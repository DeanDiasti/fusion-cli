"""Chat regressions using fake SDK turns and HTTP responses, no account required."""
import json
import sys
import threading
import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import cad_mcp
try:
    import palette_worker
except ImportError:
    palette_worker = None

class MCPTests(unittest.TestCase):
    def test_tools_discoverable(self):
        tools = cad_mcp.respond({'method': 'tools/list'})['tools']
        self.assertEqual([t['name'] for t in tools], ['fusion'])
        self.assertEqual(len(tools), 1)

    def test_tool_error_is_visible(self):
        with patch.object(cad_mcp, 'call', return_value=({'error': 'No design'}, 500)):
            result = cad_mcp.respond({'method': 'tools/call', 'params': {'name': 'fusion', 'arguments': {'command': 'fusion design inspect'}}})
            self.assertTrue(result['isError'])
            self.assertIn('No design', result['content'][0]['text'])

    def test_screenshot_becomes_image_content(self):
        with patch.object(cad_mcp, 'call', return_value=({'path': 'test.png', 'png_base64': 'abc'}, 200)):
            result = cad_mcp.respond({'method': 'tools/call', 'params': {'name': 'fusion', 'arguments': {'command': 'fusion viewport screenshot'}}})
            self.assertEqual(result['content'][1]['type'], 'image')
            self.assertNotIn('png_base64', result['content'][0]['text'])

@unittest.skipIf(palette_worker is None, 'Run with .venv/bin/python for SDK tests')
class WorkerTests(unittest.TestCase):
    def worker(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.dict(os.environ, CADBOT_HISTORY_DIR=directory.name), patch.object(palette_worker, 'Codex'):
            worker = palette_worker.Worker()
            worker.checkpoint = Mock(return_value={'available': []})
            return worker

    def test_selected_model_applies_without_replacing_chat(self):
        w = self.worker()
        w.thread = Mock(id="test-thread")
        w.thread.turn.return_value.stream.return_value = []
        w.models = {'test-model': SimpleNamespace(default_reasoning_effort='medium', input_modalities=['text'])}
        with patch.object(palette_worker, 'emit') as emit:
            w.run_turn({'text': 'Hello', 'model': 'test-model'})
            self.assertEqual(w.thread.turn.call_args.kwargs, {'model': 'test-model', 'effort': 'medium'})
            w.thread.turn.reset_mock()
            w.run_turn({'text': 'Hello', 'model': 'missing'})
            w.thread.turn.assert_not_called()
            self.assertTrue(any('unavailable' in c.kwargs.get('text', '') for c in emit.call_args_list))

    def test_new_thread_receives_cli_system_prompt(self):
        w = self.worker()
        thread = Mock(id='prompt-thread')
        w.codex.thread_start.return_value = thread
        w.codex._client.request.return_value = SimpleNamespace(
            data=[SimpleNamespace(name='cadbot', tools=['fusion'], tools_error=None)])
        self.assertIs(w.new_thread(), thread)
        instructions = w.codex.thread_start.call_args.kwargs['developer_instructions']
        self.assertIs(instructions, palette_worker.SYSTEM_PROMPT)
        self.assertIn('fusion app inspect', instructions)

    def test_file_attachments_are_staged_without_path_traversal(self):
        w = self.worker()
        w.thread = Mock(id="test-thread")
        w.thread.turn.return_value.stream.return_value = []
        with patch.object(palette_worker, 'emit'):
            w.run_turn({'text': 'Read this', 'files': [{'name': '../../notes.txt', 'url': 'data:text/plain;base64,aGVsbG8='}]})
        staged = list(Path(w.attachment_root).rglob('notes.txt'))
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].read_text(), 'hello')
        inputs = w.thread.turn.call_args.args[0]
        self.assertIn(str(staged[0]), inputs[1].text)

    def test_saved_chat_reopens_original_thread_after_store_reload(self):
        from history import History
        w = self.worker()
        w.thread = Mock(id='original-thread')
        w.thread.turn.return_value.stream.return_value = []
        with patch.object(palette_worker, 'emit'):
            w.run_turn({'text': 'Remember the bracket'})
        key = w.conversation
        w.history = History(w.history.root)
        self.assertEqual(w.history.list()[0]['title'], 'Remember the bracket')
        self.assertEqual(list(w.history.events(key))[0]['text'], 'Remember the bracket')
        w.thread = None
        with patch.object(w, 'new_thread', return_value=Mock(id='original-thread')) as resume, patch.object(palette_worker, 'emit') as output:
            w.open_history(key)
            resume.assert_called_once_with('original-thread')
            self.assertTrue(any(c.args == ('replay',) for c in output.call_args_list))
        w.busy = True
        with self.assertRaisesRegex(ValueError, 'Stop'):
            w.open_history(key)

    def test_conversation_restore_forks_before_selected_message_without_design_undo(self):
        w = self.worker()
        w.thread = Mock(id='original-thread')
        w.conversation = w.history.create('original-thread', {'text': 'Original'})
        original = w.conversation
        w.history.append(original, {'kind': 'user', 'id': 'm1', 'previous_turn': None, 'text': 'first'})
        w.history.append(original, {'kind': 'user', 'id': 'm2', 'previous_turn': 'turn1', 'text': 'second'})
        w.codex._client.request.return_value = SimpleNamespace(thread=SimpleNamespace(id='fork'))
        with patch.object(w, 'new_thread', return_value=Mock(id='fork')), patch.object(palette_worker, 'emit'):
            w.restore_message({'id': 'm2', 'mode': 'conversation'})
        w.checkpoint.assert_not_called()
        params = w.codex._client.request.call_args.args[1]
        self.assertEqual(params['threadId'], 'original-thread')
        self.assertEqual(params['lastTurnId'], 'turn1')
        self.assertIn('cadbot', params['config']['mcp_servers'])
        self.assertNotEqual(w.conversation, original)
        self.assertEqual(len(list(w.history.events(original))), 2)
        users = [e['id'] for e in w.history.events(w.conversation) if e['kind'] == 'user']
        self.assertEqual(users, ['m1'])
        self.assertIn('NOT undone', w.history.read(w.conversation)['pending_restore_notice'])

    def test_design_restore_never_calls_model_or_forks(self):
        w = self.worker()
        w.thread = Mock(id='thread')
        w.conversation = w.history.create('thread', {'text': 'Original'})
        w.history.append(w.conversation, {'kind': 'user', 'id': 'm1', 'previous_turn': None, 'text': 'first'})
        with patch.object(palette_worker, 'emit'):
            w.restore_message({'id': 'm1', 'mode': 'design'})
        w.checkpoint.assert_called_once_with('restore', id='m1')
        w.thread.turn.assert_not_called()
        w.codex._client.request.assert_not_called()

    def test_combined_restore_failure_preserves_active_conversation(self):
        w = self.worker()
        w.thread = Mock(id='original')
        w.conversation = w.history.create('original', {'text': 'Original'})
        key = w.conversation
        w.history.append(key, {'kind': 'user', 'id': 'm1', 'previous_turn': None, 'text': 'first'})
        w.checkpoint.side_effect = RuntimeError('outside edit')
        with patch.object(w, 'new_thread', return_value=Mock(id='branch')), patch.object(palette_worker, 'emit') as output:
            w.restore_message({'id': 'm1', 'mode': 'both'})
        self.assertEqual(w.conversation, key)
        self.assertEqual(w.thread.id, 'original')
        self.assertTrue(any('outside edit' in c.kwargs.get('text', '') for c in output.call_args_list))

    def test_new_thread_requires_cad_tool_inventory(self):
        w = self.worker()
        w.codex._client.request.return_value = SimpleNamespace(data=[])
        with self.assertRaisesRegex(RuntimeError, 'CAD tools failed'):
            w.new_thread()
        w.codex._client.request.return_value = SimpleNamespace(data=[SimpleNamespace(name='cadbot', tools={'get_state': {}}, tools_error=None)])
        self.assertIs(w.new_thread(), w.codex.thread_start.return_value)
        config = w.codex.thread_start.call_args.kwargs['config']
        self.assertTrue(config['mcp_servers']['cadbot']['required'])

    def test_images_passed_as_sdk_image_inputs_and_context_reused(self):
        w = self.worker()
        w.thread = Mock(id="test-thread")
        turn = w.thread.turn.return_value
        turn.stream.return_value = []
        with patch.object(palette_worker, 'emit') as emit:
            w.run_turn({'text': 'Build from this', 'images': [{'url': 'data:image/png;base64,YQ=='}]})
            inputs = w.thread.turn.call_args.args[0]
            self.assertEqual(inputs[0].text, 'Build from this')
            self.assertEqual(inputs[1].url, 'data:image/png;base64,YQ==')
            w.run_turn({'text': 'Make it taller'})
            self.assertEqual(w.thread.turn.call_count, 2)
            self.assertFalse(w.busy)
            self.assertEqual(emit.call_args.args, ('idle',))

    def test_cancel_before_turn_start_prevents_execution(self):
        w = self.worker()
        w.thread = Mock(id="test-thread")
        w.cancel()
        with patch.object(palette_worker, 'emit'):
            w.run_turn({'text': 'test'})
        w.thread.turn.assert_not_called()

    def test_cancel_interrupts_active_turn(self):
        w = self.worker()
        w.active = Mock()
        w.cancel()
        w.active.interrupt.assert_called_once()

    def test_failure_clears_busy_state(self):
        w = self.worker()
        w.thread = Mock(id="test-thread")
        w.thread.turn.side_effect = RuntimeError('Offline')
        w.busy = True
        with patch.object(palette_worker, 'emit') as emit:
            w.run_turn({'text': 'test'})
            self.assertIn(unittest.mock.call('error', text='Offline'), emit.call_args_list)
        self.assertFalse(w.busy)

    def test_event_normalization(self):
        payload = Mock()
        payload.model_dump.return_value = {'itemId': 'a', 'delta': 'Hello'}
        event = SimpleNamespace(method='item/agentMessage/delta', payload=payload)
        self.assertEqual(palette_worker.normalize_event(event), {'kind': 'delta', 'id': 'a', 'text': 'Hello'})
        payload.model_dump.return_value = {'item': {'id': 'b', 'type': 'mcpToolCall', 'result': {'data': 'hidden'}}}
        event.method = 'item/completed'
        normalized = palette_worker.normalize_event(event)
        self.assertEqual(normalized['kind'], 'tool')
        self.assertNotIn('data', normalized['item']['result'])

if __name__ == '__main__':
    unittest.main()
