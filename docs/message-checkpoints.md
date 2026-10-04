# Implemented session-based message restore

CadBot now records a boundary before every new user message. Restore controls are application-owned and never ask the agent to execute Undo. Three choices are exposed on messages: design only, conversation-only branch, or both.

Native implementation: `bridge/fusion_undo.py` groups each mutating tool in a `PTransaction.Start`/`Commit` transaction containing an undoable design attribute. `message_undo.py` groups those verified transactions by message. Before/after each native undo, the adapter checks the marker, document identity, component/body/sketch revisions, parameters, timeline, and occurrence transforms. Live tests on this Fusion build verified multiple-message restore, solid creation, component deletion restoration, and refusal after outside API edits.

Compatibility: PTransaction is a hidden Fusion text-command interface, not a promised stable public transaction-manager API. Unexpected return values fail closed. Revalidate the live smoke test after Fusion updates. Native failure invalidates the chain rather than retrying Undo blindly.

Any external Fusion command conservatively invalidates the previous design-undo chain, even commands which may not modify geometry. Switching documents, reloading CadBot, restarting Fusion, or reconnecting the worker also invalidates it. A new message establishes a fresh chain. Historical chat branching remains available across sessions for messages recorded with turn IDs. No past design checkpoints can be reconstructed.

UI: `Restore before this message` appears under new user messages. Design options are disabled when their IDs are not in the current verified session ledger. The original chat is preserved on conversation branches. Selected text/attachments return to the composer. A persisted context notice ensures subsequent agent work knows whether geometry was restored or retained.

Checkpoint state is not an archive snapshot. This implementation does not restore cloud versions, persist Fusion's undo stack, selectively reverse a single old operation while preserving its dependents, or provide redo buttons. Restore before message N reverses N and later recorded changes. Failed partial undo reports its completed count and disables further restore.

Validation: `tests/test_message_undo.py`, worker restore tests in `tests/test_chat.py`, the synthetic real-SDK fork smoke test in `tests/smoke_chat.py`, and the in-Fusion `tests/fusion_undo_smoke.py`. Model data is not transmitted by the native undo tests.

---

## Earlier archive-based proposal (future fallback, not implemented)


Status: implementation proposal, researched against Fusion API and installed Codex SDK. Not implemented or enabled.

## User behavior

Each submitted user message owns a checkpoint of the design and conversation immediately BEFORE that message. All tool calls in its response belong to that checkpoint. The previous response's end state is not reused: a user may have manually edited Fusion between messages.

A Restore control beside the user message opens these choices:

- Design only: open the checkpoint design as a restored working copy; retain the current chat and add a restoration record to both the displayed transcript and agent context.
- Conversation only: create a conversation branch ending before the selected message; leave the design unchanged. Put the selected message back in the composer without sending it. Tell the new agent branch that the active design includes changes from later work and must be inspected again.
- Design and conversation: restore the working copy and branch the conversation to the matching point. Keep the original conversation and design accessible.

Use 'Before this message' consistently. Restoring before message N removes the effect of N and subsequent work from the restored working copy; it does not selectively undo only N while preserving later dependent changes. Do not offer selective undo with this name.

## Integration points

- agent/palette_worker.py: assign stable message UUID; create pre-turn checkpoint before thread.turn; persist checkpoint status before allowing tool execution. Track Codex turn IDs and branch boundaries. Restore operations use an exclusive worker operation state, separate from sending/cancellation.
- agent/history.py: extend user events with message_id/checkpoint_id. Store checkpoints as independent manifests plus archives under the existing CadBot data root. Preserve original branches. Record restoration events, source branch, source message, target document, and resulting branch.
- Fusion bridge: add application-owned checkpoint capture/restore operations. These should be called by the worker/UI, not offered as agent-directed MCP tools. All Fusion operations go through the main-thread dispatcher.
- palette/chat.js and index.html: show checkpoint state and Restore menu on each user message, including when replaying saved history. Disable switching/sending/restoring while capture, turn, or restore is active. No tool-call-level checkpoint controls.

## Snapshot contents

Manifest: schema version, checkpoint UUID, stable conversation/message IDs, Codex thread ID and pre-turn boundary, creation time, source document session ID, cloud data-file ID/version where available, design name, active configuration and timeline marker where available, archive filename/checksum/size, capture status, and explicit supported/unsupported reason.

Document names are labels, not identity. Unsaved documents need a session identity and a persistent lineage identifier attached to the checkpoint. Imported working copies must be rebound explicitly. A checkpoint from another design must never silently replace the active design.

Capture a complete native design archive, not STEP/STL, screenshots, or parameter-only records. Parameter diffs can supplement snapshots for review but cannot restore deleted sketches, joints, or components.

Write archive into a unique temporary checkpoint directory. Check export success, file existence/nonzero size, checksum, then atomically publish the manifest. Only completed manifests count as restore points. Preserve interrupted turns' pre-message checkpoints. Missing/corrupt archives disable design restoration while conversation branching remains available.

Retain checkpoint archives until explicitly removed. Do not silently prune checkpoints reachable from a saved conversation. Show disk usage; retention controls can be added later. Old conversations cannot acquire genuine historical design snapshots retroactively.

## Fusion restore constraints

Fusion's createFusionArchiveExportOptions exports the root component and contents when no geometry is specified. importToNewDocument opens a new unnamed, unsaved document. Initial restoration therefore opens a working copy and keeps the original open; it does NOT overwrite the cloud document or promise in-place Undo semantics.

Before restore, preserve current unsaved work as a recovery snapshot when supported. Import the target, verify a valid Design and expected feature/body/parameter structure, then activate and bind the restored working copy. Do not close the original. Failed import must leave original model/conversation active; retain any partially completed branch/recovery record for diagnosis.

Linked assemblies require separate handling: the documented local archive import supports F3D only; F3Z uses DataFolder.uploadFile. Detect external references/configurations and validate round-trip support before enabling design restore. Never break links or flatten an assembly silently to make capture succeed. Until a supported dependency-aware restore is implemented and tested, show 'Design checkpoint unavailable: linked assembly' and require an explicit per-message 'Continue without design checkpoint' choice. Conversation-only branching remains possible.

Do not run model edits if capture fails without showing the failure and getting the user's explicit choice to proceed unprotected. Chat-only requests may also incur capture overhead in the initial straightforward implementation; optimize only without losing pre-message coverage.

## Conversation boundaries

The installed openai-codex 0.154 high-level thread_fork does not expose last_turn_id. Current documented protocol supports thread/fork lastTurnId, but runtime support must be integration-tested; do not assume documentation alone means the bundled runtime accepts it.

Preferred: use the typed low-level protocol if supported, fork through the LAST completed turn before the selected user message. For the first message, start a fresh thread with the same CadBot instructions/configuration. Never fork through the selected message itself. Alternative: preserve a pre-turn full fork on submission, before starting any work, if bounded historical forking is unavailable. Do not use destructive rollback on the original thread or reconstruct context by sending the visible transcript as a new user prompt.

Resume/fork with fresh CadBot MCP config and validate tool inventory. Persist branch ID before changing the active UI selection. Ensure a 'design only' or 'conversation only' restore is represented in model-visible context, not solely local JSON history. Require fresh get_state/list_parameters inspection before subsequent edits.

## Required validation before enabling

1. Capture -> parameter edit -> restore: original expressions, timeline, and dimensions return.
2. Capture -> sketch/extrusion/fillet creation or deletion -> restore: topology and editable history return.
3. Capture -> joint/occurrence deletion -> restore: joints/components return in correct positions.
4. Existing linked-bearing assembly: preserve external references or explicitly block unsupported restoration.
5. Conversation-only branching retains current geometry and excludes later turns from model context.
6. Design-only restoration retains chat and informs agent of changed document state.
7. Combined restore returns both to the same boundary, keeping originals recoverable.
8. Restart/reconnect during capture/turn/import: no half-written checkpoint advertised as ready.
9. Wrong active document, missing archive, failed export/import, disk full, duplicate clicks, running tool call.
10. Manual Fusion edits between messages are captured at the next submission.

## References

- https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_ExportManager_createFusionArchiveExportOptions.htm
- https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_ImportManager_importToNewDocument.htm
- https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_ImportManager_createFusionArchiveImportOptions.htm
- https://learn.chatgpt.com/docs/app-server (thread/fork, thread/resume, lastTurnId)

Recovery: a tool exception preserves the current message and earlier checkpoints only when native Abort succeeds and the document, marker, and model signature match the pre-tool boundary. Failed commits, failed aborts, and mismatched state still invalidate the chain. The palette explains unavailable design restores inside each message menu.
