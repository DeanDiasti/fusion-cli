"""Verify failure recovery against a deterministic native-transaction stand-in."""
import unittest
from unittest.mock import Mock, patch
import test_startup

test_startup.core.ApplicationCommandEventHandler = type('ApplicationCommandEventHandler', (), {})
test_startup.core.DocumentEventHandler = type('DocumentEventHandler', (), {})
from bridge.fusion_undo import FusionUndo, _timeline_signature, _timeline_signature_item
from bridge.checkpoint_undo import CheckpointUndo, UndoUnavailable


class RecoveryTests(unittest.TestCase):
    def test_checkpoint_resolves_design_from_document_in_animation(self):
        owner = FusionUndo.__new__(FusionUndo)
        owner.app = Mock()
        product = object()
        owner.app.activeDocument.products.itemByProductType.return_value = product
        with patch('bridge.fusion_undo.adsk.fusion.Design', Mock(cast=lambda item: item), create=True):
            self.assertIs(owner.design(), product)
        owner.app.activeDocument.products.itemByProductType.assert_called_once_with('DesignProductType')

    def test_begin_without_document_refuses_checkpoint(self):
        owner = FusionUndo.__new__(FusionUndo)
        owner.app = Mock(activeDocument=None)
        owner.ledger = None
        with self.assertRaisesRegex(UndoUnavailable, 'Open a Fusion design'):
            owner.begin('checkpoint')
        self.assertIsNone(owner.ledger)

    def test_timeline_signature_supports_group_without_entity(self):
        item = type('TimelineGroupRow', (), {
            'name': 'Group', 'entity': None,
            'objectType': 'adsk::fusion::TimelineGroup', 'isGroup': True,
        })()
        self.assertEqual(
            _timeline_signature_item(item),
            ('Group', 'adsk::fusion::TimelineGroup', True),
        )

    def test_timeline_signature_is_independent_of_group_display_state(self):
        child = type('TimelineRow', (), {
            'name': 'Extrude', 'entity': None, 'objectType': 'TimelineObject',
            'isGroup': False, 'parentGroup': object(),
        })()
        group = type('TimelineGroupRow', (), {
            'name': 'Group', 'entity': None, 'objectType': 'TimelineGroup',
            'isGroup': True, 'count': 1, 'item': lambda self, _i: child,
        })()
        groups = type('Groups', (), {
            'count': 1, 'item': lambda self, _i: group,
        })()
        expanded = type('Timeline', (), {
            'count': 1, 'item': lambda self, _i: child,
            'timelineGroups': groups,
        })()
        collapsed = type('Timeline', (), {
            'count': 1, 'item': lambda self, _i: group,
            'timelineGroups': groups,
        })()
        self.assertEqual(_timeline_signature(expanded),
                         _timeline_signature(collapsed))

    def controller(self, abort_fails=False, changed=False, commit_fails=False):
        owner = FusionUndo.__new__(FusionUndo)
        owner.owned = False
        owner.signatures = {'baseline': 'original'}
        owner.document_id = lambda: 'document'
        state = {'marker': 'baseline', 'signature': 'original'}
        owner.marker = lambda: state['marker']
        owner.signature = lambda: state['signature']
        attributes = Mock()
        attributes.add.side_effect = lambda group, name, token: state.update(marker=token)
        owner.design = lambda: Mock(attributes=attributes)
        def text(command):
            if command == 'PTransaction.Abort':
                if abort_fails: raise RuntimeError('abort failed')
                state.update(marker='baseline', signature='changed' if changed else 'original')
            if command == 'PTransaction.Commit' and commit_fails:
                raise RuntimeError('commit failed')
        owner.text = Mock(side_effect=text)
        owner.ledger = CheckpointUndo(owner)
        owner.ledger.begin('checkpoint')
        return owner

    def test_verified_abort_preserves_checkpoint_and_allows_retry(self):
        owner = self.controller()
        with self.assertRaisesRegex(ValueError, 'invalid dimension'):
            owner.execute(Mock(side_effect=ValueError('invalid dimension')), {})
        self.assertIsNone(owner.ledger.reason)
        self.assertEqual(owner.execute(lambda args: {'ok': True}, {}), {'ok': True})
        owner.finish()
        self.assertEqual(owner.status()['available'], ['checkpoint'])
        self.assertEqual(len(owner.ledger.checkpoints[0].transactions), 1)

    def test_unverified_abort_blocks_further_edits(self):
        for kwargs in ({'abort_fails': True}, {'changed': True}):
            with self.subTest(kwargs=kwargs):
                owner = self.controller(**kwargs)
                with self.assertRaises(ValueError):
                    owner.execute(Mock(side_effect=ValueError('failed')), {})
                self.assertTrue(owner.ledger.reason)
                edit = Mock()
                with self.assertRaises(UndoUnavailable): owner.execute(edit, {})
                edit.assert_not_called()

    def test_commit_failure_never_treated_as_recovered_tool_error(self):
        owner = self.controller(commit_fails=True)
        with self.assertRaisesRegex(RuntimeError, 'commit failed'):
            owner.execute(lambda args: {}, {})
        self.assertTrue(owner.ledger.reason)

    def test_preview_aborts_on_success_without_checkpoint_entry(self):
        owner=self.controller()
        result=owner.preview(lambda a:{'samples':[1]}, {}, lambda:{'angle':4.1802617})
        self.assertTrue(result['restoration']['verified'])
        self.assertEqual(owner.ledger.active.transactions,[])
        self.assertIsNone(owner.ledger.reason)
        self.assertEqual([c.args[0] for c in owner.text.call_args_list],['PTransaction.Start CadBotPreview','PTransaction.Abort'])

    def test_preview_error_reports_verified_recovery(self):
        owner=self.controller()
        with self.assertRaisesRegex(RuntimeError,'capture failed; temporary transaction rolled back'):
            owner.preview(Mock(side_effect=ValueError('capture failed')), {}, lambda:{})
        self.assertIsNone(owner.ledger.reason)

    def test_preview_rollback_failure_invalidates_chain(self):
        for options in ({'abort_fails':True},{'changed':True}):
            owner=self.controller(**options)
            with self.assertRaises(UndoUnavailable):owner.preview(lambda a:{}, {}, lambda:{})
            self.assertTrue(owner.ledger.reason)
            self.assertEqual(sum(c.args[0]=='PTransaction.Abort' for c in owner.text.call_args_list),1)

    def test_preview_joint_drift_rejected_even_if_signature_matches(self):
        owner=self.controller();observe=Mock(side_effect=[{'angle':4.1802617},{'angle':4.2}])
        with self.assertRaises(UndoUnavailable):owner.preview(lambda a:{}, {}, observe)
        self.assertTrue(owner.ledger.reason)
