# CadBot CLI 0.4.0 release report

Historical release notes. Current setup and CLI workflows are in [the CLI guide](cli-guide.md).

Release build: `ae63c40b6456c132` · bridge protocol 3 · validated October 3, 2026
on Autodesk Fusion 2705.1.15 (Education License), macOS, Python 3.14.

## Supported release scope

The CLI is ready for the supported command cases on this installation. The
release gate verifies 252 canonical command dispositions: 246 have passing live
cases, six are explicitly unavailable, and none remain unverified or failing.
This is not certification of arbitrary geometries, every flag combination, other
Fusion versions, or other platforms. The local bridge is for one trusted user.

This release adds sketches on planar faces and construction planes, native
face/edge/vertex discovery, linked and independent sketch projection, and
through-all cut/intersection with explicit target bodies. Previous arcs, splines,
profile measurement, and profile selection remain verified.

The native gate checks positive/negative/two-sided extents, cut and intersection
volumes, thickness changes, participant isolation, projection associativity, and
undo, including recovery after a nonintersecting-target failure. A second gate executes the entire face/project/cut/restore workflow over
HTTP against the installed add-in.

Through-all requires root or untransformed components. Native Fusion rejected
moved-component intersections in a disposable probe; the CLI now refuses that
case before creating a feature. Face supports and projection in moved components
are verified. Two-sided through-all expects an interior plane with material on
both sides. Projection accepts same-component native geometry only.

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

- 242 host tests, including malformed transport, checkpoint enforcement,
  source/build diagnostics, release restrictions, install rollback, credential
  preservation, and offline help from a staged installation.
- Palette JavaScript regression: sending, streaming, tool results/errors,
  cancellation, disconnection, and new chat.
- Eight native release gates: face modeling, basic Design, curved sketches, core Design,
  extended Design, remaining Design, Administration, and Animation.
- Installed HTTP face modeling gate: face sketch, projected perimeter, targeted hole, native undo.
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
absolute path and one of `face-modeling`, `curves`, `core`, `extended`, `remaining`, `basic`,
`animation`, or `admin`:

```python
import runpy
result = runpy.run_path('/absolute/path/cad-bot/tests/run_fusion_gate.py',
                       init_globals={'GATE_NAME': 'curves'})
```

The runner requires the loaded build to match source and stamps fresh evidence.
Then run these terminal gates sequentially, with Fusion free to service events:

```bash
.venv/bin/python tests/live_face_modeling_http.py
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
Two additional empty cloud projects remain from this release's successive Administration
gates because Fusion exposes no project-delete API:

- `CadBot-Admin-Gate-4887c46a18-complete`
- `CadBot-Admin-Gate-b027b1110e-complete`

The prior release's three projects are listed in [its historical cleanup record](release-0.3.0.md).

## API references

The implementation follows Autodesk's [empty face sketch creation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_Sketches_addWithoutEdges.htm),
[linked projection](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_Sketch_project2.htm),
[one-sided extents](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_ExtrudeFeatureInput_setOneSideExtent.htm),
and [participant bodies](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_ExtrudeFeatureInput_participantBodies.htm)
APIs. Live evidence, rather than API presence, determines the supported scope.
