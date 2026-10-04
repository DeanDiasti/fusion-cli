import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fusion_addin/CadBot'))
import chat

class ProcessTests(unittest.TestCase):
    def test_managed_worker_send_poll_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'agent').mkdir()
            (root / 'runtime_config.json').write_text(json.dumps({'python': sys.executable, 'project': temp}))
            (root / 'agent/palette_worker.py').write_text('''import json, sys
print(json.dumps({'kind':'ready', 'signed_in':True}), flush=True)
for line in sys.stdin:
    data = json.loads(line)
    if data['action'] == 'shutdown': break
    print(json.dumps({'kind':'echo', 'text':data.get('text')}), flush=True)
''')
            with patch.object(chat, '__file__', str(root / 'chat.py')), patch.dict(os.environ, {'PYTHONHOME': '/invalid/fusion/python', 'PYTHONPATH': '/invalid/fusion/modules', 'DYLD_FRAMEWORK_PATH': '/invalid/fusion/frameworks', '__PYVENV_LAUNCHER__': '/invalid/python'}):
                session = chat.ChatSession('test-token')
                session.start()
            session.send({'action': 'send', 'text': 'hello'})
            events = []
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                events.extend(session.poll())
                if any(e.get('kind') == 'echo' for e in events):
                    break
                time.sleep(.01)
            self.assertIn({'kind': 'echo', 'text': 'hello'}, events)
            session.close()
            session.process.wait(timeout=4)
            self.assertEqual(session.process.returncode, 0)
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                session.send({'action': 'send'})

if __name__ == '__main__': unittest.main()
