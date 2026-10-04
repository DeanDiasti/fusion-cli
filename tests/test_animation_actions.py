import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from bridge.commands import prepare, EFFECTS
from tools import animation_actions as actions


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(document_id='doc', storyboard='storyboard:test', component='leg:1',
                         axis='x', degrees=10, pivot_mm=[0, 0, 0], start=0, end=1)

    def test_cli_requires_explicit_target_and_pivot(self):
        command = ('fusion animation actions rotate --document-id doc --storyboard storyboard:test '
                   '--component leg:1 --axis x --degrees 10 --pivot-mm "[0,0,0]" '
                   '--start 0 --end 1 --dry-run')
        handler, args, mutation = prepare({'command': command})
        self.assertEqual(handler, 'animation_actions_rotate')
        self.assertTrue(args['dry_run'])
        self.assertFalse(mutation)
        self.assertEqual(EFFECTS['animation actions rotate'], 'inspection')
        with self.assertRaises(ValueError):
            prepare({'command': command.replace('--document-id doc ', '')})

    def test_rejects_invalid_rotation_before_native_access(self):
        for change in [dict(start=1, end=1), dict(start=-1), dict(end=float('inf')),
                       dict(degrees=0), dict(degrees=181), dict(axis='foo'),
                       dict(pivot_mm=[0, 0]), dict(pivot_mm=[0, True, 0]),
                       dict(pivot_mm=[0, float('nan'), 0])]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                actions.rotation_request({**self.args, **change})

    def test_planning_and_blocked_write_do_not_change_scene(self):
        app = SimpleNamespace(activeDocument=SimpleNamespace(creationId='doc', name='Fixture'),
                              version='test', executeTextCommand=Mock())
        board = SimpleNamespace(isActive=True, isInPlayMode=False, end=0, playheadPosition=0)
        occurrence = SimpleNamespace(fullPathName='leg:1')
        with patch.object(actions.adsk.core.Application, 'get', return_value=app), \
             patch.object(actions.animation, 'board', return_value=board), \
             patch.object(actions.animation_entities, 'resolve_occurrence', return_value=occurrence), \
             patch.object(actions.animation_entities, 'selector_for', return_value='occurrence:test'):
            planned = actions.rotate({**self.args, 'dry_run': True})
            self.assertEqual(planned['status'], 'planned')
            self.assertFalse(planned['animation_created'])
            blocked = actions.rotate(self.args)
            self.assertEqual(blocked['status'], 'blocked')
            self.assertEqual(blocked['error']['code'], 'native_animation_backend_unverified')
            self.assertEqual(blocked['changes'], [])
            app.executeTextCommand.assert_not_called()
            self.assertEqual(board.playheadPosition, 0)
            app.activeDocument.creationId = 'different'
            with self.assertRaisesRegex(ValueError, 'Active document changed'):
                actions.rotate(self.args)


if __name__ == '__main__':
    unittest.main()
