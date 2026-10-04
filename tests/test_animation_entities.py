import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_startup
from tools import animation_entities


class Matrix:
    def __init__(self, x=1, y=2, z=3):
        self.translation = SimpleNamespace(x=x, y=y, z=z)

    def asArray(self):
        return [1, 0, 0, self.translation.x,
                0, 1, 0, self.translation.y,
                0, 0, 1, self.translation.z,
                0, 0, 0, 1]


def occurrence(path, component="Leg", visible=True, token=None):
    return SimpleNamespace(
        fullPathName=path,
        name=path.rsplit("+", 1)[-1],
        component=SimpleNamespace(name=component),
        isLightBulbOn=visible,
        isVisible=visible,
        isValid=True,
        entityToken=token,
        transform2=Matrix(),
    )


class AnimationEntityTests(unittest.TestCase):
    def setUp(self):
        animation_entities._selectors.clear()
        self.front = occurrence("Robot:1+Front Leg:1", token="front-token")
        self.rear = occurrence("Robot:1+Rear Leg:1", token="rear-token")
        self.design = SimpleNamespace(
            rootComponent=SimpleNamespace(allOccurrences=[self.front, self.rear])
        )
        self.design.findEntityByToken = lambda token: [
            item for item in self.design.rootComponent.allOccurrences
            if item.entityToken == token
        ]
        self.document = SimpleNamespace(creationId="document-a", name="Robot")
        self.context = patch.object(
            animation_entities, "_context", return_value=(self.document, self.design)
        )
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_listing_exposes_instance_state_and_stable_selectors(self):
        first = animation_entities.list_occurrences({})
        second = animation_entities.list_occurrences({})
        self.assertEqual(
            [item["selector"] for item in first["occurrences"]],
            [item["selector"] for item in second["occurrences"]],
        )
        item = first["occurrences"][0]
        self.assertEqual(item["path"], "Robot:1+Front Leg:1")
        self.assertEqual(item["name"], "Front Leg:1")
        self.assertEqual(item["component"], "Leg")
        self.assertEqual(item["visibility"], {"light_bulb": True, "effective": True})
        self.assertEqual(item["transform"]["translation_mm"], {"x": 10.0, "y": 20.0, "z": 30.0})
        self.assertEqual(len(item["transform"]["matrix"]), 16)
        self.assertEqual(item["transform"]["space"], "assembly_context")

    def test_repeated_component_name_is_ambiguous_but_path_is_exact(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            animation_entities.resolve_occurrence("Leg")
        self.assertIs(
            animation_entities.resolve_occurrence("Robot:1+Rear Leg:1"), self.rear
        )

    def test_selector_is_bound_to_document(self):
        selector = animation_entities.selector_for(self.front)
        self.assertIs(animation_entities.resolve_occurrence(selector), self.front)
        self.document.creationId = "document-b"
        with self.assertRaisesRegex(ValueError, "another Fusion session or document"):
            animation_entities.resolve_occurrence(selector)

    def test_selector_survives_a_new_api_wrapper_for_the_same_entity(self):
        selector = animation_entities.selector_for(self.front)
        replacement_wrapper = occurrence(self.front.fullPathName, token="front-token")
        self.design.rootComponent.allOccurrences[0] = replacement_wrapper
        self.assertIs(
            animation_entities.resolve_occurrence(selector), replacement_wrapper
        )
        self.assertEqual(
            animation_entities.selector_for(replacement_wrapper), selector
        )

    def test_deleted_occurrence_makes_selector_stale(self):
        selector = animation_entities.selector_for(self.front)
        self.design.rootComponent.allOccurrences.remove(self.front)
        with self.assertRaisesRegex(ValueError, "deleted"):
            animation_entities.resolve_occurrence(selector)

    def test_reused_path_does_not_rebind_selector(self):
        selector = animation_entities.selector_for(self.front)
        replacement = occurrence(self.front.fullPathName, token="replacement-token")
        self.design.rootComponent.allOccurrences[0] = replacement
        with self.assertRaisesRegex(ValueError, "stale"):
            animation_entities.resolve_occurrence(selector)

    def test_invalid_entity_and_expected_document_are_rejected(self):
        self.front.isValid = False
        with self.assertRaisesRegex(ValueError, "invalid"):
            animation_entities.selector_for(self.front)
        with self.assertRaisesRegex(ValueError, "Active document changed"):
            animation_entities.list_occurrences({"document_id": "wrong"})

    def test_filter_and_hidden_control(self):
        self.rear.isLightBulbOn = False
        self.rear.isVisible = False
        result = animation_entities.list_occurrences(
            {"query": "rear", "visible_only": True}
        )
        self.assertEqual(result["occurrences"], [])

    def test_inspect_component_returns_exact_occurrence(self):
        selector = animation_entities.selector_for(self.front)
        result = animation_entities.inspect_component({"component": selector})
        self.assertEqual(result["document"], {"id": "document-a", "name": "Robot"})
        self.assertEqual(result["occurrence"]["path"], "Robot:1+Front Leg:1")


if __name__ == "__main__":
    unittest.main()
