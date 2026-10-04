"""Opt-in live SDK smoke test. Sends only synthetic fixture data, never Fusion data."""
import json
import base64
import struct
import zlib
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if request['tool'] == '_checkpoint':
            data = json.dumps({'available': []}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        assert request['tool'] == 'fusion' and request['args']['command'] in ('fusion design inspect', 'design inspect'), 'Only fixture design inspection is allowed'
        data = json.dumps({'fixture': True, 'body_count': 0, 'bodies': [], 'units': 'mm'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='cadbot-fixture-') as cwd:
        os.environ['CADBOT_PROJECT'] = cwd
        os.environ['CADBOT_HISTORY_DIR'] = str(Path(cwd) / 'history')
        os.environ['CADBOT_BRIDGE_URL'] = 'http://127.0.0.1:' + str(server.server_port)
        import palette_worker
        events = []
        def capture(kind, **data):
            events.append({'kind': kind, **data})
        palette_worker.emit = capture
        worker = palette_worker.Worker()
        try:
            worker.account_status()
            worker.run_turn({'text': 'Connection test using a synthetic fixture only. Call the fusion tool with command fusion design inspect once and report its body_count. Do not use other tools or read files.'})
            calls = [e for e in events if e['kind'] == 'tool' and e['phase'] == 'completed']
            assert any(e['item'].get('tool') == 'fusion' and e['item'].get('status') == 'completed' for e in calls), [e for e in events if e["kind"] in ("error", "tool", "message")]
            assert any(e['kind'] == 'delta' for e in events), events
            print('PASS: streamed response and synthetic MCP get_state result')
            # Generate a solid red PNG using the standard library.
            def chunk(kind, data):
                return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
            png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 32, 8, 2, 0, 0, 0))
            png += chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\x00\x00' * 32) * 32)) + chunk(b'IEND', b'')
            events.clear()
            worker.run_turn({'text': 'Image input connection test only. Name the color in the attached synthetic image. Do not use any tools.',
                             'images': [{'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}]})
            replies = ' '.join(e.get('text', '') for e in events if e['kind'] == 'message')
            assert 'red' in replies.lower(), events
            assert not any(e['kind'] == 'error' for e in events), events
            print('PASS: generated image accepted and identified as red')
            original_thread = worker.thread
            user_events = [e for e in worker.history.events(worker.conversation) if e['kind'] == 'user']
            assert user_events[1]['previous_turn']
            events.clear()
            worker.restore_message({'id': user_events[1]['id'], 'mode': 'conversation'})
            assert not any(e['kind'] == 'error' for e in events), events
            assert worker.thread.id != original_thread.id
            turns = worker.thread.read(include_turns=True).thread.turns
            assert len(turns) == 1, len(turns)
            assert len(original_thread.read(include_turns=True).thread.turns) == 2
            print('PASS: bounded conversation branch retains first turn and preserves original two-turn conversation')
        finally:
            worker.close()
            server.shutdown()
