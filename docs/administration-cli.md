# Administration CLI release scope

The Administration CLI now exposes 41 typed commands across application,
workspace, document, project, folder, file, and cloud-job management.

- Application: inspect build/runtime, capability matrix, operational state,
  diagnostics, read-only preferences, and list/inspect/cancel/forget jobs.
- Workspaces: list and activate by exact ID or unique name.
- Documents: list, inspect (including unsaved documents), create, activate,
  save, save-as, open cloud files, import local F3D/STEP/IGES/SAT/SMT, export
  F3D/STEP/IGES/SAT/SMT/STL, and guarded close.
- Projects: list, inspect, create, rename, and an explicit typed deletion
  blocker.
- Folders: list, inspect, bounded recursive search, create, rename, and guarded
  deletion.
- Files: list, bounded recursive search, inspect versions and references,
  rename, copy (including the preview reference-aware API), move, guarded
  deletion, upload with job tracking, and download of non-Fusion files.

All cloud selectors resolve by stable Fusion/APS ID. Project and workspace names
are accepted only when unique. Folder/file traversal is bounded by `--limit`.
Cloud deletion refuses project roots, nonempty folders unless `--recursive` is
explicit, and referenced files unless `--allow-referenced` is explicit.
Document close refuses unsaved changes unless `--discard-changes` is explicit.

## Installed API boundary

Fusion 2705.1.15's installed `adsk.core.DataProject` has no deletion method, so
`fusion projects delete` returns a precise capability blocker and directs the
caller to Fusion Team. `DataFileFuture` exposes `uploadState` and `dataFile` but
no cancellation method; `fusion app jobs cancel` therefore returns
`cancelled: false`, `cancel_supported: false`, and the installed-API reason.
The other planned Administration operations have typed public API paths.

## Verification

`tests/test_admin_release.py` covers the complete registry, parser safety,
search bounds, deletion guards, typed import/export, upload/download, and
truthful job lifecycle behavior. `tests/fusion_admin_release_smoke.py` is the
live release gate. It creates UUID-named fixtures, avoids all existing cloud
designs, removes every created file and folder, restores the original document
and workspace, and records the unavoidable empty test project retained because
Fusion cannot delete projects through its public API.
