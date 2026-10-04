"""Transport contracts: no Fusion process or network needed."""
import contextlib
import io
import json
from email.message import Message
from unittest import TestCase
from unittest.mock import Mock, patch
import urllib.error

import test_startup
import bridge_cli
import fusion_cli
from bridge import server
from bridge.commands import prepare


def response(data, status=200):
    result = io.BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())
    result.status = status
    return result


class ClientTransportTests(TestCase):
    def test_help_and_bad_arguments_do_not_touch_network(self):
        with patch.object(bridge_cli, '_open') as request:
            result, status = bridge_cli.call('fusion', {'command': 'fusion design sketches arcs add --help'})
            self.assertEqual(status, 200)
            self.assertIn('points-mm', result['help'])
            result, status = bridge_cli.call('fusion', {'command': 'fusion design reset --bogus'})
            self.assertEqual(status, 400)
        request.assert_not_called()

    def test_connection_error_is_not_stale_build(self):
        with patch.object(bridge_cli, '_open', side_effect=urllib.error.URLError('connection refused')):
            result, status = bridge_cli.runtime_status()
        self.assertEqual((status, result['status']), (503, 'bridge_unavailable'))

    def test_malformed_response_and_authentication_are_actionable(self):
        for raw in (b'not json', b'[]', b'null', b'"string"', b'\xff'):
            with self.subTest(raw=raw), patch.object(bridge_cli, '_open', return_value=response(raw)):
                result, status = bridge_cli._request('/ping')
                self.assertEqual((status, result['status']), (502, 'invalid_response'))
        error = urllib.error.HTTPError('http://localhost', 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
        with patch.object(bridge_cli, '_open', side_effect=error):
            result, status = bridge_cli.runtime_status()
        self.assertEqual((status, result['status']), (401, 'unauthorized'))

    def test_timeout_is_not_retried(self):
        with patch.object(bridge_cli, '_open', side_effect=TimeoutError) as request:
            result, status = bridge_cli._request('/tool', {'tool': 'fusion', 'args': {}})
        self.assertEqual((status, result['status']), (504, 'timeout'))
        self.assertIn('may still finish', result['error'])
        request.assert_called_once()

    def test_nonlocal_configuration_never_sends_token(self):
        for url in ('https://example.org', 'http://example.org', 'http://user:pass@localhost', 'http://localhost/path',
                    'http://[', 'http://localhost:invalid', 'http://localhost:99999'):
            with self.subTest(url=url), patch.object(bridge_cli, 'BRIDGE_URL', url), \
                    patch.object(bridge_cli, '_open') as request:
                result, status = bridge_cli._request('/ping')
                self.assertEqual(status, 400)
                request.assert_not_called()

    def test_terminal_help_readable_and_json_available(self):
        for argv, is_json in ((['design', 'sketches', 'arcs', 'add', '--help'], False),
                              (['--json', 'help', 'design', 'sketches'], True)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(fusion_cli.main(argv), 0)
            if is_json:
                self.assertIn('commands', json.loads(output.getvalue()))
            else:
                self.assertTrue(output.getvalue().startswith('usage: fusion'))

    def test_strict_inputs_reject_duplicates_and_nonfinite_json(self):
        for command in ('fusion design reset --document-id a --document-id b',
                        'fusion design sketches splines add --sketch s --points-mm "[[0,0],[NaN,2]]"',
                        'fusion design sketches splines add --sketch s --points-mm "[[0,0],[1e999,2]]"'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                prepare({'command': command})
        for args in (None, [], 'command'):
            with self.assertRaises(ValueError):
                prepare(args)


class ServerTransportTests(TestCase):
    def handler(self, body, **headers):
        instance = server._make_handler().__new__(server._make_handler())
        instance.path = '/tool'
        instance.headers = Message()
        instance.headers['X-CadBot-Token'] = 'test-token'
        instance.headers['Content-Length'] = str(len(body))
        for name, value in headers.items():
            instance.headers.replace_header(name, value) if name in instance.headers else instance.headers.add_header(name, value)
        instance.rfile = io.BytesIO(body)
        instance._send_json = Mock()
        return instance

    def test_invalid_envelopes_never_dispatch(self):
        dispatcher = Mock()
        for body in (b'[]', b'null', b'{"tool":[]}', b'{"tool":"fusion","args":[]}', b'{"tool":"fusion","args":null}', b'\xff'):
            with self.subTest(body=body), patch.dict(server._state, token='test-token', dispatcher=dispatcher):
                handler = self.handler(body)
                handler.do_POST()
                self.assertEqual(handler._send_json.call_args.args[0], 400)
        dispatcher.call.assert_not_called()

    def test_invalid_lengths_and_transfer_encoding_never_dispatch(self):
        dispatcher = Mock()
        for headers in ({'Content-Length': '-1'}, {'Content-Length': 'oops'},
                        {'Content-Length': str(server.MAX_REQUEST_BYTES + 1)},
                        {'Transfer-Encoding': 'chunked'}):
            with self.subTest(headers=headers), patch.dict(server._state, token='test-token', dispatcher=dispatcher):
                handler = self.handler(b'{}', **headers)
                handler.do_POST()
                self.assertIn(handler._send_json.call_args.args[0], (400, 413))
        dispatcher.call.assert_not_called()

    def test_unauthorized_requests_never_dispatch(self):
        with patch.dict(server._state, token='other-token', dispatcher=Mock()):
            handler = self.handler(b'{}')
            handler.do_POST()
            self.assertEqual(handler._send_json.call_args.args[0], 401)
            server._state['dispatcher'].call.assert_not_called()

    def test_direct_mutations_and_admin_cannot_bypass_cli(self):
        fn = Mock()
        for tool in ('create_sketch', 'arcs_add', 'body_delete', 'documents_close', 'files_delete', 'render_animation'):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, 'structured fusion CLI'):
                server._execute_tool(tool, fn, {})
            with patch.dict(server._state, token='test-token', dispatcher=Mock(), tools={tool: fn}):
                handler = self.handler(json.dumps({'tool': tool, 'args': {}}).encode())
                handler.do_POST()
                self.assertEqual(handler._send_json.call_args.args[0], 400)
                server._state['dispatcher'].call.assert_not_called()
        fn.assert_not_called()

    def test_checkpoint_shape_rejected_before_initialization(self):
        for args in ({'action': 'begin'}, {'action': 'restore', 'id': ''}, {'action': 'wat'}):
            with patch.object(server, '_undo', None), self.assertRaises(ValueError):
                server._checkpoint(args)

    def test_cannot_bind_public_interface(self):
        with self.assertRaisesRegex(ValueError, 'loopback'):
            server.BridgeServer('0.0.0.0', 8765, Mock())

    def test_unverified_release_paths_refuse_before_any_native_access(self):
        commands = (
            'fusion design forms create-from-tsm --tsm-description fixture',
            'fusion design forms inspect --form fixture',
            'fusion design forms rename --form fixture --name test',
            'fusion design forms delete --form fixture',
            'fusion design configurations edit --configuration fixture --column-index 0 --expression "12 mm"',
        )
        with patch.object(server, '_undo', None):
            for command in commands:
                with self.subTest(command=command):
                    result = server._execute_tool('fusion', None, {'command': command})
                    self.assertEqual(result['status'], 'blocked')
                    self.assertEqual(result['error']['code'], 'release_capability_unavailable')
                    self.assertEqual(result['changes'], [])
