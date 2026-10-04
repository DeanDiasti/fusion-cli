import unittest
from unittest.mock import Mock, patch

import test_startup
from tools import design_management as management
from bridge.commands import prepare


class DesignManagementTests(unittest.TestCase):
    def test_management_commands_parse(self):
        self.assertEqual(prepare({"command": "fusion design features inspect --feature f1"})[0],
                         "feature_inspect")
        self.assertEqual(prepare({"command": "fusion design bodies rename --body b1 --name Main"})[0],
                         "body_rename")
        self.assertEqual(prepare({"command": "fusion design parameters create --name width --expression '25 mm'"})[0],
                         "parameter_create")

    def test_feature_name_must_be_unambiguous(self):
        a = Mock(name="a"); a.name = "Cut"; a.objectType = "adsk::fusion::ExtrudeFeature"
        b = Mock(name="b"); b.name = "Cut"; b.objectType = "adsk::fusion::ExtrudeFeature"
        design = Mock()
        design.findEntityByToken.side_effect = RuntimeError()
        with patch.object(management, "_design", return_value=design), \
             patch.object(management, "_feature_entries", return_value=[(0, a), (1, b)]), \
             self.assertRaisesRegex(ValueError, "exactly one"):
            management._resolve_feature("Cut")

    def test_feature_suppression_is_verified(self):
        feature = Mock()
        feature.entityToken = "f1"
        feature.isSuppressed = False
        with patch.object(management, "_resolve_feature", return_value=feature):
            result = management.feature_suppress({"feature": "f1"})
        self.assertEqual(result, {"feature": "f1", "suppressed": True})

    def test_body_rename_rejects_empty_name(self):
        body = Mock(); body.name = "Body"; body.entityToken = "b1"
        with patch.object(management, "_resolve_body", return_value=(Mock(), body)), \
             self.assertRaisesRegex(ValueError, "empty"):
            management.body_rename({"body": "b1", "name": "  "})

    def test_parameter_delete_only_uses_user_parameters(self):
        design = Mock()
        design.userParameters.itemByName.return_value = None
        with patch.object(management, "_design", return_value=design), \
             self.assertRaisesRegex(ValueError, "User parameter"):
            management.parameter_delete({"name": "d1"})


if __name__ == "__main__":
    unittest.main()
