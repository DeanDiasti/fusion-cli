import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import test_startup
from test_core_design import Collection
from bridge.commands import prepare
from tools import sketch_support as support, features


class FaceModelingTests(unittest.TestCase):
    def test_grammar_accepts_new_workflow_and_preserves_distance(self):
        for command in (
            'sketches create --support face --component Bracket',
            'sketches create --component Bracket --plane XY --offset-mm 3',
            'sketches project --sketch holes --entities \'["face"]\' --linked false',
            'features extrude --sketch holes --extent through-all --operation cut --participants \'["body"]\' --direction both',
            'features extrude --sketch holes --distance-mm -3 --operation cut',
            'bodies topology list --body plate --kind edges --limit 10 --offset 5',
        ):
            with self.subTest(command=command):
                prepare({'command': 'fusion design ' + command})

    def test_incompatible_flags_are_rejected_offline(self):
        for command in (
            'sketches create --support face --plane XY',
            'sketches create --support face --offset-mm 0',
            'sketches project --sketch holes --entities \'[1]\'',
            'sketches project --sketch holes --entities \'["a","a"]\'',
            'features extrude --sketch holes',
            'features extrude --sketch holes --distance-mm 0',
            'features extrude --sketch holes --distance-mm 3 --direction both',
            'features extrude --sketch holes --extent through-all --operation new',
            'features extrude --sketch holes --extent through-all --operation cut',
            'features extrude --sketch holes --extent through-all --operation cut --participants \'["b"]\' --distance-mm 5',
            'features extrude --sketch holes --distance-mm 5 --operation new --participants \'["b"]\'',
        ):
            with self.subTest(command=command), self.assertRaises(ValueError):
                prepare({'command': 'fusion design ' + command})

    def test_nonplanar_and_wrong_owner_support_rejected(self):
        parent = object()
        face = NS(objectType='adsk::fusion::BRepFace', nativeObject=None,
                  body=NS(parentComponent=parent), geometry=object())
        with patch.object(support.design_structure, '_resolve_token', return_value=face), \
                patch.object(support.adsk.core, 'Plane', NS(cast=lambda _: None), create=True):
            with self.assertRaisesRegex(ValueError, 'planar'):
                support.support('face')
        with patch.object(support.design_structure, '_resolve_token', return_value=face), \
                patch.object(support.adsk.core, 'Plane', NS(cast=lambda _: object()), create=True):
            self.assertIs(support.support('face')[0], parent)
            with self.assertRaisesRegex(ValueError, 'component'):
                support.support('face', object())

    def test_projection_prevalidates_all_sources_before_mutation(self):
        parent = object()
        sketch = NS(parentComponent=parent, project2=Mock())
        edge = NS(objectType='adsk::fusion::BRepEdge', body=NS(parentComponent=parent))
        wrong = NS(objectType='adsk::fusion::BRepEdge', body=NS(parentComponent=object()))
        with patch.object(support, '_find_sketch', return_value=sketch), \
                patch.object(support.design_structure, '_resolve_token', side_effect=[edge, wrong]):
            with self.assertRaisesRegex(ValueError, 'same component'):
                support.project_geometry({'sketch':'s', 'entities':['a','b']})
        sketch.project2.assert_not_called()

    def test_projection_link_state_is_verified(self):
        parent = object()
        edge = NS(objectType='adsk::fusion::BRepEdge', body=NS(parentComponent=parent))
        projected = NS(isValid=True, isLinked=True, objectType='adsk::fusion::SketchLine', entityToken='projected')
        sketch = NS(parentComponent=parent, project2=Mock(return_value=[projected]),
                    entityToken='s', profiles=Collection([]))
        with patch.object(support, '_find_sketch', return_value=sketch), \
                patch.object(support.design_structure, '_resolve_token', return_value=edge):
            self.assertEqual(support.project_geometry({'sketch':'s','entities':['e']})['created_count'], 1)
            with self.assertRaisesRegex(RuntimeError, 'link state'):
                support.project_geometry({'sketch':'s','entities':['e'],'linked':False})

    def test_through_all_uses_direction_and_explicit_participants(self):
        parent = Mock()
        parent.parentDesign.rootComponent = parent
        body = NS(parentComponent=parent, isSolid=True)
        sketch = NS(parentComponent=parent, profiles=Collection([object()]))
        operations = NS(NewBodyFeatureOperation=0, JoinFeatureOperation=1, CutFeatureOperation=2, IntersectFeatureOperation=3)
        ext = parent.features.extrudeFeatures.createInput.return_value
        parent.features.extrudeFeatures.add.return_value.healthState = 0
        with patch.object(features, '_find_sketch', return_value=sketch), \
                patch('tools.design_solids._body', return_value=body), \
                patch.object(features.adsk.fusion, 'FeatureOperations', operations, create=True), \
                patch.object(features.adsk.fusion, 'FeatureHealthStates', NS(HealthyFeatureHealthState=0), create=True), \
                patch.object(features.adsk.fusion, 'ThroughAllExtentDefinition', Mock(), create=True), \
                patch.object(features.adsk.fusion, 'ExtentDirections', NS(PositiveExtentDirection=1,NegativeExtentDirection=2), create=True), \
                patch.object(features.adsk.core, 'ValueInput', Mock(), create=True):
            features.extrude({'sketch':'s','extent':'through-all','operation':'cut','participants':['b'],'direction':'negative'})
            self.assertEqual(ext.setOneSideExtent.call_args.args[1], 2)
            self.assertEqual(ext.participantBodies, [body])
            ext.setDistanceExtent.assert_not_called()
            ext.setOneSideExtent.return_value = False
            parent.features.extrudeFeatures.add.reset_mock()
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                features.extrude({'sketch':'s','extent':'through-all','operation':'cut','participants':['b']})
            parent.features.extrudeFeatures.add.assert_not_called()
            ext.setOneSideExtent.return_value = True
            parent.features.extrudeFeatures.add.return_value.healthState = 1
            parent.features.extrudeFeatures.add.return_value.errorOrWarningMessage = 'No target body'
            with self.assertRaisesRegex(RuntimeError, 'healthy extrusion'):
                features.extrude({'sketch':'s','extent':'through-all','operation':'cut','participants':['b']})


    def test_moved_component_refuses_before_feature_input_creation(self):
        parent = Mock()
        parent.parentDesign.rootComponent.allOccurrencesByComponent.return_value = Collection([
            NS(transform2=NS(asArray=lambda:[1,0,0,5,0,1,0,0,0,0,1,0,0,0,0,1]))])
        body = NS(parentComponent=parent, isSolid=True)
        sketch = NS(parentComponent=parent, profiles=Collection([object()]))
        with patch.object(features, '_find_sketch', return_value=sketch), \
                patch('tools.design_solids._body', return_value=body):
            with self.assertRaisesRegex(ValueError, 'moved or rotated'):
                features.extrude({'sketch':'s','extent':'through-all','operation':'cut','participants':['b']})
        parent.features.extrudeFeatures.createInput.assert_not_called()
