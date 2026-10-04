"""Manage the external SDK process without blocking Fusion's UI thread."""
import json
import os
import queue
import signal
import subprocess
import threading
from pathlib import Path


class ChatSession:
    def __init__(self, token):
        self.token = token
        self.process = None
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.closed = False

    def start(self):
        here = Path(__file__).resolve().parent
        config = json.loads((here / 'runtime_config.json').read_text())
        python = config['python']
        if not Path(python).is_file():
            raise RuntimeError('CadBot Python environment is missing. Reinstall the add-in from the project.')
        # Fusion embeds Python and exports its runtime paths. Inheriting those
        # makes the venv interpreter load Fusion's incompatible standard library.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('PYTHON', 'DYLD_', 'QT_', 'QML'))
               and key not in ('__PYVENV_LAUNCHER__', 'VIRTUAL_ENV', 'LD_LIBRARY_PATH')}
        env.update(CADBOT_BRIDGE_TOKEN=self.token, CADBOT_PROJECT=config['project'], PYTHONUNBUFFERED='1')
        env['PATH'] = os.pathsep.join([str(Path(python).parent), '/opt/homebrew/bin', '/usr/local/bin', env.get('PATH', '')])
        self.process = subprocess.Popen([python, '-E', '-s', '-u', str(here / 'agent' / 'palette_worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', env=env, cwd=config['project'], start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                pass
        if not self.closed:
            self.events.put({'kind': 'error', 'text': 'The agent stopped. Click Reconnect to restart it.'})
            self.events.put({'kind': 'disconnected'})

    def _stderr(self):
        # Drain stderr so the subprocess cannot block on a full pipe.
        for line in self.process.stderr:
            if not self.closed:
                try:
                    with open(os.path.expanduser('~/cadbot_debug.log'), 'a') as log:
                        log.write('[CadBot worker] ' + line)
                except OSError:
                    pass

    def _write(self):
        while True:
            command = self.commands.get()
            if command is None:
                return
            try:
                self.process.stdin.write(json.dumps(command) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                if not self.closed:
                    self.events.put({'kind': 'error', 'text': 'Agent connection closed. Click Reconnect.'})
                return

    def send(self, command):
        if self.closed or self.process is None or self.process.poll() is not None:
            raise RuntimeError('Agent is disconnected. Click Reconnect.')
        self.commands.put(command)

    def poll(self):
        events = []
        for _ in range(150):
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                break
        return events

    def close(self):
        self.closed = True
        process = self.process
        if process is None:
            return
        self.commands.put({'action': 'shutdown'})
        self.commands.put(None)
        # Reap the whole owned process group if graceful shutdown stalls.
        def reap():
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            for pipe in (process.stdin, process.stdout, process.stderr):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
        threading.Thread(target=reap, daemon=True).start()
