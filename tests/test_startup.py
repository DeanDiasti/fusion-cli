"""Host-side regression tests; these do not substitute for Fusion integration."""
import importlib
import sys
import threading
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'fusion_addin' / 'CadBot'))
sys.path.insert(0, str(ROOT / 'agent'))
adsk = ModuleType('adsk')
core = ModuleType('adsk.core')
fusion = ModuleType('adsk.fusion')
adsk.core, adsk.fusion = core, fusion
core.CustomEventHandler = type('CustomEventHandler', (), {})
core.ApplicationEventHandler = type('ApplicationEventHandler', (), {})
core.HTMLEventHandler = type('HTMLEventHandler', (), {})
core.CommandCreatedEventHandler = type('CommandCreatedEventHandler', (), {})
core.Application = SimpleNamespace(get=Mock())
core.PaletteDockingStates = SimpleNamespace(PaletteDockStateRight=4, PaletteDockStateFloating=0)
sys.modules.update({'adsk': adsk, 'adsk.core': core, 'adsk.fusion': fusion})
import CadBot
from bridge.dispatch import Dispatcher
from bridge.server import BridgeServer
import codex_agent
from tools import state


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock()
        core.Application.get.return_value = self.app
        self.app.fireCustomEvent.return_value = True

    def test_dispatch_registers_typed_handler_and_delivers_result(self):
        dispatcher = Dispatcher()
        dispatcher.start()
        self.app.registerCustomEvent.assert_called_once_with('CadBotDispatchEvent')
        event = self.app.registerCustomEvent.return_value
        handler = event.add.call_args.args[0]
        self.assertIsInstance(handler, core.CustomEventHandler)
        result = []
        thread = threading.Thread(target=lambda: result.append(dispatcher.call(lambda: 42)))
        thread.start()
        # Wait until the worker has queued work, without touching Fusion APIs.
        for _ in range(1000):
            if not dispatcher._queue.empty():
                break
            threading.Event().wait(.001)
        handler.notify(None)
        thread.join(2)
        self.assertEqual(result, [(True, 42)])
        self.app.fireCustomEvent.assert_called_once_with('CadBotDispatchEvent')
        dispatcher.stop()
        self.app.unregisterCustomEvent.assert_called_once()
        self.assertFalse(dispatcher.call(lambda: 42)[0])

    def test_html_poll_executes_when_custom_event_is_rejected(self):
        dispatcher = Dispatcher()
        dispatcher.start()
        self.app.fireCustomEvent.return_value = False
        queued = threading.Event()
        self.app.fireCustomEvent.side_effect = lambda *_: queued.set() or False
        result = []
        main_thread = threading.get_ident()
        t = threading.Thread(target=lambda: result.append(dispatcher.call(threading.get_ident)))
        t.start()
        self.assertTrue(queued.wait(2))
        with patch.object(CadBot, '_dispatcher', dispatcher), patch.object(CadBot, '_chat', None):
            CadBot._ChatHTMLHandler().notify(SimpleNamespace(action='poll', returnData=''))
        t.join(2)
        self.assertEqual(result, [(True, main_thread)])
        dispatcher.stop()

    def test_timed_out_work_never_executes_on_later_event(self):
        dispatcher = Dispatcher()
        dispatcher.start()
        self.app.fireCustomEvent.return_value = False
        fn = Mock()
        with patch('bridge.dispatch._CALL_TIMEOUT_SECONDS', 0.001):
            ok, result = dispatcher.call(fn)
        self.assertFalse(ok)
        dispatcher.drain()
        fn.assert_not_called()
        dispatcher.stop()

    def test_stop_cancels_queued_work(self):
        dispatcher = Dispatcher()
        dispatcher.start()
        queued = threading.Event()
        self.app.fireCustomEvent.side_effect = lambda *_: queued.set() or False
        fn = Mock()
        result = []
        t = threading.Thread(target=lambda: result.append(dispatcher.call(fn)))
        t.start()
        self.assertTrue(queued.wait(2))
        dispatcher.stop()
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertFalse(result[0][0])
        dispatcher.drain()
        fn.assert_not_called()

    def test_port_conflict_is_synchronous(self):
        with patch('bridge.server.ThreadingHTTPServer', side_effect=OSError('port occupied')):
            with self.assertRaisesRegex(OSError, 'port occupied'):
                BridgeServer('localhost', 8765, Mock())

    def test_run_builds_palette_with_correct_signature(self):
        CadBot._bridge = None
        self.app.userInterface.palettes.itemById.return_value = None
        with patch.object(CadBot, '_log'), patch.object(CadBot, 'Dispatcher'), patch.object(CadBot, 'BridgeServer'), patch.object(CadBot, 'threading'), patch.object(CadBot, '_create_toolbar_button'):
            CadBot.run(None)
            args = self.app.userInterface.palettes.add.call_args.args
            self.assertEqual(args[3:], (False, True, True, 440, 650))
            from urllib.parse import urlparse, unquote
            self.assertTrue(Path(unquote(urlparse(args[2]).path)).is_file())
            self.assertEqual(CadBot._palette.dockingState, 4)
            self.assertFalse(CadBot._palette.isDockedInCanvas)
            self.assertTrue(CadBot._palette.isVisible)
            CadBot.stop(None)

    def test_running_addin_recreates_missing_palette(self):
        CadBot._bridge = Mock()
        CadBot._ui = self.app.userInterface
        CadBot._palette = Mock(isValid=False)
        self.app.userInterface.palettes.itemById.return_value = None
        with patch.object(CadBot, '_log'):
            CadBot.run(None)
        self.app.userInterface.palettes.add.assert_called_once()
        self.assertTrue(CadBot._palette.isVisible)
        CadBot._bridge = None

    def test_startup_defers_window_until_application_ready(self):
        CadBot._bridge = None
        self.app.userInterface.palettes.itemById.return_value = None
        with patch.object(CadBot, '_log'), patch.object(CadBot, 'Dispatcher'), patch.object(CadBot, 'BridgeServer'), patch.object(CadBot, 'threading'), patch.object(CadBot, '_create_toolbar_button'):
            CadBot.run({'IsApplicationStartup': True})
            self.app.userInterface.palettes.add.assert_not_called()
            handler = self.app.startupCompleted.add.call_args.args[0]
            handler.notify(None)
            self.app.userInterface.palettes.add.assert_called_once()
            CadBot.stop(None)

    def test_startup_failure_cleans_dispatcher(self):
        CadBot._bridge = None
        with patch.object(CadBot, '_log'), patch.object(CadBot, 'Dispatcher') as factory, patch.object(CadBot, 'BridgeServer', side_effect=OSError('port occupied')):
            CadBot.run(None)
            factory.return_value.stop.assert_called_once()
            self.assertIsNone(CadBot._dispatcher)

    def test_shutdown_survives_palette_deletion_failure(self):
        palette = Mock(isValid=True, isNative=False)
        palette.deleteMe.side_effect = RuntimeError('3 : Cannot delete native palette.')
        bridge, thread, dispatcher = Mock(), Mock(), Mock()
        CadBot._palette, CadBot._bridge = palette, bridge
        CadBot._bridge_thread, CadBot._dispatcher = thread, dispatcher
        CadBot._ui = self.app.userInterface
        with patch.object(CadBot, '_log'), patch.object(CadBot, '_remove_toolbar_button') as toolbar:
            CadBot.stop(None)
            toolbar.assert_called_once()
            bridge.shutdown.assert_called_once()
            thread.join.assert_called_once_with(timeout=5)
            dispatcher.stop.assert_called_once()
            CadBot.stop(None)  # Repeated stop must be harmless.
            bridge.shutdown.assert_called_once()
        self.app.userInterface.messageBox.assert_not_called()
        self.assertIsNone(CadBot._palette)
        self.assertIsNone(CadBot._dispatcher)

    def test_palette_cleanup_only_deletes_valid_custom_palette(self):
        with patch.object(CadBot, '_log'):
            for valid, native, expected in [(False, False, 0), (True, True, 0), (True, False, 1)]:
                palette = Mock(isValid=valid, isNative=native)
                CadBot._delete_palette(palette)
                self.assertEqual(palette.deleteMe.call_count, expected)

    def test_html_actions_use_managed_chat(self):
        import json
        CadBot._chat = None
        handler = CadBot._ChatHTMLHandler()
        with patch.object(CadBot, 'ChatSession') as factory, patch.object(CadBot, '_load_token', return_value='test'):
            args = SimpleNamespace(action='ready', data='{}', returnData='')
            handler.notify(args)
            factory.return_value.start.assert_called_once()
            self.assertTrue(json.loads(args.returnData)['ok'])
            args.action, args.data = 'send', '{"text":"hello"}'
            handler.notify(args)
            factory.return_value.send.assert_called_once_with({'text': 'hello', 'action': 'send'})
            factory.return_value.poll.return_value = [{'kind': 'delta', 'text': 'Hi'}]
            args.action = 'poll'
            handler.notify(args)
            self.assertEqual(json.loads(args.returnData)['events'][0]['text'], 'Hi')
        CadBot._chat = None

    def test_agent_checks_matching_runtime_before_startup(self):
        with patch('codex_agent.runtime_status', return_value=({'runtime': {'ok': True}}, 200)):
            self.assertTrue(codex_agent.check_bridge())
        with patch('codex_agent.runtime_status', return_value=({'error': 'stale runtime'}, 409)):
            self.assertFalse(codex_agent.check_bridge())

    def test_line_dimension_uses_fusion_aligned_orientation(self):
        from tools import sketch
        fake_sketch = Mock()
        fake_sketch.sketchCurves.count = 4
        orientation = SimpleNamespace(AlignedDimensionOrientation=2)
        with patch.object(sketch, '_find_sketch', return_value=fake_sketch), patch.object(core, 'Point3D', Mock(), create=True), patch.object(fusion, 'DimensionOrientations', orientation, create=True):
            result = sketch.add_dimension({'sketch': 'Cube', 'target': 'line_length', 'curve_index': 0, 'value_mm': 20})
        dimensions = fake_sketch.sketchDimensions
        self.assertEqual(dimensions.addDistanceDimension.call_args.args[2], 2)
        self.assertEqual(dimensions.addDistanceDimension.return_value.parameter.expression, '20 mm')
        self.assertEqual(result['value_mm'], 20)

    def test_measurement_finds_child_component_bodies(self):
        from tools import inspection
        body = SimpleNamespace(name='Body1')
        occurrence = SimpleNamespace(fullPathName='Part:1', bRepBodies=[body])
        root = SimpleNamespace(bRepBodies=[], allOccurrences=[occurrence])
        with patch.object(inspection, '_get_root', return_value=root):
            self.assertIs(inspection._body_by_name_or_last('Part:1/Body1'), body)
            self.assertIs(inspection._body_by_name_or_last(None), body)

    def test_screenshot_uses_supported_api_and_checks_failure(self):
        from tools import inspection
        def save(path, width, height):
            Path(path).write_bytes(b'png-test')
            return True
        viewport = self.app.activeViewport
        viewport.saveAsImageFile.side_effect = save
        result = inspection.screenshot_viewport({})
        self.assertEqual(result['png_base64'], 'cG5nLXRlc3Q=')
        viewport.saveAsImageFile.assert_called_once()
        viewport.saveAsImageFile.side_effect = None
        viewport.saveAsImageFile.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'could not save'):
            inspection.screenshot_viewport({})

    def test_existing_parameter_edit_and_conflict(self):
        from tools import editing
        parameter = SimpleNamespace(name='d1', expression='100 mm')
        design = Mock()
        design.parentDocument.name = 'Linkage'
        design.allParameters.itemByName.return_value = parameter
        design.computeAll.return_value = True
        args = {'document': 'Linkage', 'changes': [{'name': 'd1', 'expected_expression': '100 mm', 'expression': '75 mm'}]}
        with patch.object(editing, '_get_design', return_value=design), patch.object(editing, 'list_timeline', return_value={'items': []}):
            result = editing.edit_parameters(args)
            self.assertEqual(parameter.expression, '75 mm')
            self.assertEqual(result['changes'][0]['before'], '100 mm')
            with self.assertRaisesRegex(ValueError, 'changed since inspection'):
                editing.edit_parameters(args)
            parameter.expression = '100 mm'
            design.computeAll.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'original expressions restored'):
                editing.edit_parameters(args)
            self.assertEqual(parameter.expression, '100 mm')

    def test_delete_targets_entity_and_reports_failure(self):
        from tools import inspection
        entity = Mock(isValid=True)
        entity.name = 'Bearing:1'
        entity.deleteMe.return_value = True
        timeline = Mock(count=1)
        timeline.item.return_value = SimpleNamespace(entity=entity)
        with patch.object(inspection, '_get_design', return_value=SimpleNamespace(timeline=timeline)):
            self.assertEqual(inspection.delete_features({'names': ['Bearing:1']})['deleted'], ['Bearing:1'])
            entity.deleteMe.side_effect = RuntimeError('Deletion blocked')
            result = inspection.delete_features({'names': ['Bearing:1']})
            self.assertIn('error', result)
            self.assertEqual(result['failed'][0]['error'], 'Deletion blocked')

    def test_state_accepts_tool_args(self):
        fusion.Design = SimpleNamespace(cast=lambda _: None)
        self.assertIn('error', state.get_state({}))

if __name__ == '__main__':
    unittest.main()
