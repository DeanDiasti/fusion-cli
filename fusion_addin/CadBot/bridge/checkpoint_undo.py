"""Session-only checkpoint undo ledger. No unchecked native Undo operations.

The host adapter must provide verified, committed transaction tokens. A tool
call count is NOT a transaction token. This module intentionally cannot invoke
Fusion's Undo command without an adapter that checks the stack's current head.
"""
from dataclasses import dataclass, field
from typing import Protocol


class UndoUnavailable(RuntimeError):
    pass


class UndoAdapter(Protocol):
    def document_id(self) -> str: ...
    def head(self) -> str: ...
    def undo(self, expected_head: str) -> None: ...


@dataclass
class CheckpointBoundary:
    id: str
    before: str
    after: str
    # Pairs describe actual committed undo steps in chronological order.
    transactions: list[tuple[str, str]] = field(default_factory=list)
    complete: bool = False


class CheckpointUndo:
    def __init__(self, adapter: UndoAdapter):
        self.adapter = adapter
        self.document = adapter.document_id()
        self.checkpoints: list[CheckpointBoundary] = []
        self.active = None
        self.reason = None
        self.restoring = False

    def invalidate(self, reason):
        self.reason = reason

    def _check(self):
        if self.reason:
            raise UndoUnavailable(self.reason)
        if self.adapter.document_id() != self.document:
            self.invalidate('The active document changed.')
            raise UndoUnavailable(self.reason)

    def begin(self, checkpoint_id):
        self._check()
        if self.active or self.restoring:
            raise UndoUnavailable('An operation is already running.')
        if any(m.id == checkpoint_id for m in self.checkpoints):
            raise ValueError('Duplicate checkpoint ID')
        head = self.adapter.head()
        if self.checkpoints and head != self.checkpoints[-1].after:
            self.invalidate('The undo history changed outside CadBot.')
            raise UndoUnavailable(self.reason)
        self.active = CheckpointBoundary(checkpoint_id, head, head)
        self.checkpoints.append(self.active)

    def committed(self, before, after):
        self._check()
        if not self.active:
            raise UndoUnavailable('No active checkpoint.')
        if before != self.active.after or self.adapter.head() != after:
            self.invalidate('The committed transaction boundary could not be verified.')
            raise UndoUnavailable(self.reason)
        if before != after:
            self.active.transactions.append((before, after))
        self.active.after = after

    def finish(self):
        self._check()
        if not self.active:
            raise UndoUnavailable('No active checkpoint.')
        if self.adapter.head() != self.active.after:
            self.invalidate('The undo history changed outside CadBot.')
            raise UndoUnavailable(self.reason)
        self.active.complete = True
        self.active = None

    def plan(self, checkpoint_id):
        self._check()
        if self.active or self.restoring:
            raise UndoUnavailable('Finish or stop the current request first.')
        index = next((i for i, m in enumerate(self.checkpoints) if m.id == checkpoint_id), None)
        if index is None:
            raise UndoUnavailable('Checkpoint is not available in this session.')
        if self.adapter.head() != self.checkpoints[-1].after:
            self.invalidate('The undo history changed outside CadBot.')
            raise UndoUnavailable(self.reason)
        steps = [step for m in self.checkpoints[index:] for step in m.transactions]
        return index, list(reversed(steps))

    def restore_before(self, checkpoint_id):
        index, steps = self.plan(checkpoint_id)
        self.restoring = True
        undone = 0
        try:
            for before, after in steps:
                self._check()
                if self.adapter.head() != after:
                    raise UndoUnavailable('Undo head changed during restoration.')
                self.adapter.undo(expected_head=after)
                undone += 1
                if self.adapter.head() != before:
                    raise UndoUnavailable('Fusion did not reach the expected undo boundary.')
            if self.adapter.head() != self.checkpoints[index].before:
                raise UndoUnavailable('The target checkpoint boundary was not reached.')
            restored = [m.id for m in self.checkpoints[index:]]
            self.checkpoints = self.checkpoints[:index]
            return {'restored_before': checkpoint_id, 'checkpoints_undone': restored,
                    'transactions_undone': undone}
        except Exception as exc:
            self.invalidate('Restore interrupted after {} undo steps: {}'.format(undone, exc))
            raise UndoUnavailable(self.reason) from exc
        finally:
            self.restoring = False
