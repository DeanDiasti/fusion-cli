"""Host-side tests for typed sheet-metal Design operations."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup  # Installs the host-side adsk modules.
from tools import design_sheet_metal as sheet


class Collection:
    def __init__(self, values=()):
        self.values = list(values)
        self.count = len(self.values)

    def item(self, index):
        return self.values[index]


def feature(name, token):
    return SimpleNamespace(name=name, entityToken=token, healthState=0,
                           errorOrWarningMessage="")


class SheetMetalTests(unittest.TestCase):
    def test_component_selector_rejects_ambiguous_names(self):
        values = [SimpleNamespace(name="Part", entityToken="a", id="1"),
                  SimpleNamespace(name="Part", entityToken="b", id="2")]
        with self.assertRaisesRegex(ValueError, "resolve uniquely; matches: 2"):
            sheet._unique(values, "Part", "Component")

    def test_capabilities_explain_missing_flange_creation(self):
        component = SimpleNamespace(
            name="Sheet", entityToken="component-token", activeSheetMetalRule=None,
            features=SimpleNamespace(flangeFeatures=Collection(), foldFeatures=object(),
                                     unfoldFeatures=object(), refoldFeatures=object()),
        )
        design = SimpleNamespace(
            rootComponent=SimpleNamespace(occurrences=SimpleNamespace(
                addNewSheetMetalComponent=lambda matrix: None)),
        )
        with patch.object(sheet, "_design", return_value=design), \
             patch.object(sheet, "_component", return_value=component):
            result = sheet.capabilities({})
        self.assertFalse(result["operations"]["flange-create"]["available"])
        self.assertIn("no creation method",
                      result["operations"]["flange-create"]["blocker"])
        self.assertTrue(result["operations"]["fold-create"]["available"])

    def test_rule_assignment_is_verified(self):
        rule = SimpleNamespace(name="Metric", units="mm", isUsed=True, kFactor=.44,
                               thickness=SimpleNamespace(expression="1 mm", value=.1),
                               bendRadius=SimpleNamespace(expression="1 mm", value=.1),
                               gap=SimpleNamespace(expression=".1 mm", value=.01))
        component = SimpleNamespace(name="Sheet", entityToken="c", activeSheetMetalRule=None)
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_resolve_rule", return_value=(rule, "design")):
            result = sheet.rule_assign({"component": "c", "rule": "Metric"})
        self.assertIs(component.activeSheetMetalRule, rule)
        self.assertEqual(result["rule"]["name"], "Metric")

    def test_faces_list_classifies_candidates_and_returns_tokens(self):
        plane = SimpleNamespace(entityToken="face-plane", area=4.0,
                                geometry=SimpleNamespace(objectType="adsk::core::Plane"))
        cylinder = SimpleNamespace(entityToken="face-cylinder", area=1.0,
                                   geometry=SimpleNamespace(objectType="adsk::core::Cylinder"))
        body = SimpleNamespace(name="Body", entityToken="body", isSheetMetal=True,
                               faces=Collection([plane, cylinder]))
        component = SimpleNamespace(name="Sheet", entityToken="component")
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_body", return_value=body):
            result = sheet.faces_list({"component": "component", "body": "body"})
        self.assertTrue(result["faces"][0]["planar_candidate"])
        self.assertTrue(result["faces"][1]["bend_candidate"])
        self.assertEqual(result["faces"][1]["token"], "face-cylinder")

    def test_convert_verifies_sheet_metal_result(self):
        body = SimpleNamespace(name="Body", entityToken="b", isSheetMetal=False)
        body.convertToSheetMetal = Mock(side_effect=lambda face, rule:
                                       setattr(body, "isSheetMetal", True) or True)
        rule = SimpleNamespace(name="Rule", units="mm", isUsed=True, kFactor=.4,
                               thickness=SimpleNamespace(expression="1 mm", value=.1),
                               bendRadius=SimpleNamespace(expression="1 mm", value=.1),
                               gap=SimpleNamespace(expression=".1 mm", value=.01))
        component = SimpleNamespace(activeSheetMetalRule=rule)
        face = SimpleNamespace(geometry=object())
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_body", return_value=body), \
             patch.object(sheet, "_face", return_value=face), \
             patch.object(sheet, "_resolve_rule", return_value=(rule, "design")):
            result = sheet.convert({"component": "c", "body": "b",
                                    "base_face": "f", "rule": "Rule"})
        self.assertTrue(result["body"]["sheet_metal"])
        body.convertToSheetMetal.assert_called_once_with(face, rule)

    def test_fold_create_uses_typed_input_and_angle_expression(self):
        definition = object()
        bend_lines = Mock(count=1)
        bend_lines.add.return_value = definition
        inp = SimpleNamespace(isUseCornerRelief=False, bendLines=bend_lines)
        created = feature("Fold1", "fold-token")
        created.bendLines = Collection([definition])
        folds = Mock()
        folds.createInput.return_value = inp
        folds.add.return_value = created
        component = SimpleNamespace(features=SimpleNamespace(foldFeatures=folds))
        value_input = Mock()
        position_types = SimpleNamespace(CenterFoldBendLinePositionType=22)
        stationary, line = object(), object()
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_face", return_value=stationary), \
             patch.object(sheet, "_sketch_line", return_value=line), \
             patch.object(sheet.adsk.core, "ValueInput", value_input, create=True), \
             patch.object(sheet.adsk.fusion, "FoldBendLinePositionTypes",
                          position_types, create=True):
            value_input.createByString.return_value = "90 deg input"
            result = sheet.fold_create({"component": "c", "stationary_face": "f",
                                        "sketch": "s", "line": "l", "angle": "90 deg"})
        bend_lines.add.assert_called_once_with(line, "90 deg input", 22, True)
        folds.add.assert_called_once_with(inp)
        self.assertEqual(result["bend_lines"], 1)

    def test_unfold_requires_faces_when_not_unfolding_all(self):
        component = SimpleNamespace(features=SimpleNamespace(unfoldFeatures=Mock()))
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_face", return_value=object()), \
             self.assertRaisesRegex(ValueError, "Provide bend_faces"):
            sheet.unfold_create({"component": "c", "stationary_face": "f",
                                 "all_bends": False})

    def test_fold_edit_angle_uses_compare_and_set(self):
        parameter = SimpleNamespace(expression="90 deg")
        bend = SimpleNamespace(bendAngle=parameter)
        fold = feature("Fold1", "fold")
        fold.bendLines = Collection([bend])
        component = SimpleNamespace(features=SimpleNamespace(foldFeatures=Collection([fold])))
        design = SimpleNamespace(computeAll=Mock(return_value=True))
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_design", return_value=design):
            result = sheet.fold_edit_angle({"component": "c", "fold": "fold",
                                            "bend_index": 0,
                                            "expected_angle": "90 deg",
                                            "angle": "45 deg"})
        self.assertEqual(parameter.expression, "45 deg")
        self.assertEqual(result["before"], "90 deg")

    def test_unfold_edit_restores_timeline_marker(self):
        timeline = SimpleNamespace(markerPosition=7)
        unfold = feature("Unfold1", "unfold")
        unfold.isUnfoldAllBends = True
        unfold.bendFaces = Collection()
        unfold.timelineObject = Mock()
        unfold.timelineObject.rollTo.return_value = True
        unfold.setUnfoldBends = Mock(return_value=True)
        component = SimpleNamespace(features=SimpleNamespace(
            unfoldFeatures=Collection([unfold])))
        design = SimpleNamespace(timeline=timeline)
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_design", return_value=design):
            result = sheet.unfold_edit({"component": "c", "unfold": "unfold",
                                        "all_bends": True})
        unfold.setUnfoldBends.assert_called_once_with(True)
        self.assertEqual(timeline.markerPosition, 7)
        self.assertTrue(result["all_bends"])

    def test_refold_blocks_duplicate_refold(self):
        unfold = SimpleNamespace(refoldFeature=object())
        component = SimpleNamespace(features=SimpleNamespace())
        with patch.object(sheet, "_component", return_value=component), \
             patch.object(sheet, "_resolve_feature", return_value=unfold), \
             self.assertRaisesRegex(ValueError, "already has"):
            sheet.refold_create({"component": "c", "unfold": "u"})

    def test_flat_pattern_create_rejects_existing_pattern(self):
        component = SimpleNamespace(flatPattern=object())
        with patch.object(sheet, "_component", return_value=component), \
             self.assertRaisesRegex(ValueError, "already has"):
            sheet.flat_pattern_create({"component": "c", "stationary_face": "f"})

    def test_flat_pattern_delete_accepts_invalidated_handle_when_component_query_errors(self):
        flat = SimpleNamespace(name="Flat1", entityToken="flat", isValid=False)
        flat.deleteMe = Mock(return_value=True)

        class Component:
            calls = 0

            @property
            def flatPattern(self):
                self.calls += 1
                if self.calls == 1:
                    return flat
                raise RuntimeError("InternalValidationError : res")

        with patch.object(sheet, "_component", return_value=Component()):
            result = sheet.flat_pattern_delete({"component": "c"})
        self.assertEqual(result["deleted"]["token"], "flat")
        self.assertEqual(result["verified"], "feature_handle_invalid")

    def test_feature_delete_reports_domain_kind(self):
        target = feature("Unfold1", "unfold")
        target.deleteMe = Mock(return_value=True)
        component = SimpleNamespace(features=SimpleNamespace(
            flangeFeatures=Collection(), foldFeatures=Collection(),
            unfoldFeatures=Collection([target]), refoldFeatures=Collection()))
        with patch.object(sheet, "_component", return_value=component):
            result = sheet.feature_delete({"component": "c", "feature": "unfold"})
        target.deleteMe.assert_called_once_with()
        self.assertEqual(result["deleted"]["kind"], "unfold")

    def test_empty_component_name_does_not_mutate_fusion(self):
        occurrences = Mock()
        design = SimpleNamespace(rootComponent=SimpleNamespace(occurrences=occurrences))
        with patch.object(sheet, "_design", return_value=design), \
             self.assertRaisesRegex(ValueError, "must not be empty"):
            sheet.component_create({"name": "   "})
        occurrences.addNewSheetMetalComponent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
