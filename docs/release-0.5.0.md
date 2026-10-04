# CadBot CLI 0.5.0 release report

Historical release notes. Current setup and CLI workflows are in [the CLI guide](cli-guide.md).

Release build: `41b3c0f4c7e81a3a` · bridge protocol 3 · validated October 3, 2026
on Autodesk Fusion 2705.1.15 (Education License), macOS, Python 3.14.

## Supported scope

This release adds five canonical commands: parametric sketch offset, segment
trim, occurrence-aware motion-joint discovery, current-pose interference, and
sampled motion inspection. Existing check/render commands gain configurable
samples, track easing and pauses, and once/loop/ping-pong playback. The catalog
contains 257 commands, with 251 passing live cases and six explicit unavailable
paths. The evidence applies to recorded cases on this installation, not every
geometry, flag combination, Fusion version, or platform.

Offset uses the current `createOffsetInput`/`addOffset2` API and preserves topology.
Distances are signed mm; positive is right of input flow and outward for circles.
Source dimension changes update the offset. Dragging unconstrained curves across
the offset can switch sides in Fusion's solver; inspect geometry after edits.
Trim removes the segment nearest a sketch-space point and deletes the entire
curve when it has no intersections. Fixed/linked curves are refused. Both edits
require a Design message checkpoint, and topology tokens should be refreshed.

Motion accepts 1–24 existing rotation/slide tracks with 2–32 normalized keyframes
per track. Easing supports linear, ease-in, ease-out, ease-in-out and step. Equal
consecutive values create pauses. Joint orientation determines signed movement;
use a small feasibility check before selecting a trajectory. Native regular
joint creation expects the moving occurrence first. Motion discovery returns
assembly-context track selectors, separately from assembly-edit selectors.

Interference accepts 2–32 distinct root solid body names/tokens, root-context body
proxies, or `occurrence:<full path>` selectors, with at most 100 solid body instances.
Native child body definitions, overlapping scopes and duplicates are refused.
Reports contain pair intersection volumes in mm³ without creating model bodies.
Coincident faces are excluded; summed pair volumes can overlap and do not measure
their union. Inspection checks uniform poses plus every keyframe, up to 120 poses.
The default uniform count is 21; feasibility checks default to five.

All motion previews run in transactions that abort. The controller verifies the
model signature, undo marker and all observed joint axes before reporting success.
Palette polling during viewport capture now reports busy instead of comparing a
temporary pose against the saved signature and invalidating the checkpoint.
Failed capture removes incomplete output folders.

Sampling can miss thin or brief collisions between poses. This is not continuous
collision detection, clearance analysis, contact/dynamics simulation, automatic
rigging, native Motion Study creation, video export, or persistent native component
animation authoring. Those remain future work.

The existing six unavailable paths and moved-component through-all restriction
remain documented in [the previous release](release-0.4.0.md). Native rotation
authoring remains blocked; its planning/refusal and persisted timeline playback
are verified separately.

## Verification

- 255 host tests, including offline motion validation, scope/duplicate rejection,
  preflight ordering, preview dispatch and reentrant palette status polling.
- Palette JavaScript regression and actual player JavaScript checks for all three
  playback modes, replay, pause and scrubbing.
- Nine native gates: Design/motion, face modeling, curved sketches, core,
  extended, remaining, basic Design, native Animation, and Administration.
- Six installed HTTP gates: Design/motion, face modeling, expanded Design,
  Design coverage, release restrictions and native Animation playback.

The new native fixture checks circle offset association through a driving
parameter, middle-segment trim lengths, whole-curve deletion, native undo,
independent simultaneous slider/revolute tracks, exact 500 mm³ overlap at paused
poses, all playback modes, and rollback after an injected analysis failure at a
changed pose. The installed HTTP fixture independently builds an assembly, checks
inward offset and trim/undo, performs sampled inspection, renders a preview and
verifies its starting pose and original document/workspace restoration.

[Public evidence](public-evidence/41b3c0f4c7e81a3a/) contains redacted current-build
case summaries and report/source/fixture SHA-256 hashes. Raw results and account
metadata are kept local. The public summaries preserve gate dispositions and
geometry/cleanup assertion flags; detailed tool responses are withheld. See
[the publication workflow](validation.md). Historical reports do not certify this
build. Both packaged coverage snapshots must match the durable evidence.

```bash
.venv/bin/python scripts/check_release.py
.venv/bin/python scripts/check_release.py --runtime
```

## Repeating live checks

Install the candidate, restart Fusion, and run CadBot after saving your work.
Use the Python console runner documented in [0.4.0](release-0.4.0.md), adding the
`design-motion` gate. Then run sequentially:

```bash
.venv/bin/python tests/live_design_motion_http.py
.venv/bin/python tests/live_face_modeling_http.py
.venv/bin/python tests/live_design_http_smoke.py
.venv/bin/python tests/live_design_coverage_http.py
.venv/bin/python tests/live_animation_playback_http.py
.venv/bin/python tests/live_release_policy_http.py
```

Review successful fresh reports, keep raw reports private, publish redacted summaries under the current build,
regenerate coverage against that public directory, refresh the manifest after
checks, and reinstall
the coverage snapshot. The verifier reads evidence and never silently certifies
changed code. Administration creates an empty cloud project that the public API
cannot delete; use `doctor` for routine health checks.

## Cleanup

All disposable design fixtures and created cloud files/folders were closed or
removed. Administration leaves one new empty test project,
`CadBot-Admin-Gate-5686b2412f-complete`, because Fusion has no public project-delete
API. Its identity is recorded in the archived Administration report. Earlier empty projects are recorded in
[0.4.0](release-0.4.0.md). The final active design is an empty unmodified Untitled.
Preview files live in the system temporary directory and are outside CAD undo.

## API references

Autodesk documents [parametric offset input](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_GeometricConstraints_createOffsetInput.htm),
[offset creation](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_GeometricConstraints_addOffset2.htm),
[segment trimming](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_SketchCurve_trim.htm),
[root-context interference input](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_Design_createInterferenceInput.htm),
and [transient interference volumes](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_InterferenceResult.htm).
Supported scope is determined by the live evidence.

## Initial public import

The GPL-3.0-only import keeps the CAD Python fingerprint unchanged. Add-in metadata
now matches 0.5.0. Publication tooling, portable host-test invocation and redaction
checks were added; the complete host suite now has 259 tests. Raw historical
reports, scratch probes and private model investigation notes remain local.
Public summaries reference original report hashes and preserve their dispositions;
they do not imply that omitted account/tool details are publicly available.
