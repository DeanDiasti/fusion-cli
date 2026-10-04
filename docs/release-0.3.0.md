# CadBot CLI 0.3.0 release report

Historical release notes. Current setup and CLI workflows are in [the CLI guide](cli-guide.md).

Release build: `da711d4ee46c21a8` · bridge protocol 3 · validated October 3, 2026
on Autodesk Fusion 2705.1.15 (Education License), macOS, Python 3.14.

## Supported release scope

The CLI is ready for the supported command cases on this installation. The
release gate verifies 250 canonical command dispositions: 244 have passing live
cases, six are explicitly unavailable, and none remain unverified or failing.
This is not certification of arbitrary geometries, every flag combination, other
Fusion versions, or other platforms. The local bridge is for one trusted user.

The new CAD capabilities are three-point arcs, bounded fitted splines,
standalone sketch points, profile measurement, and selecting a profile for
extrude/revolve. Component ownership, mm/cm conversion, independent solid
volume, and native undo were checked in a disposable design.

Unavailable command paths:

- Form create-from-tsm, inspect, rename, and delete: safe native fixtures are
  missing, and empty Form creation has previously blocked Fusion. The public
  CLI now refuses these operations before native access.
- Configuration cell edit: no verified editable-cell/rollback fixture. The public
  CLI refuses this operation; other tested configuration operations remain available.
- Cloud project deletion: no public deletion API in this installed Fusion version.

Native rotation action **planning** passes; action authoring remains explicitly
blocked. Native timeline playback passes using an imported one-second storyboard.
That test verifies playhead progression, not component motion or video export.

## Checks and evidence

- 235 host tests, including malformed transport, checkpoint enforcement,
  source/build diagnostics, release restrictions, install rollback, credential
  preservation, and offline help from a staged installation.
- Palette JavaScript regression: sending, streaming, tool results/errors,
  cancellation, disconnection, and new chat.
- Seven native release gates: basic Design, curved sketches, core Design,
  extended Design, remaining Design, Administration, and Animation.
- Installed HTTP Design gates: 79 and 66 recorded rows.
- Installed HTTP policy gate: all five restricted commands refuse before native access.
- Installed HTTP Animation playback: start, intermediate positions, completion,
  and restoration of the original context.

Raw evidence for this historical release is retained privately and excluded
from the public repository. The initial public import contains
[redacted current-release evidence](public-evidence/41b3c0f4c7e81a3a/).
Historical results do not certify the current source tree.

```bash
# Runs locally without Fusion, credentials, cloud writes, or model calls:
.venv/bin/python scripts/check_release.py

# Also checks the installed/running add-in handshake:
.venv/bin/python scripts/check_release.py --runtime
```

## Repeating live checks

Save work first. Install the candidate with `./scripts/install_addin.sh`, restart
Fusion, and run CadBot. `./scripts/fusion doctor` must report the matching build.
Use Fusion's Python console to run each native gate, substituting the checkout's
absolute path and one of `curves`, `core`, `extended`, `remaining`, `basic`,
`animation`, or `admin`:

```python
import runpy
result = runpy.run_path('/absolute/path/cad-bot/tests/run_fusion_gate.py',
                       init_globals={'GATE_NAME': 'curves'})
```

The runner requires the loaded build to match source and stamps fresh evidence.
Then run these terminal gates sequentially, with Fusion free to service events:

```bash
.venv/bin/python tests/live_design_http_smoke.py
.venv/bin/python tests/live_design_coverage_http.py
.venv/bin/python tests/live_animation_playback_http.py
.venv/bin/python tests/live_release_policy_http.py
.venv/bin/python scripts/cli_coverage.py --write
```

The Administration gate creates UUID-named cloud fixtures. It cleans up its own
files/folders, but leaves one empty project because Fusion has no project delete
API. Do not run that gate merely to check CLI health; use `doctor`. The other
release fixtures are local disposable documents. Fusion can replace its pristine
startup Untitled during cloud open; the admin gate records this explicitly and
verifies the replacement remains empty/unmodified instead of claiming the
original document identity was restored.

After live gates pass, preserve current-build reports in the evidence directory,
regenerate coverage with `--reports-dir` pointing there, and update the manifest
only after reviewing the evidence. Reinstall to package the new coverage snapshot.

## Operations and recovery

Help is offline. `doctor` distinguishes unavailable bridge, rejected credentials,
and a stale loaded build. Invalid arguments exit 2; runtime/tool errors exit 1.
A timeout or interruption can leave a native call running: inspect the design
before retrying. The client never automatically retries a mutation.

Terminal Design edits require an active CadBot message checkpoint. The normal
modeling entry point is the Fusion chat. Checkpoint undo is session scoped;
document/workspace changes and external Fusion commands can invalidate it.
Native PTransaction compatibility must be revalidated after Fusion upgrades.

The installer stages a complete package, backs up the previous installation,
preserves credentials, and restores the previous directory if the swap fails.
For manual rollback, stop CadBot, restore the recorded sibling backup directory
as `CadBot`, restore its corresponding source checkout, and restart Fusion.
Keep the configured project virtual environment in place.

## Cleanup record

All disposable model documents and created cloud files/folders were closed or
removed. The final active document is an unmodified empty Untitled in Design.
Three empty cloud projects remain from the successive Administration gate runs;
their names are recorded below. No existing cloud design was edited.

- `CadBot-Admin-Gate-ec4f01a988-complete`
- `CadBot-Admin-Gate-1aa5b87f5f-complete`
- `CadBot-Admin-Gate-2c81b85236-complete`
