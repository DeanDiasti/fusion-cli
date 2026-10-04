import unittest
import test_startup
from bridge.coverage import reconcile


class CoverageTests(unittest.TestCase):
    specs = {'design inspect': ('get_state', False, {}, {}), 'design reset': ('reset_design', True, {}, {})}
    effects = {'design inspect': 'inspection', 'design reset': 'design_mutation'}

    def report(self, cases, build='current'):
        return {'build': build, 'release_ready': True, 'commands': [
            {'command': 'fusion ' + name, 'cases': cases} for name in self.specs]}

    def test_historical_pass_never_certifies_current_build(self):
        result = reconcile(self.report([{'passed': True}], 'old'), self.specs, self.effects, 'current')
        self.assertFalse(result['release_ready'])
        self.assertEqual(result['section_summary']['design']['not_live_verified'], 2)
        self.assertEqual(result['commands'][0]['cases'][0]['build'], 'old')
        # A second reconciliation must not re-label historical cases as current.
        again = reconcile(result, self.specs, self.effects, 'current')
        self.assertFalse(again['release_ready'])

    def test_current_failure_wins_over_current_pass(self):
        result = reconcile(self.report([{'passed': True}, {'passed': False}]), self.specs, self.effects, 'current')
        self.assertFalse(result['release_ready'])
        self.assertEqual(result['section_summary']['design']['live_failure'], 2)

    def test_current_passing_cases_release_and_new_commands_block(self):
        result = reconcile(self.report([{'passed': True}]), self.specs, self.effects, 'current')
        self.assertTrue(result['release_ready'])
        result = reconcile(result, {**self.specs, 'design new': ()}, {**self.effects, 'design new': 'inspection'}, 'current')
        self.assertFalse(result['release_ready'])
        self.assertEqual(result['command_count'], 3)

    def test_matched_capability_refusal_is_explicit(self):
        result = reconcile(self.report([{'passed': True, 'capability_blocked': True}]), self.specs, self.effects, 'current')
        self.assertTrue(result['release_ready'])
        self.assertEqual(result['section_summary']['design']['live_capability_blocked'], 2)
        self.assertEqual(result['section_summary']['design']['live_case_passed'], 0)
