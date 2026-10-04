import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch
import test_startup
from tools import motion


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.limits=SimpleNamespace(isMinimumValueEnabled=True,minimumValue=-1,isMaximumValueEnabled=True,maximumValue=1)
        self.m=SimpleNamespace(rotationValue=0.1,rotationLimits=self.limits)
        self.j=SimpleNamespace(name='Hip',entityToken='token',jointMotion=self.m)
        observer=patch.object(motion,'observe_axes',return_value={});observer.start();self.addCleanup(observer.stop)
        p=patch.object(motion,'resolve',return_value=self.j);p.start();self.addCleanup(p.stop)

    def test_degrees_and_limits(self):
        motion.drive({'joint':'Hip','axis':'rotation','value':30})
        self.assertAlmostEqual(self.m.rotationValue,0.5235987756)
        with self.assertRaises(ValueError):motion.drive({'joint':'Hip','axis':'rotation','value':90})

    def test_tracks_validate_before_moving(self):
        for keys in ([[0,0],[1,90]],[[0,0],[0,10]],[[0.1,0],[1,10]]):
            with self.assertRaises(ValueError):motion.prepare_tracks([{'joint':'Hip','axis':'rotation','keys':keys}])
        self.assertEqual(self.m.rotationValue,0.1)
        self.assertEqual(motion.sample([[0,0],[1,20]],0.25),5)

    def test_capture_failure_propagates_to_controller(self):
        viewport=Mock();viewport.saveAsImageFile.return_value=False
        with patch.object(motion.adsk.core.Application,'get',return_value=SimpleNamespace(activeViewport=viewport)):
            with self.assertRaisesRegex(RuntimeError,'capture'):
                motion.run_preview(motion.render, {'tracks':[{'joint':'Hip','axis':'rotation','keys':[[0,10],[1,20]]}],'seconds':1,'fps':2})
        self.assertNotEqual(self.m.rotationValue,0.1)

    def test_render_creates_player_without_claiming_restoration(self):
        viewport=Mock()
        viewport.saveAsImageFile.side_effect=lambda path,w,h: Path(path).write_bytes(b'fixture-png')>0
        with tempfile.TemporaryDirectory() as folder, patch.object(motion.tempfile,'mkdtemp',return_value=folder), patch.object(motion.adsk.core.Application,'get',return_value=SimpleNamespace(activeViewport=viewport)):
            result=motion.run_preview(motion.render, {'tracks':[{'joint':'Hip','axis':'rotation','keys':[[0,10],[1,20]]}],'seconds':1,'fps':2})
            self.assertEqual(result['frames'],2)
            self.assertIn('data:image/png;base64',Path(result['path']).read_text())
            self.assertNotEqual(self.m.rotationValue,0.1)

    def test_open_rejects_arbitrary_file(self):
        with self.assertRaises(ValueError): motion.open_preview({'path':'/etc/passwd'})

    def test_frame_budget_rejected_before_motion(self):
        with self.assertRaises(ValueError): motion.run_preview(motion.render, {'tracks':[], 'fps':30, 'seconds':10})
        self.assertEqual(self.m.rotationValue,0.1)

    def test_unlimited_rotation_accepts_full_turn_equivalence(self):
        self.limits.isMinimumValueEnabled=False
        self.limits.isMaximumValueEnabled=False
        self.m.rotationValue=2*motion.math.pi
        self.assertAlmostEqual(motion.deviation(self.m,'rotationValue',0)[1],0)
        self.limits.isMaximumValueEnabled=True
        self.assertAlmostEqual(motion.deviation(self.m,'rotationValue',0)[1],360)

    def test_preview_and_restoration_have_separate_tolerances(self):
        tracks=motion.prepare_tracks([{'joint':'Hip','axis':'rotation','keys':[[0,0],[1,10]]}])
        self.m.rotationValue=motion.math.radians(0.04)
        self.assertTrue(motion.position_report(tracks,[0],['Hip'])[0]['within_tolerance'])
        report=motion.position_report(tracks,[0],['Hip'],restoring=True)[0]
        self.assertFalse(report['within_tolerance'])
        self.assertEqual(report['units'],'deg')
        self.assertEqual(report['joint'],'Hip')

    def test_check_leaves_rollback_to_controller(self):
        result=motion.run_preview(motion.check, {'tracks':[{'joint':'Hip','axis':'rotation','keys':[[0,0],[1,20]]}]})
        self.assertEqual(len(result['samples']),5)
        self.assertNotEqual(self.m.rotationValue,0.1)

    def test_direct_preview_calls_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'transaction controller'):
            motion.check({'tracks':[]})
        with self.assertRaisesRegex(RuntimeError, 'transaction controller'):
            motion.render({'tracks':[]})


class InstanceMotionTests(unittest.TestCase):
    def fixture(self):
        limits=SimpleNamespace(isMinimumValueEnabled=False,isMaximumValueEnabled=False)
        def proxy(occ):
            return SimpleNamespace(name='Hip',objectType='Joint',assemblyContext=occ,
                jointMotion=SimpleNamespace(rotationValue=0,rotationLimits=limits))
        native=SimpleNamespace(name='Hip',createForAssemblyContext=proxy)
        component=SimpleNamespace(name='leg',joints=[native],asBuiltJoints=[])
        first=SimpleNamespace(fullPathName='front:1+leg:1',component=component)
        second=SimpleNamespace(fullPathName='rear:1+leg:1',component=component)
        root=SimpleNamespace(name='root',joints=[],asBuiltJoints=[],allOccurrences=[first,second])
        return SimpleNamespace(rootComponent=root)

    def test_shared_definition_has_distinct_proxy_selectors(self):
        with patch.object(motion,'_get_design',return_value=self.fixture()):
            entries=motion.joint_entries()
            self.assertEqual([e['selector'] for e in entries],['front:1+leg:1::joint:Hip','rear:1+leg:1::joint:Hip'])
            self.assertEqual(motion.resolve(entries[1]['selector']).assemblyContext.fullPathName,'rear:1+leg:1')
            with self.assertRaisesRegex(ValueError,'ambiguous'):motion.resolve('Hip')
            with self.assertRaises(ValueError):motion.resolve('old-definition-token')
            tracks=motion.prepare_tracks([{'joint':e['selector'],'axis':'rotation','keys':[[0,0],[1,2]]} for e in entries])
            self.assertEqual(len(tracks),2)

    def test_duplicate_instance_axis_rejected(self):
        with patch.object(motion,'_get_design',return_value=self.fixture()):
            t={'joint':'front:1+leg:1::joint:Hip','axis':'rotation','keys':[[0,0],[1,2]]}
            with self.assertRaisesRegex(ValueError,'Duplicate'):motion.prepare_tracks([t,t])

    def test_observer_reports_passive_and_other_instance_motion(self):
        before={('front::joint:Passive','rotation'):10,('rear::joint:Hip','rotation'):0}
        with patch.object(motion,'observe_axes',return_value={('front::joint:Passive','rotation'):11,('rear::joint:Hip','rotation'):2}):
            changes=motion.observed_changes(before)
            self.assertEqual([r['delta'] for r in changes],[1,2])
