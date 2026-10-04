"""Host checks for curved sketches and explicit profile selection."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import test_startup
from test_core_design import Collection, circle, point
from bridge.commands import prepare
from bridge import server
from tools import core_design as curves, features


class SketchCurveTests(unittest.TestCase):
    def setUp(self):
        self.arc = circle('arc-token')
        self.arc.objectType = 'adsk::fusion::SketchArc'
        self.arc.startSketchPoint = point(0, 0)
        self.arc.endSketchPoint = point(2, 0)
        self.arc.length = 3.14159
        self.spline = circle('spline-token')
        self.spline.objectType = 'adsk::fusion::SketchFittedSpline'
        self.spline.fitPoints = Collection([point(0, 0), point(1, 2), point(2, 0)])
        self.spline.isClosed = False
        self.spline.length = 4.5
        self.sketch = NS(
            name='Outline', entityToken='sketch-token',
            sketchCurves=NS(
                sketchArcs=NS(addByThreePoints=Mock(return_value=self.arc)),
                sketchFittedSplines=NS(add=Mock(return_value=self.spline))),
            sketchPoints=NS(add=Mock(return_value=NS(
                isValid=True, entityToken='point-token', geometry=NS(x=1, y=2)))),
        )
        for patcher in (
            patch.object(curves, '_find_sketch', return_value=self.sketch),
            patch.object(curves.adsk.core, 'Point3D', NS(create=lambda x, y, z: NS(x=x, y=y, z=z)), create=True),
            patch.object(curves.adsk.core, 'ObjectCollection', NS(create=lambda: self.collection()), create=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def collection(self):
        collection = Collection()
        collection.add = collection.append
        return collection

    def test_arc_converts_mm_and_returns_actual_geometry(self):
        result = curves.arcs_add({'sketch': 'Outline', 'points_mm': [[0, 0], [10, 10], [20, 0]]})
        points = self.sketch.sketchCurves.sketchArcs.addByThreePoints.call_args.args
        self.assertEqual([(p.x, p.y, p.z) for p in points], [(0, 0, 0), (1, 1, 0), (2, 0, 0)])
        self.assertEqual(result['arc']['token'], 'arc-token')
        self.assertEqual(result['arc']['end'], {'x_mm': 20, 'y_mm': 0})
        self.assertEqual(result['arc']['radius_mm'], 10)

    def test_invalid_arc_points_never_create_geometry(self):
        for points in ([], [[0, 0], [1, 1]], [[0, 0], [1, 1], [2, 2]],
                       [[0, 0], [0, 0], [1, 1]], [[0, 0], [1, True], [2, 0]],
                       [[0, 0], [1, float('nan')], [2, 0]],
                       [[0, 0], [1, 1, 1], [2, 0]]):
            with self.subTest(points=points), self.assertRaises(ValueError):
                curves.arcs_add({'sketch': 'Outline', 'points_mm': points})
        self.sketch.sketchCurves.sketchArcs.addByThreePoints.assert_not_called()

    def test_closed_spline_converts_points_and_reports_closure(self):
        result = curves.splines_add({'sketch': 'Outline', 'points_mm': [[0, 0], [10, 20], [20, 0]], 'closed': True})
        points = self.sketch.sketchCurves.sketchFittedSplines.add.call_args.args[0]
        self.assertEqual([(p.x, p.y) for p in points], [(0, 0), (1, 2), (2, 0)])
        self.assertTrue(result['spline']['closed'])
        self.assertEqual(result['spline']['fit_points_mm'][1], {'x_mm': 10, 'y_mm': 20})

    def test_open_spline_accepts_two_points(self):
        result = curves.splines_add({'sketch': 'Outline', 'points_mm': [[0, 0], [10, 20]]})
        self.assertFalse(result['spline']['closed'])

    def test_invalid_spline_points_and_closure_never_create_geometry(self):
        for points, closed in (([[0, 0]], False), ([[0, 0], [1, 1]], True),
                               ([[0, 0], [1, 1], [0, 0]], True),
                               ([[i, i] for i in range(101)], False),
                               ([[0, 0], [1, float('inf')]], False),
                               ([[0, 0], [1, 1]], 'false')):
            with self.subTest(points=points, closed=closed), self.assertRaises(ValueError):
                curves.splines_add({'sketch': 'Outline', 'points_mm': points, 'closed': closed})
        self.sketch.sketchCurves.sketchFittedSplines.add.assert_not_called()

    def test_ignored_spline_closure_is_not_reported_as_success(self):
        class RefusesClosure:
            isValid = True

            @property
            def isClosed(self):
                return False

            @isClosed.setter
            def isClosed(self, value):
                pass

        self.sketch.sketchCurves.sketchFittedSplines.add.return_value = RefusesClosure()
        with self.assertRaisesRegex(RuntimeError, 'closure'):
            curves.splines_add({'sketch': 'Outline', 'closed': True,
                               'points_mm': [[0, 0], [10, 20], [20, 0]]})

    def test_fusion_creation_failures_are_errors(self):
        self.sketch.sketchCurves.sketchArcs.addByThreePoints.return_value = None
        self.sketch.sketchCurves.sketchFittedSplines.add.return_value = None
        self.sketch.sketchPoints.add.return_value = None
        for fn, args in ((curves.arcs_add, {'points_mm': [[0, 0], [1, 1], [2, 0]]}),
                         (curves.splines_add, {'points_mm': [[0, 0], [1, 1]]}),
                         (curves.points_add, {'x_mm': 1, 'y_mm': 2})):
            with self.subTest(handler=fn.__name__), self.assertRaises(RuntimeError):
                fn({'sketch': 'Outline', **args})

    def test_point_creation_uses_sketch_space_mm(self):
        result = curves.points_add({'sketch': 'Outline', 'x_mm': 10, 'y_mm': 20})
        p = self.sketch.sketchPoints.add.call_args.args[0]
        self.assertEqual((p.x, p.y, p.z), (1, 2, 0))
        self.assertEqual(result['point']['token'], 'point-token')

    def test_profiles_report_area_perimeter_centroid_and_indices(self):
        profile = NS(areaProperties=Mock(return_value=NS(area=2, perimeter=6, centroid=NS(x=1, y=2))),
                     profileLoops=Collection([object(), object()]))
        self.sketch.profiles = Collection([profile])
        result = curves.profiles_list({'sketch': 'Outline'})
        self.assertEqual(result['profiles'], [{'index': 0, 'area_mm2': 200, 'perimeter_mm': 60,
                                             'centroid': {'x_mm': 10, 'y_mm': 20}, 'loop_count': 2}])
        self.sketch.profiles.clear()
        self.assertEqual(curves.profiles_list({'sketch': 'Outline'})['profiles'], [])

    def test_commands_are_typed_and_checkpointed(self):
        for command in ('arcs add --points-mm \'[[0,0],[10,10],[20,0]]\'',
                        'splines add --points-mm \'[[0,0],[10,10],[20,0]]\' --closed true',
                        'points add --x-mm 5 --y-mm 10'):
            full = 'fusion design sketches ' + command + ' --sketch Outline'
            handler, args, mutates = prepare({'command': full})
            self.assertTrue(mutates)
            test_startup.core.Application.get.return_value.userInterface.activeWorkspace.id = 'FusionSolidEnvironment'
            with patch.object(server, '_undo', None), self.assertRaisesRegex(RuntimeError, 'checkpoint'):
                server._execute_tool('fusion', None, {'command': full})
        _, _, mutates = prepare({'command': 'fusion design sketches profiles list --sketch Outline'})
        self.assertFalse(mutates)


class FeatureProfileTests(unittest.TestCase):
    def test_profile_bounds_and_legacy_default(self):
        sketch = NS(name='Outline', profiles=Collection([object(), object()]))
        self.assertIs(features._profile_from_sketch(sketch), sketch.profiles[0])
        self.assertIs(features._profile_from_sketch(sketch, 1), sketch.profiles[1])
        for index in (-1, 2, True, 1.0):
            with self.subTest(index=index), self.assertRaises(ValueError):
                features._profile_from_sketch(sketch, index)
        sketch.profiles.clear()
        with self.assertRaisesRegex(RuntimeError, 'no closed profile'):
            features._profile_from_sketch(sketch)

    def test_features_use_selected_profile_in_sketch_component(self):
        component = Mock()
        component.features.extrudeFeatures.add.return_value.healthState = 0
        sketch = NS(profiles=Collection([object(), object()]), parentComponent=component)
        operations = NS(NewBodyFeatureOperation=0, JoinFeatureOperation=1,
                        CutFeatureOperation=2, IntersectFeatureOperation=3)
        for fn in (features.extrude, features.revolve):
            with self.subTest(handler=fn.__name__), \
                    patch.object(features, '_find_sketch', return_value=sketch) as find, \
                    patch.object(features.adsk.fusion, 'FeatureOperations', operations, create=True), \
                    patch.object(features.adsk.fusion, 'FeatureHealthStates', NS(HealthyFeatureHealthState=0), create=True), \
                    patch.object(features.adsk.core, 'ValueInput', Mock(), create=True):
                args = {'sketch': 'sketch-token', 'profile_index': 1, 'distance_mm': 10}
                fn(args)
                find.assert_called_once_with('sketch-token')
                family = component.features.extrudeFeatures if fn is features.extrude else component.features.revolveFeatures
                self.assertIs(family.createInput.call_args.args[0], sketch.profiles[1])

    def test_profile_index_parses_for_both_features(self):
        for command in ('extrude --distance-mm 5', 'revolve'):
            _, args, _ = prepare({'command': 'fusion design features ' + command + ' --sketch s --profile-index 1'})
            self.assertEqual(args['profile_index'], 1)


if __name__ == '__main__':
    unittest.main()
