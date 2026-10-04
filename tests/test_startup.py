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
sys.path.insert(0, str(ROOT / 'cli'))
adsk = ModuleType('adsk')
core = ModuleType('adsk.core')
fusion = ModuleType('adsk.fusion')
adsk.core, adsk.fusion = core, fusion
core.CustomEventHandler = type('CustomEventHandler', (), {})
core.ApplicationEventHandler = type('ApplicationEventHandler', (), {})
core.ApplicationCommandEventHandler = type('ApplicationCommandEventHandler', (), {})
core.DocumentEventHandler = type('DocumentEventHandler', (), {})
core.HTMLEventHandler = type('HTMLEventHandler', (), {})
core.CommandCreatedEventHandler = type('CommandCreatedEventHandler', (), {})
core.Application = SimpleNamespace(get=Mock())
core.PaletteDockingStates = SimpleNamespace(PaletteDockStateRight=4, PaletteDockStateFloating=0)
sys.modules.update({'adsk': adsk, 'adsk.core': core, 'adsk.fusion': fusion})
import CadBot
from bridge.dispatch import Dispatcher
from bridge.server import BridgeServer
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


    def test_timed_out_work_never_executes_on_later_event(self):
        dispatcher = Dispatcher()
        dispatcher.start()
        self.app.fireCustomEvent.return_value = True
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
        self.app.fireCustomEvent.side_effect = lambda *_: queued.set() or True
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




    def test_startup_failure_cleans_dispatcher(self):
        CadBot._bridge = None
        with patch.object(CadBot, 'Dispatcher') as factory, patch.object(CadBot, 'BridgeServer', side_effect=OSError('port occupied')):
            CadBot.run(None)
            factory.return_value.stop.assert_called_once()
            self.assertIsNone(CadBot._dispatcher)





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

    def test_rejected_event_uses_hidden_main_thread_callback(self):
        dispatcher = Dispatcher(); dispatcher.start()
        queued = threading.Event()
        self.app.fireCustomEvent.side_effect = lambda *_: queued.set() or False
        fn = Mock(return_value=42); result = []
        thread = threading.Thread(target=lambda: result.append(dispatcher.call(fn)))
        thread.start(); self.assertTrue(queued.wait(2)); fn.assert_not_called()
        handler = dispatcher._pump_handler
        handler.notify(SimpleNamespace(action='arbitrary', data=''))
        handler.notify(SimpleNamespace(action='dispatch', data='untrusted command'))
        fn.assert_not_called()
        handler.notify(SimpleNamespace(action='dispatch', data=''))
        thread.join(2); self.assertEqual(result, [(True,42)])
        fn.assert_called_once(); dispatcher.stop()
        self.app.userInterface.palettes.add.assert_called_once()
        self.assertEqual(self.app.userInterface.palettes.add.call_args.args[3:],
                         (False, False, False, 1, 1))

    def test_hidden_callback_failure_cleans_registered_event(self):
        self.app.userInterface.palettes.add.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'dispatch callback'):
            Dispatcher().start()
        self.app.unregisterCustomEvent.assert_called_once()

    def test_hidden_callback_cleanup_failure_still_unregisters_event(self):
        dispatcher = Dispatcher(); dispatcher.start()
        dispatcher._pump.deleteMe.side_effect = RuntimeError('stale UI object')
        with self.assertRaisesRegex(RuntimeError, 'stale UI object'):
            dispatcher.stop()
        self.app.unregisterCustomEvent.assert_called_once()
        self.assertFalse(dispatcher._running)

    def test_registration_failure_is_reported_before_starting(self):
        self.app.registerCustomEvent.return_value = None
        with self.assertRaisesRegex(RuntimeError, 'register'):
            Dispatcher().start()

    def test_bridge_starts_without_chat_toolbar_or_worker(self):
        CadBot._bridge = CadBot._startup_handler = None
        with patch.object(CadBot, 'Dispatcher') as dispatcher, patch.object(CadBot, 'BridgeServer') as bridge, patch.object(CadBot, 'threading'):
            CadBot.run(None)
            dispatcher.return_value.start.assert_called_once()
            bridge.assert_called_once_with('localhost', 8765, dispatcher.return_value)
            self.app.userInterface.palettes.add.assert_not_called()
            self.app.userInterface.commandDefinitions.addButtonDefinition.assert_not_called()
            CadBot.run(None); bridge.assert_called_once()
            CadBot.stop(None)

    def test_bridge_startup_waits_for_fusion_initialization(self):
        CadBot._bridge = CadBot._startup_handler = None
        self.app.isStartupComplete = False
        with patch.object(CadBot, '_start_bridge') as start:
            CadBot.run({'IsApplicationStartup': True})
            start.assert_not_called()
            handler = self.app.startupCompleted.add.call_args.args[0]
            handler.notify(None)
            start.assert_called_once()
            self.assertIsNone(CadBot._startup_handler)

    def test_shutdown_continues_after_checkpoint_and_server_errors(self):
        from bridge import server
        bridge, thread, dispatcher = Mock(), Mock(), Mock()
        bridge.shutdown.side_effect = RuntimeError('shutdown failed')
        controller = Mock(); controller.close.side_effect = RuntimeError('close failed')
        CadBot._bridge, CadBot._bridge_thread, CadBot._dispatcher = bridge, thread, dispatcher
        with patch.object(server, '_undo', controller):
            CadBot.stop(None)
            thread.join.assert_called_once_with(timeout=5)
            dispatcher.stop.assert_called_once()
            self.assertIsNone(server._undo)
            CadBot.stop(None); bridge.shutdown.assert_called_once()
        self.assertIsNone(CadBot._dispatcher)

if __name__ == '__main__':
    unittest.main()
