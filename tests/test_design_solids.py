"""Host-side tests for bounded typed solid feature operations."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from tools import design_solids as solids


class Collection:
    def __init__(self, values=()):
        self.values = list(values)
        self.count = len(self.values)

    def item(self, index):
        return self.values[index]


class SolidFeatureTests(unittest.TestCase):
    def test_unique_rejects_ambiguous_name(self):
        values = [SimpleNamespace(name="Hole", entityToken="a"),
                  SimpleNamespace(name="Hole", entityToken="b")]
        with self.assertRaisesRegex(ValueError, "resolve uniquely"):
            solids._unique(values, "Hole", "Feature")

    def test_index_validation_stops_before_api_item(self):
        collection = Mock(count=2)
        with self.assertRaisesRegex(ValueError, "out of range"):
            solids._indexed(collection, 4, "Face")
        collection.item.assert_not_called()

    def test_counterbore_requires_specific_dimensions(self):
        point = object()
        sketch = SimpleNamespace(sketchPoints=Collection([point]),
                                 parentComponent=SimpleNamespace(
                                     name="Root", features=SimpleNamespace(holeFeatures=Mock())))
        with patch.object(solids, "_sketch", return_value=sketch), \
             self.assertRaisesRegex(ValueError, "counterbore hole requires"):
            solids.holes_create({"sketch": "s", "point_index": 0,
                                 "diameter_mm": 4, "kind": "counterbore"})

    def test_shell_requires_nonzero_thickness(self):
        body = SimpleNamespace(parentComponent=SimpleNamespace(), faces=Collection())
        with patch.object(solids, "_body", return_value=body), \
             patch.object(solids.adsk.core, "ObjectCollection", Mock(), create=True), \
             self.assertRaisesRegex(ValueError, "positive"):
            solids.shells_create({"body": "b", "inside_mm": 0, "outside_mm": 0})

    def test_loft_requires_two_sections(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            solids.lofts_create({"sketches": ["one"]})

    def test_edit_rejects_family_specific_unknown_field(self):
        feature = SimpleNamespace(name="Shell", entityToken="f", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[])
        component = SimpleNamespace(name="Root")
        with patch.object(solids, "_feature", return_value=("shell", component, feature)):
            with self.assertRaisesRegex(ValueError, "Unsupported shell edit fields"):
                solids.solid_feature_edit({"feature": "f", "expressions": {"diameter": "4 mm"}})

    def test_hole_expression_edit_is_verified_and_recomputed(self):
        parameter = SimpleNamespace(name="diameter", expression="4 mm", unit="mm")
        feature = SimpleNamespace(name="Hole", entityToken="f", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[],
                                  holeDiameter=parameter, tipAngle=None,
                                  counterboreDiameter=None, counterboreDepth=None,
                                  countersinkDiameter=None, countersinkAngle=None)
        component = SimpleNamespace(name="Root")
        design = Mock(); design.computeAll.return_value = True
        with patch.object(solids, "_feature", return_value=("hole", component, feature)), \
             patch.object(solids, "_design", return_value=design):
            result = solids.solid_feature_edit({
                "feature": "f", "expressions": {"diameter": "5 mm"}})
        self.assertEqual(parameter.expression, "5 mm")
        self.assertEqual(result["changes"]["diameter"]["before"], "4 mm")
        design.computeAll.assert_called_once_with()

    def test_capabilities_expose_explicit_preview_blocker(self):
        result = solids.capabilities({})
        self.assertIn("preview-only", result["blockers"][0])
        self.assertEqual(result["families"]["drafts"]["create"],
                         "fixed-plane single-angle")

    def test_loft_adds_each_profile_in_order(self):
        sections = Mock()
        loft_input = SimpleNamespace(loftSections=sections, isSolid=None, isClosed=None)
        feature = SimpleNamespace(name="Loft", entityToken="loft-token", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[])
        lofts = Mock(); lofts.createInput.return_value = loft_input; lofts.add.return_value = feature
        component = SimpleNamespace(name="Root", features=SimpleNamespace(loftFeatures=lofts))
        a_profile, b_profile = object(), object()
        sketches = [SimpleNamespace(parentComponent=component, profiles=Collection([a_profile])),
                    SimpleNamespace(parentComponent=component, profiles=Collection([b_profile]))]
        with patch.object(solids, "_sketch", side_effect=sketches), \
             patch.object(solids, "_operation", return_value=7):
            result = solids.lofts_create({"sketches": ["a", "b"], "operation": "new"})
        self.assertEqual([call.args[0] for call in sections.add.call_args_list],
                         [a_profile, b_profile])
        self.assertTrue(loft_input.isSolid)
        self.assertEqual(result["token"], "loft-token")

    def test_sweep_builds_path_from_exact_curve(self):
        profile, path = object(), object()
        curve = SimpleNamespace(objectType="adsk::fusion::SketchLine")
        sweep_input = SimpleNamespace(isSolid=None, taperAngle=None, twistAngle=None)
        feature = SimpleNamespace(name="Sweep", entityToken="sweep-token", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[],
                                  taperAngle=None, twistAngle=None)
        sweeps = Mock(); sweeps.createInput.return_value = sweep_input; sweeps.add.return_value = feature
        features = SimpleNamespace(sweepFeatures=sweeps, createPath=Mock(return_value=path))
        component = SimpleNamespace(name="Root", features=features)
        profile_sketch = SimpleNamespace(parentComponent=component, profiles=Collection([profile]))
        path_sketch = SimpleNamespace(parentComponent=component, sketchCurves=Collection([curve]))
        with patch.object(solids, "_sketch", side_effect=[profile_sketch, path_sketch]), \
             patch.object(solids, "_operation", return_value=3):
            result = solids.sweeps_create({"profile_sketch": "p", "path_sketch": "q",
                                           "path_curve_index": 0})
        features.createPath.assert_called_once_with(curve, True)
        sweeps.createInput.assert_called_once_with(profile, path, 3)
        self.assertEqual(result["family"], "sweep")

    def test_loft_adds_token_selected_rails(self):
        sections, guides = Mock(), Mock()
        guides.addRail.return_value = object()
        loft_input = SimpleNamespace(loftSections=sections, centerLineOrRails=guides,
                                     isSolid=None, isClosed=None)
        feature = SimpleNamespace(name="Loft", entityToken="loft-token", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[])
        lofts = Mock(); lofts.createInput.return_value = loft_input; lofts.add.return_value = feature
        component = SimpleNamespace(name="Root", features=SimpleNamespace(
            loftFeatures=lofts, createPath=Mock(return_value="rail-path")))
        sketches = [SimpleNamespace(parentComponent=component, profiles=Collection([object()])),
                    SimpleNamespace(parentComponent=component, profiles=Collection([object()]))]
        curve = SimpleNamespace(objectType="adsk::fusion::BRepEdge",
                                body=SimpleNamespace(parentComponent=component))
        with patch.object(solids, "_sketch", side_effect=sketches), \
             patch.object(solids, "_entity_token", return_value=curve), \
             patch.object(solids, "_operation", return_value=7):
            solids.lofts_create({"sketches": ["a", "b"],
                                 "rails": [{"token": "edge-token"}]})
        guides.addRail.assert_called_once_with("rail-path")

    def test_sweep_accepts_token_path_and_guide_rail(self):
        profile = object()
        sweep_input = SimpleNamespace(isSolid=None, taperAngle=None, twistAngle=None,
                                      guideRail=None, profileScaling=None)
        feature = SimpleNamespace(name="Sweep", entityToken="sweep-token", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[],
                                  taperAngle=None, twistAngle=None)
        sweeps = Mock(); sweeps.createInput.return_value = sweep_input; sweeps.add.return_value = feature
        features = SimpleNamespace(sweepFeatures=sweeps,
                                   createPath=Mock(side_effect=["path", "guide"]))
        component = SimpleNamespace(name="Root", features=features)
        sketch = SimpleNamespace(parentComponent=component, profiles=Collection([profile]))
        curves = [SimpleNamespace(objectType="adsk::fusion::BRepEdge") for _ in range(2)]
        scaling = SimpleNamespace(SweepProfileScaleOption="scale")
        with patch.object(solids, "_sketch", return_value=sketch), \
             patch.object(solids, "_entity_token", side_effect=curves), \
             patch.object(solids, "_operation", return_value=3), \
             patch.object(solids.adsk.fusion, "SweepProfileScalingOptions", scaling,
                          create=True):
            solids.sweeps_create({"profile_sketch": "p", "path_entity": "path-token",
                                  "guide_rail": {"token": "guide-token"}})
        self.assertEqual(sweep_input.guideRail, "guide")
        self.assertEqual(sweep_input.profileScaling, "scale")

    def test_failed_edit_recomputes_after_restoring_expression(self):
        parameter = SimpleNamespace(name="diameter", expression="4 mm", unit="mm")
        feature = SimpleNamespace(name="Hole", entityToken="f", isSuppressed=False,
                                  healthState="ok", errorOrWarningMessage="", bodies=[],
                                  holeDiameter=parameter, tipAngle=None,
                                  counterboreDiameter=None, counterboreDepth=None,
                                  countersinkDiameter=None, countersinkAngle=None)
        component = SimpleNamespace(name="Root")
        design = Mock(); design.computeAll.side_effect = [False, True]
        with patch.object(solids, "_feature", return_value=("hole", component, feature)), \
             patch.object(solids, "_design", return_value=design), \
             self.assertRaisesRegex(RuntimeError, "original values were restored"):
            solids.solid_feature_edit({
                "feature": "f", "expressions": {"diameter": "5 mm"}})
        self.assertEqual(parameter.expression, "4 mm")
        self.assertEqual(design.computeAll.call_count, 2)


if __name__ == "__main__":
    unittest.main()
