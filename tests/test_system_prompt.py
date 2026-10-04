"""Keep the Fusion agent's operating contract aligned with the structured CLI."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))

from system_prompt import SYSTEM_PROMPT
import cad_mcp


class SystemPromptTests(unittest.TestCase):
    def flat(self):
        return ' '.join(SYSTEM_PROMPT.split())

    def test_teaches_discovery_and_namespaces(self):
        for phrase in (
            'fusion app inspect',
            'fusion app capabilities',
            'fusion help <namespace>',
            'fusion design ...',
            'fusion animation ...',
            'fusion design motion check',
            '--document-id',
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, SYSTEM_PROMPT)

    def test_teaches_inspect_mutate_verify_loop(self):
        positions = [SYSTEM_PROMPT.index(text) for text in (
            '1. Inspect', '2. Read help', '3. Make', '4. Verify', '5. Report')]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('An API call returning successfully is not enough', SYSTEM_PROMPT)

    def test_distinguishes_native_animation_from_design_motion(self):
        self.assertIn('The HTML joint preview under `fusion design motion` is not native Animation', SYSTEM_PROMPT)
        self.assertIn('Never substitute it', self.flat())
        self.assertIn('persistent storyboards', SYSTEM_PROMPT)
        self.assertIn('fusion animation authoring', SYSTEM_PROMPT)
        self.assertIn('scene changes', SYSTEM_PROMPT)

    def test_teaches_cloud_and_recovery_boundaries(self):
        for phrase in ('cloud_complete=false', 'status=pending', 'Never discard unsaved work',
                       'Never issue Undo', 'first save can change the document ID'):
            self.assertIn(phrase, self.flat())

    def test_does_not_advertise_arbitrary_execution(self):
        self.assertIn('It is not a shell or Python sandbox', SYSTEM_PROMPT)
        self.assertNotIn('fusion_execute', SYSTEM_PROMPT)
        self.assertNotIn('fusion_api_help', SYSTEM_PROMPT)

    def test_mcp_description_uses_canonical_commands(self):
        description = cad_mcp.tool_specs()[0]['description']
        self.assertIn('fusion app inspect', description)
        self.assertIn('fusion design ...', description)
        self.assertIn('fusion animation ...', description)
        self.assertNotIn('fusion bodies combine', description)


if __name__ == '__main__':
    unittest.main()
