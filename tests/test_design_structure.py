import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from tools import design_structure as structure


class Collection:
    def __init__(self, values=()):
        self.values = list(values)

    @property
    def count(self):
        return len(self.values)

    def item(self, index):
        return self.values[index]


class HiddenTimelineItem:
    name = "Extrude"
    isGroup = False
    isSuppressed = False
    isRolledBack = False
    healthState = "healthy"
    errorOrWarningMessage = ""
    entity = None

    @property
    def index(self):
        raise RuntimeError("global index hidden while grouped")


def construction(kind="Plane", name="Offset Plane", token="plane-token"):
    parameter = SimpleNamespace(expression="10 mm", unit="mm", value=1.0)
    definition = SimpleNamespace(objectType="OffsetDefinition", offset=parameter)
    geometry = SimpleNamespace(
        origin=SimpleNamespace(x=0, y=0, z=1),
        normal=SimpleNamespace(x=0, y=0, z=1),
    )
    component = SimpleNamespace(name="Root", entityToken="root-token")
    return SimpleNamespace(
        name=name, entityToken=token, objectType="adsk::fusion::Construction{}".format(kind),
        component=component, isValid=True, isParametric=True, isDeletable=True,
        isVisible=True, isLightBulbOn=True, healthState="healthy",
        errorOrWarningMessage="", geometry=geometry, definition=definition,
    )


class DesignStructureTests(unittest.TestCase):
    def test_origin_alias_resolves_without_name_guessing(self):
        origin = object()
        design = SimpleNamespace(rootComponent=SimpleNamespace(xYConstructionPlane=origin))
        with patch.object(structure, "_design", return_value=design):
            self.assertIs(structure._resolve_token("origin:xy-plane"), origin)

    def test_origin_alias_can_be_inspected_as_construction(self):
        origin = construction(name="XY", token="origin-token")
        root = SimpleNamespace(name="Root", entityToken="root", xYConstructionPlane=origin)
        design = SimpleNamespace(rootComponent=root)
        with patch.object(structure, "_design", return_value=design):
            kind, component, entity = structure._resolve_construction("origin:xy-plane", "plane")
        self.assertEqual(kind, "plane")
        self.assertIs(component, root)
        self.assertIs(entity, origin)

    def test_construction_name_must_be_unambiguous(self):
        first = construction(name="Plane", token="p1")
        second = construction(name="Plane", token="p2")
        component = SimpleNamespace(name="Root")
        with patch.object(structure, "_construction_entries",
                          return_value=[("plane", component, first),
                                        ("plane", component, second)]), \
                self.assertRaisesRegex(ValueError, "exactly one"):
            structure._resolve_construction("Plane")

    def test_offset_plane_uses_typed_value_and_verifies_result(self):
        entity = construction()
        construction_input = Mock()
        construction_input.setByOffset.return_value = True
        planes = Mock()
        planes.createInput.return_value = construction_input
        planes.add.return_value = entity
        component = SimpleNamespace(constructionPlanes=planes)
        reference = object()
        value_input = Mock()
        with patch.object(structure, "_component", return_value=component), \
                patch.object(structure, "_resolve_token", return_value=reference), \
                patch.object(structure.adsk.core, "ValueInput", value_input, create=True):
            value_input.createByString.return_value = "value-input"
            result = structure.plane_create_offset({
                "reference": "origin:xy-plane", "offset": "10 mm", "name": "Deck"
            })
        construction_input.setByOffset.assert_called_once_with(reference, "value-input")
        self.assertEqual(entity.name, "Deck")
        self.assertEqual(result["token"], "plane-token")

    def test_edit_only_allows_known_definition_parameters(self):
        entity = construction()
        component = entity.component
        with patch.object(structure, "_resolve_construction",
                          return_value=("plane", component, entity)):
            result = structure.construction_set_parameter({
                "construction": "plane-token", "parameter": "offset",
                "expression": "25 mm"
            })
            self.assertEqual(result["definition"]["offset"]["expression"], "25 mm")
            with self.assertRaisesRegex(ValueError, "offset, angle, or distance"):
                structure.construction_set_parameter({
                    "construction": "plane-token", "parameter": "script",
                    "expression": "anything"
                })

    def test_timeline_roll_validates_and_verifies_marker(self):
        timeline = SimpleNamespace(markerPosition=3, count=6)
        design = SimpleNamespace(timeline=timeline)
        with patch.object(structure, "_design", return_value=design):
            result = structure.timeline_roll({"position": 2})
            self.assertEqual(result["marker_position"], 2)
            with self.assertRaisesRegex(ValueError, "between 0"):
                structure.timeline_roll({"position": 7})

    def test_group_delete_keep_cannot_delete_contents(self):
        group = Mock()
        group.name = "Setup"
        group.count = 3
        group.isCollapsed = False
        group.deleteMe.return_value = True
        with patch.object(structure, "_timeline_group", return_value=group):
            result = structure.timeline_group_delete_keep({"group": 0})
        group.deleteMe.assert_called_once_with(False)
        self.assertTrue(group.isCollapsed)
        self.assertTrue(result["contents_kept"])

    def test_group_info_tolerates_hidden_child_global_index(self):
        child = HiddenTimelineItem()
        group = SimpleNamespace(name="Smoke", count=1, isCollapsed=True,
                                item=lambda _index: child)
        result = structure._group_info(0, group)
        self.assertIsNone(result["items"][0]["index"])
        self.assertEqual(result["items"][0]["group_index"], 0)

    def test_selection_add_requires_resolved_entity_and_verifies_add(self):
        entity = SimpleNamespace(entityToken="body-token", objectType="BRepBody")
        selections = Mock()
        selections.add.return_value = True
        selections.count = 1
        app = SimpleNamespace(userInterface=SimpleNamespace(activeSelections=selections))
        with patch.object(structure, "_resolve_token", return_value=entity), \
                patch.object(structure.adsk.core.Application, "get", return_value=app):
            result = structure.selection_add({"entity": "body-token"})
        selections.add.assert_called_once_with(entity)
        self.assertEqual(result["selection_count"], 1)


if __name__ == "__main__":
    unittest.main()
