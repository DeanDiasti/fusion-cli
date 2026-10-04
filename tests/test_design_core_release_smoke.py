"""Host-side contract checks for the native core Design live gate."""

import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "tests" / "fusion_design_core_release_smoke.py"
EXCLUDED = ("sheet-metal", "configurations", "materials", " forms ", " surfaces ")


def literal_targets(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "TARGETS"
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("TARGETS literal is missing")


class CoreDesignReleaseSmokeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATE.read_text()
        cls.targets = literal_targets(cls.source)
        spec = importlib.util.spec_from_file_location(
            "core_release_commands",
            ROOT / "fusion_addin" / "CadBot" / "bridge" / "commands.py")
        cls.commands = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.commands)

    def test_gate_covers_exact_current_core_gap(self):
        self.assertEqual(len(self.targets), 64)
        self.assertTrue(self.targets.issubset(self.commands.SPECS))
        self.assertTrue(all(name.startswith("design ") for name in self.targets))
        self.assertFalse(any(any(value in name for value in EXCLUDED)
                             for name in self.targets))

    def test_every_case_uses_cli_grammar_and_registered_handler(self):
        self.assertIn('commands.prepare({"command": command})', self.source)
        self.assertIn("registry._TOOL_MAP[handler_name]", self.source)
        self.assertIn('"handler": None', self.source)

    def test_fixture_and_restoration_are_explicit(self):
        self.assertIn("FusionDesignDocumentType", self.source)
        self.assertIn("fixture.close(False)", self.source)
        self.assertIn("original_document.activate()", self.source)
        self.assertIn("original_workspace.activate()", self.source)
        self.assertIn("ui.activeSelections.clear()", self.source)
        self.assertIn('"original_model_touched": False', self.source)

    def test_report_records_expected_actual_and_cleanup(self):
        self.assertIn('"expected": evidence_value(expected)', self.source)
        self.assertIn('row["actual"] = actual', self.source)
        self.assertIn('report["fixture_closed"]', self.source)
        self.assertIn('report["original_document_restored"]', self.source)


if __name__ == "__main__":
    unittest.main()
