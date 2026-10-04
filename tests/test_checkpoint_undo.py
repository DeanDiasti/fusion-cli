import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fusion_addin/CadBot'))
from bridge.checkpoint_undo import CheckpointUndo, UndoUnavailable


class FakeHost:
    def __init__(self):
        self.document = 'design-A'
        self.stack = ['manual-baseline']
        self.undone = []
    def document_id(self): return self.document
    def head(self): return self.stack[-1]
    def undo(self, expected_head):
        assert self.head() == expected_head
        self.undone.append(self.stack.pop())


class CheckpointUndoTests(unittest.TestCase):
    def setUp(self):
        self.host = FakeHost()
        self.ledger = CheckpointUndo(self.host)
    def checkpoint(self, name, count=1):
        self.ledger.begin(name)
        for i in range(count):
            before = self.host.head()
            self.host.stack.append(name + ':' + str(i))
            self.ledger.committed(before, self.host.head())
        self.ledger.finish()
    def test_multiple_checkpoints_and_multiple_transactions(self):
        self.checkpoint('arm', 2)
        self.checkpoint('shorten', 1)
        self.checkpoint('inspect', 0)
        self.checkpoint('bearings', 3)
        result = self.ledger.restore_before('shorten')
        self.assertEqual(self.host.head(), 'arm:1')
        self.assertEqual(result['checkpoints_undone'], ['shorten', 'inspect', 'bearings'])
        self.assertEqual(len(self.host.undone), 4)
        self.ledger.restore_before('arm')
        self.assertEqual(self.host.stack, ['manual-baseline'])
    def test_manual_edit_blocks_all_undo(self):
        self.checkpoint('arm')
        self.host.stack.append('manual-edit')
        with self.assertRaises(UndoUnavailable): self.ledger.restore_before('arm')
        self.assertEqual(self.host.undone, [])
    def test_document_switch_blocks_undo(self):
        self.checkpoint('arm')
        self.host.document = 'design-B'
        with self.assertRaises(UndoUnavailable): self.ledger.restore_before('arm')
        self.assertEqual(self.host.undone, [])
    def test_running_checkpoint_blocks_undo(self):
        self.ledger.begin('arm')
        with self.assertRaises(UndoUnavailable): self.ledger.restore_before('arm')
    def test_unexpected_undo_result_stops_without_further_undo(self):
        self.checkpoint('arm', 3)
        def wrong_undo(expected_head): self.host.stack[:] = ['unexpected']
        self.host.undo = wrong_undo
        with self.assertRaises(UndoUnavailable): self.ledger.restore_before('arm')
        self.assertIsNotNone(self.ledger.reason)
    def test_new_session_does_not_reuse_boundaries(self):
        self.checkpoint('arm')
        fresh = CheckpointUndo(self.host)
        with self.assertRaises(UndoUnavailable): fresh.restore_before('arm')
    def test_branch_after_restoring(self):
        self.checkpoint('arm')
        self.checkpoint('bearings')
        self.ledger.restore_before('bearings')
        self.checkpoint('alternative')
        self.assertEqual([m.id for m in self.ledger.checkpoints], ['arm', 'alternative'])

if __name__ == '__main__': unittest.main()
