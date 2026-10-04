# fusion-cli 0.6.0 release report

Release build: `eed1b12ce2969c86` · bridge protocol 4 · validated October 3, 2026
on Autodesk Fusion 2705.1.15 (Education License), macOS, Python 3.14.

## CLI-only runtime

The source now contains the terminal CLI, Fusion bridge, CAD handlers, installation
and validation tooling. The Fusion chat UI, conversation history code, agent/MCP
worker and Codex SDK dependency are removed. The CLI and installer use only Python's
standard library. Autodesk Fusion remains separately installed and licensed.

The terminal code lives in `cli/`. CadBot remains the installed bridge add-in name.
The installer copies a self-contained CLI/bridge package without a worker path or
runtime configuration file. It preserves an existing private bridge token and
backs up the previous installation. Existing user data outside the add-in is retained.

Four new commands make Design editing usable independently from chat:

```bash
fusion checkpoint begin --id bracket
# Run Design edit commands or temporary motion previews.
fusion checkpoint finish
fusion checkpoint status
fusion checkpoint restore --id bracket
```

Begin/restore accept `--document-id` to assert the intended active document and
require a Design workspace. Edits outside an active checkpoint are refused. Restore
reverses the selected checkpoint and every later recorded checkpoint, after
verifying native undo boundaries. External edits, document changes and restarts
can invalidate the session ledger. See [checkpoint behavior](checkpoints.md).

Fusion's custom-event API on this installation can register events but refuse
to fire them, including after a clean restart. The bridge therefore keeps an
invisible local HTML wakeup that drains its queue through Fusion's main-thread
callback. It exposes no conversation UI, accepts no CAD arguments, fetches no
external resources and does not bypass HTTP authentication. The runtime fingerprint
includes this dispatch page. Timeout cancellation prevents queued work from running
later; an already executing native operation is not automatically replayed.

## Supported scope and limits

The catalog contains 261 canonical commands: 255 have passing recorded live cases
and six are explicitly unavailable. This includes four checkpoint controls plus
the Design, motion, native Animation and Administration scope from
[0.5.0](release-0.5.0.md). Evidence applies to recorded cases on this installation,
not every geometry, flag combination, Fusion version or platform.

Form creation/inspection/rename/deletion, configuration cell edits and cloud project
deletion remain unavailable. Native Animation rotation authoring remains refused;
its planning case is verified. Moved/rotated-component through-all extrusion remains
refused. Motion sampling is not continuous collision detection or dynamics; native
transactions use the runtime-specific hidden PTransaction interface. Windows
installation and native behavior are not validated.

## Verification

- 244 host tests run with Python `-S`, without third-party site packages.
- Motion-player JavaScript tests and website link/search-metadata checks.
- Nine native Fusion gates: Design/motion, face modeling, curved sketches, core,
  extended, remaining, basic Design, native Animation and Administration.
- Seven installed HTTP gates: the six existing regression gates and a new explicit
  CLI checkpoint gate. All run with Python `-S` and no chat interface.

The new HTTP fixture independently creates a 20 × 10 × 5 mm solid, measures its
volume and dimensions, refuses edits without a checkpoint, duplicate/concurrent
IDs, wrong-document begin/restore, restore during active work and unavailable
restore. It verifies three native undo steps restore empty bodies/sketches and
closes the disposable document. All gates verify cleanup. Administration removes
created files/folders but leaves an empty test project because the public API
cannot delete projects; do not run it for routine health checks.

[Public evidence](public-evidence/eed1b12ce2969c86/) binds redacted gate summaries
to the build and exact source/test/fixture hashes. Raw results and account metadata
remain private. See [validation and publication](validation.md).

```bash
.venv/bin/python -S scripts/check_release.py
.venv/bin/python -S scripts/check_release.py --runtime
```

## Repeat live checks

Save work, install the candidate, restart Fusion and run CadBot. Run the gates in
Fusion's Python Text Commands console:

```python
import runpy
results = [runpy.run_path('PATH_TO_CHECKOUT/tests/run_fusion_gate.py',
    init_globals={'GATE_NAME': name}) for name in
    ('design-motion', 'face-modeling', 'curves', 'core', 'extended',
     'remaining', 'basic', 'animation', 'admin')]
```

Run HTTP gates sequentially from the source checkout:

```bash
.venv/bin/python -S tests/live_cli_checkpoints_http.py
.venv/bin/python -S tests/live_design_motion_http.py
.venv/bin/python -S tests/live_face_modeling_http.py
.venv/bin/python -S tests/live_design_http_smoke.py
.venv/bin/python -S tests/live_design_coverage_http.py
.venv/bin/python -S tests/live_animation_playback_http.py
.venv/bin/python -S tests/live_release_policy_http.py
```

Publish fresh passing summaries, regenerate coverage, and refresh the manifest only
after reviewing validation. Reinstall to package coverage and verify `fusion doctor`.
Published historical evidence cannot certify a changed runtime.

## Upgrade

Save work and stop CadBot before upgrading the Homebrew package. Run
`fusion-install-addin` again, restart Fusion and run CadBot. Source users run
`./scripts/install_addin.sh`. Protocol 4 rejects stale chat-era installations.
The current source, website and Homebrew package no longer require an AI account.
