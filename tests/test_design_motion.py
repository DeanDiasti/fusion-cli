"""Contract and failure-path checks for editing and sampled motion inspection."""
import json
import math
import shlex
import subprocess
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import test_startup
from test_core_design import Collection
from bridge import commands, server
from tools import sketch_edit, interference, motion


class MotionSpecTests(unittest.TestCase):
    def track(self, **extra):
        return {'joint':'Hinge','axis':'rotation','keys':[[0,0],[1,40]],**extra}

    def test_easing_values_endpoints_and_holds(self):
        for mode, expected in [('linear',10),('ease-in',2.5),('ease-out',17.5),('ease-in-out',6.25),('step',0)]:
            self.assertAlmostEqual(motion.sample([[0,0],[1,40]],.25,mode),expected)
            self.assertEqual(motion.sample([[0,0],[1,40]],1,mode),40)
            self.assertEqual(motion.sample([[0,0],[.3,10],[.6,10],[1,20]],.45,mode),10)
        self.assertEqual(motion.sample([[0,0],[.5,20],[1,40]],.5,'step'),20)

    def test_invalid_shapes_fail_offline(self):
        for track in (self.track(easing='bounce'),self.track(extra=1),self.track(joint=''),
                      self.track(keys=[[0,True],[1,10]]),self.track(keys=[[0,0],[.8,10]])):
            cmd='fusion design motion check --tracks '+shlex.quote(json.dumps([track]))
            with self.subTest(track=track),self.assertRaises(ValueError):commands.prepare({'command':cmd})
        for count in (1,62,True):
            with self.assertRaises(ValueError):commands.sample_times([self.track()],count)

    def test_samples_include_keyframes_and_are_bounded(self):
        t=self.track(keys=[[0,0],[.13,10],[1,20]])
        self.assertEqual(commands.sample_times([t],3),[0,.13,.5,1])
        tracks=[self.track(keys=[[0,0],[i/1000,1],[1,20]]) for i in range(1,25)]
        self.assertEqual(len(commands.sample_times(tracks,61)),85)

    def test_real_offline_cli_loads_shared_validation(self):
        p=subprocess.run([sys.executable,str(test_startup.ROOT/'cli/fusion_cli.py'),
            'design','motion','check','--tracks',json.dumps([self.track(easing='invalid')])],capture_output=True,text=True)
        self.assertEqual(p.returncode,2,p.stderr)
        self.assertIn('easing',p.stdout)

    def test_inspection_is_dispatched_through_preview(self):
        cmd='fusion design motion inspect --tracks '+shlex.quote(json.dumps([self.track()]))+' --entities \'["A","B"]\''
        controller=Mock();controller.ledger.active=True
        test_startup.core.Application.get.return_value.userInterface.activeWorkspace.id='FusionSolidEnvironment'
        with patch.object(server,'_undo',controller):server._execute_tool('fusion',None,{'command':cmd})
        controller.preview.assert_called_once();controller.execute.assert_not_called()

    def test_interference_resolution_fails_before_motion(self):
        with patch.object(motion,'prepare_tracks',return_value=[]),patch.object(interference,'resolve_entities',side_effect=ValueError('missing')),patch.object(motion,'move_frame') as move:
            with self.assertRaisesRegex(ValueError,'missing'):
                motion.run_preview(motion.inspect_motion,{'tracks':[self.track()],'entities':['A','B']})
            move.assert_not_called()


class PreviewPollingTests(unittest.TestCase):
    def test_status_during_capture_does_not_check_temporary_signature(self):
        from bridge.fusion_undo import FusionUndo
        owner=FusionUndo.__new__(FusionUndo)
        owner.ledger=NS(active=True,reason=None,_check=Mock())
        owner.owned=True;owner.head=Mock(side_effect=AssertionError('temporary signature must not be checked'))
        result=owner.status()
        self.assertTrue(result['busy']);self.assertTrue(result['active'])
        self.assertEqual(result['available'],[])
        owner.ledger._check.assert_not_called();owner.head.assert_not_called()


class SketchEditTests(unittest.TestCase):
    def test_offset_prevalidates_sources_before_native_creation(self):
        constraints=Mock();sketch=NS(geometricConstraints=constraints)
        with patch.object(sketch_edit,'_find_sketch',return_value=sketch),patch.object(sketch_edit.core_design,'_curve',side_effect=[object(),ValueError('wrong sketch')]):
            with self.assertRaises(ValueError):sketch_edit.offset({'sketch':'s','entities':['a','b'],'distance_mm':2})
        constraints.createOffsetInput.assert_not_called()

    def test_zero_offset_fails_offline(self):
        for entities in ('["a","a"]','[1]','["a"]'):
            with self.assertRaises(ValueError):commands.prepare({'command':'fusion design sketches offset --sketch s --entities '+shlex.quote(entities)+' --distance-mm 0'})

    def test_trim_refuses_linked_and_fixed_curves(self):
        for linked,fixed in ((True,False),(False,True)):
            curve=NS(isLinked=linked,isFixed=fixed,entityToken='curve',trim=Mock())
            with patch.object(sketch_edit,'_find_sketch',return_value=object()),patch.object(sketch_edit.core_design,'_point'),patch.object(sketch_edit.core_design,'_curve',return_value=curve):
                with self.assertRaisesRegex(ValueError,'linked or fixed'):sketch_edit.trim({'sketch':'s','entity':'curve','x_mm':1,'y_mm':2})
            curve.trim.assert_not_called()


class InterferenceTests(unittest.TestCase):
    def fixture(self):
        root=NS(bRepBodies=[],allOccurrences=[])
        def body(name,volume=1):return NS(name=name,entityToken=name,objectType='adsk::fusion::BRepBody',isValid=True,isSolid=True,assemblyContext=None,parentComponent=root,volume=volume)
        a,b=body('A'),body('B');root.bRepBodies=[a,b]
        design=NS(rootComponent=root,findEntityByToken=Mock(return_value=[]))
        return design,a,b

    def test_duplicate_resolved_entities_and_child_native_refused(self):
        design,a,b=self.fixture();design.findEntityByToken.return_value=[a]
        with patch.object(interference,'_design',return_value=design):
            with self.assertRaisesRegex(ValueError,'duplicate'):interference.resolve_entities(['A','alias-A'])
            a.parentComponent=object()
            with self.assertRaisesRegex(ValueError,'Native child'):interference.resolve_entities(['A','B'])

    def test_reports_volume_without_creating_persistent_bodies(self):
        design,a,b=self.fixture();results=Collection([NS(entityOne=a,entityTwo=b,interferenceBody=NS(volume=.125))])
        results.createBodies=Mock();design.createInterferenceInput=Mock(return_value=NS());design.analyzeInterference=Mock(return_value=results)
        with patch.object(interference.adsk.core,'ObjectCollection',NS(create=Mock(return_value=Mock())),create=True):report=interference.analyze(design,[a,b])
        self.assertEqual(report['total_pair_volume_mm3'],125)
        self.assertFalse(design.createInterferenceInput.return_value.areCoincidentFacesIncluded)
        results.createBodies.assert_not_called()

    def test_missing_native_result_is_error(self):
        design,a,b=self.fixture();design.createInterferenceInput=Mock(return_value=NS());design.analyzeInterference=Mock(return_value=None)
        with patch.object(interference.adsk.core,'ObjectCollection',NS(create=Mock(return_value=Mock())),create=True):
            with self.assertRaisesRegex(RuntimeError,'results'):interference.analyze(design,[a,b])
