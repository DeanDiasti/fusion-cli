# CLI Design checkpoints

Begin a named checkpoint before Design mutations or temporary motion previews:

```bash
fusion checkpoint begin --id bracket
# Run Design edit commands.
fusion checkpoint finish
fusion checkpoint status
fusion checkpoint restore --id bracket
```

`finish` commits the boundary without undoing geometry. `restore` returns the design
to BEFORE the named checkpoint, undoing it and all later recorded checkpoints.
Finish the active checkpoint first. IDs are unique in the verified chain, use
1–128 printable characters and cannot have surrounding whitespace.

`begin` and `restore` accept `--document-id`, the session ID from `app inspect` or
`documents list`. A mismatch is refused before any change. These operations require
a Design workspace. `status` reports the active ID, available completed IDs and
the reason restoration is unavailable.

The checkpoint ledger is session-only. External Fusion commands conservatively
invalidate it, including some commands that do not modify geometry. Outside API
edits, document changes, bridge restarts and native transaction failures can also
invalidate it. Begin a new checkpoint to establish a fresh chain after invalidation.
The CLI never reconstructs past undo boundaries, restores cloud versions or archives,
selectively undoes a middle edit, or provides redo.

Each Design mutation runs in a native transaction with an undoable marker. The
adapter verifies document identity, marker, component/body/sketch revisions, parameters,
timeline and occurrence transforms before and after undo. A tool failure preserves
the checkpoint only if native Abort and model restoration are verified. Failed
commits or rollback mismatch invalidate the chain. Partial restore reports its
completed undo count and disables further restoration.

Motion previews run in temporary transactions that always abort and verify the
starting model/pose. They add no committed undo step. Generated preview files
remain outside CAD undo.

Native transactions use Fusion's hidden PTransaction interface. Its behavior is
runtime-specific and must be revalidated after Fusion updates. Host contracts are
checked in `tests/test_checkpoint_undo.py`, `tests/test_checkpoint_commands.py` and
`tests/test_fusion_undo_recovery.py`; installed CLI geometry and restore are checked
in `tests/live_cli_checkpoints_http.py`.
