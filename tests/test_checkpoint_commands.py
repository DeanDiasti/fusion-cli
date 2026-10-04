"""Contracts for explicit CLI undo controls and document safety."""
import unittest
from unittest.mock import Mock, patch
import test_startup
from bridge.commands import prepare
from bridge import server
from bridge.checkpoint_undo import UndoUnavailable
import test_fusion_undo_recovery as recovery


class CheckpointCommandTests(unittest.TestCase):
    def setUp(self):
        self.app = test_startup.core.Application.get.return_value
        self.app.userInterface.activeWorkspace.id = 'FusionSolidEnvironment'
        self.app.activeDocument.creationId = 'intended-design'

    def test_controls_dispatch_without_creating_edit_transaction(self):
        owner = Mock()
        for action in ('begin', 'finish', 'status', 'restore'):
            command = 'fusion checkpoint ' + action
            if action in ('begin', 'restore'):
                command += ' --id bracket --document-id intended-design'
            with self.subTest(action=action), patch.object(server, '_undo', owner):
                result = server._execute_tool('fusion', None, {'command': command})
                method = getattr(owner, action)
                self.assertIs(result, method.return_value)
                method.assert_called_once_with(*(['bracket'] if action in ('begin', 'restore') else []))
        owner.execute.assert_not_called()

    def test_wrong_document_refuses_begin_and_restore(self):
        owner = Mock()
        for action in ('begin', 'restore'):
            with self.subTest(action=action), patch.object(server, '_undo', owner):
                with self.assertRaisesRegex(ValueError, 'Active document changed'):
                    server._execute_tool('fusion', None, {'command':
                        'fusion checkpoint ' + action + ' --id bracket --document-id wrong'})
                getattr(owner, action).assert_not_called()

    def test_animation_workspace_refuses_begin_and_restore(self):
        self.app.userInterface.activeWorkspace.id = 'AnimationEnvironment'
        owner = Mock()
        for action in ('begin', 'restore'):
            with self.subTest(action=action), patch.object(server, '_undo', owner):
                with self.assertRaisesRegex(ValueError, 'Design workspace'):
                    server._execute_tool('fusion', None, {'command':
                        'fusion checkpoint ' + action + ' --id bracket'})
                getattr(owner, action).assert_not_called()

    def test_invalid_ids_refused_by_cli_and_private_transport(self):
        import shlex
        owner = Mock()
        for value in ('', ' surrounding ', 'x\nnext', 'x' * 129):
            with self.subTest(value=value), patch.object(server, '_undo', owner):
                with self.assertRaises(ValueError):
                    prepare({'command': 'fusion checkpoint begin --id ' + shlex.quote(value)})
                with self.assertRaises(ValueError):
                    server._checkpoint({'action': 'begin', 'id': value})
        owner.begin.assert_not_called()

    def test_private_transport_rejects_extra_or_missing_fields(self):
        for args in ({'action': 'begin'}, {'action': 'finish', 'id': 'x'},
                     {'action': 'restore', 'id': 'x', 'unexpected': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                server._checkpoint(args)

    def test_invalid_checkpoint_cannot_finish_successfully(self):
        owner = recovery.RecoveryTests().controller()
        owner.invalidate('Outside edit')
        with self.assertRaisesRegex(UndoUnavailable, 'Outside edit'):
            owner.finish()
        self.assertIsNone(owner.ledger.active)
        self.assertEqual(owner.status()['available'], [])

    def test_finished_checkpoint_cannot_accept_untracked_edit(self):
        owner = recovery.RecoveryTests().controller()
        owner.finish()
        edit = Mock()
        with self.assertRaisesRegex(UndoUnavailable, 'Begin a CLI checkpoint'):
            owner.execute(edit, {})
        edit.assert_not_called()

    def test_status_exposes_active_checkpoint_id(self):
        owner = recovery.RecoveryTests().controller()
        self.assertEqual(owner.status()['active_id'], 'checkpoint')
        self.assertEqual(owner.status()['available'], [])
        owner.finish()
        self.assertIsNone(owner.status()['active_id'])
        self.assertEqual(owner.status()['available'], ['checkpoint'])
