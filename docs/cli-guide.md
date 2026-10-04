# fusion-cli guide

Use typed commands from your terminal to model, inspect and animate designs in
Autodesk Fusion. Release 0.6.0 contains 261 canonical commands; see the
[release scope](release-0.6.0.md) for verified cases and unavailable operations.

## Installation on macOS

```bash
brew install DeanDiasti/tap/fusion-cli
fusion-install-addin
```

Save work, restart Fusion, then open **Scripts and Add-Ins → Add-Ins → CadBot →
Run**. You can enable Run on Startup. CadBot is the CLI bridge add-in; it starts
the authenticated loopback server.

For source development, create a Python 3.10+ virtual environment and run the
installer. No third-party Python packages are required:

```bash
python3 -m venv .venv
./scripts/install_addin.sh
./scripts/fusion help
```

The installer stages the complete add-in and CLI, backs up a previous installation
and preserves the owner-only bridge token. Reinstall after add-in code changes.
Homebrew users run `fusion`; source users run `./scripts/fusion`.

## Commands and diagnostics

```bash
fusion help
fusion help design
fusion design sketches offset --help
fusion --json design features extrude --help
fusion doctor
fusion app inspect
fusion design inspect
```

Help and version work without Fusion. `doctor` checks authentication, protocol and
the exact installed build. Add `--json` before a command for structured help.
Exit codes are 0 for success, 1 for runtime/tool failure, 2 for invalid input and
130 for interruption. A timeout does not prove a running native operation stopped;
inspect state before retrying. Mutations are never automatically replayed.

If port 8765 is occupied, stop the older bridge before starting another instance.
After installing new source, restart Fusion to clear cached Python modules.
An invisible local HTML callback also wakes the queue on Fusion versions that
reject custom events. It accepts no CAD commands or arguments; CAD stays on the
main thread. A dispatch timeout cancels queued work that has not started.

## Model with explicit checkpoints

Read-only commands work once the add-in is running. Begin a checkpoint for Design
edits or temporary motion previews:

```bash
fusion checkpoint begin --id plate
fusion design sketches create --name Base
fusion design sketches rectangles add --sketch Base --x1-mm 0 --y1-mm 0 --x2-mm 20 --y2-mm 10
fusion design features extrude --sketch Base --distance-mm 5 --operation new
fusion checkpoint finish
fusion checkpoint status
# Optional: reverse this checkpoint and all later recorded changes.
fusion checkpoint restore --id plate
```

Use `--document-id` on begin/restore to assert the intended active design.
Checkpoints are session-only and external operations can invalidate them.
See [checkpoint behavior](checkpoints.md) for recovery and compatibility.

Lengths and coordinates use millimeters; angles use degrees. Quote names with
spaces. List flags use JSON arrays. Entity tokens or unique names identify objects;
refresh topology and profile indices after edits. Supported commands are a finite
grammar with no shell evaluation or arbitrary Python executor.

## Architecture and local bridge

```text
Terminal → cli/fusion_cli.py → authenticated localhost HTTP
    → Fusion bridge → custom-event dispatcher → Fusion main-thread CAD API
```

The bridge includes a small invisible dispatch page to support runtimes with
unreliable custom events. It contains no conversation interface.

The CLI and installer use the Python standard library. Fusion's bundled Python
loads the add-in. All CAD API calls run on Fusion's main thread.

The server listens on localhost:8765 and authenticates `X-CadBot-Token`. The
terminal discovers the installed `.bridge_token`; `CADBOT_BRIDGE_TOKEN` can
override it. The uninstalled development fallback is `cadbot-dev-token`; use the
installer for real designs. The client does not forward credentials through proxies
or redirects. Keep the bridge local. See [SECURITY.md](../SECURITY.md).

Document/workspace changes, cloud administration and native Animation operations
have different side effects from Design undo. They can invalidate Design checkpoints.
Use offline help and `app capabilities` to inspect restrictions. Host tests do not
certify native behavior; see [validation](validation.md).

## Modeling examples

### Face-based modeling

Create a sketch on a planar face or construction plane, project source geometry,
and cut through selected bodies:

```text
fusion design bodies topology list --body Plate --kind faces
fusion design sketches create --support FACE_TOKEN --name Rim
fusion design sketches project --sketch Rim --entities '["FACE_TOKEN"]'
fusion design sketches profiles list --sketch Rim
fusion design sketches create --support FACE_TOKEN --name Holes
fusion design sketches circles add --sketch Holes --center-x-mm 20 --center-y-mm 15 --radius-mm 2
fusion design features extrude --sketch Holes --extent through-all --operation cut --participants '["Plate"]' --direction negative
```

Replace `FACE_TOKEN` with a token from topology discovery. The circle coordinates
above are an example: use the returned sketch `frame` to interpret local X/Y and
normal in the owning component. Face sketches start empty, without automatic
edge projection. `--component` asserts support ownership, or selects the owner
when creating an origin-plane sketch. Components are definitions: edits affect
all their instances. Cross-component sketch supports/projection are rejected.

Projection is linked by default; `--linked false` makes independent geometry.
Project native faces, edges, vertices, sketch curves, or sketch points from the
same component. Face projection projects its edges. Use `--kind edges` or
`vertices` for finer selection, and paginate large bodies with `--offset/--limit`.
Refresh topology and profile indices after edits.

Through-all supports cut/intersect with explicit participant bodies. Choose
positive/negative relative to the sketch normal, or `both` for an interior
sketch with material on both sides. Do not combine it with distance or symmetric
flags. It remains through-all after thickness changes. Fusion currently fails
this operation in moved/rotated components; the CLI refuses that case before
native mutation. Use a root/untransformed component or an explicit distance.
Face sketching and projection remain available in moved components.

All mutations use the existing CLI checkpoint. These commands were verified
with real geometry, participant isolation, associative updates, and undo through
both native and HTTP release gates.

### Curved sketches and profile selection

The source CLI now includes arcs through three points, open/closed fitted splines,
standalone sketch points, and closed-profile inspection:

```text
fusion design sketches create --name Outline
fusion design sketches arcs add --sketch Outline --points-mm '[[0,0],[10,10],[20,0]]'
fusion design sketches lines add --sketch Outline --x1-mm 20 --y1-mm 0 --x2-mm 0 --y2-mm 0
fusion design sketches profiles list --sketch Outline
fusion design features extrude --sketch Outline --profile-index 0 --distance-mm 5 --operation new
fusion design sketches create --name Path
fusion design sketches splines add --sketch Path --points-mm '[[0,0],[10,20],[30,10]]'
fusion design sketches points add --sketch Outline --x-mm 10 --y-mm 5
```

Coordinates are `[x,y]` pairs in sketch-space millimeters. Arc points are start,
through, and end; Fusion may reverse returned endpoints to store the arc
counterclockwise. Splines accept 2–100 distinct points; `--closed true` requires at
least three and creates a periodic spline without repeating the first point.
Arcs and splines work with the existing geometry inspection, construction, fixed,
and deletion commands. Use `geometry list` for current point indices when placing
holes. Profile inspection reports approximate area in mm², perimeter in mm, and
centroids in sketch space; refresh indices after editing a sketch.

Extrude and revolve accept `--profile-index` (default 0) and a sketch token or
unique name, including sketches in components. Features are created in the sketch's
component; revolve's X/Y axes are that component's origin axes.

These operations passed the live curved-sketch gate on the release build,
including independent profile-area and solid-volume checks, component ownership,
and native checkpoint restoration. The fixture and evidence are described in
[the release report](release-0.4.0.md). As with other Design edits, these
commands require an active CadBot CLI checkpoint.

### Joint-motion previews

```text
fusion design motion joints list
fusion joints drive --joint "Hip" --axis rotation --value 20
fusion animation render --fps 12 --seconds 2 --tracks '[{"joint":"Hip","axis":"rotation","keys":[[0,0],[0.5,25],[1,0]]}]'
fusion animation open --path "/path/returned/by/render/animation.html"
```

`design motion joints list` discovers regular and as-built joints, occurrence names, current
positions, supported axes and limits. Rotation values use degrees; slide values
use millimeters. Use returned assembly-path selectors, or unique names. Suppressed/locked
joints and out-of-limit keyframes are rejected. Animation tracks use normalized
time from 0 to 1. Optional track `easing` accepts `linear`, `ease-in`, `ease-out`,
`ease-in-out`, or `step`; equal consecutive values create a pause. Multiple tracks
animate together. `--playback once|loop|ping-pong` selects HTML playback behavior.

Rendering produces a self-contained HTML player with play/pause and scrubbing,
then restores all driven axes to their initial values, including on capture
failure. Rendering is bounded to 120 frames, 24 tracks and 10 seconds; start with
24 frames. Fusion may be busy during capture and a native call cannot always be
interrupted. `animation open` opens only the generated preview paths. The output
is stored in the system temporary directory; save a copy for long-term retention.

This supports existing rotation/slide joints, not automatic rigging, inverse
kinematics, ground contact, continuous collision detection, dynamic balance, native Motion
Study creation or video export. A robot walking preview requires a suitable
jointed assembly and explicitly selected joint trajectories. Linked or constrained
axes may prevent a requested pose; commands report solver mismatches.

Live regression: `tests/fusion_design_motion_smoke.py` creates a disposable
slider/revolute assembly, renders previews, verifies interference volumes and pose
restoration, and checks undo.

Before rendering, use `fusion design motion check --tracks '...'` to check five
uniform poses plus all keyframes. `--samples 2..61` changes the uniform count.
Start with one driver and inspect passive/other-instance motion before adding more.
Errors identify requested/actual values, units and sample time. Preview fidelity
allows 0.05 degrees or 0.01 mm. Unlimited rotations compare modulo 360 degrees.

Checks and renders now execute in **temporary transactions that always abort**.
No manual drive-back operation is used. Before reporting success, the controller
compares the document/model signature (including occurrence transforms), undo
marker, and all observed joint-axis values with their pre-preview snapshots.
A verified preview adds no committed checkpoint undo step. Motion errors remain
errors even when rollback succeeds, with recovery explicitly reported. An abort
failure or state mismatch invalidates the checkpoint chain; no blind retry occurs.
Generated files are outside Fusion's undo state and remain temporary artifacts.
A sampled feasibility check does not prove collision-free motion or every intermediate frame.

### Assembly-instance joint selection

`fusion design motion joints list` returns selectors such as
`full-leg-1:1+leg:1::joint:Revolute 8`. Each selector resolves the native joint
through Fusion's assembly-context proxy for that occurrence. Root joints use
`@root::joint:Name`; as-built joints use `::as-built:Name`. Names are accepted only
when unique across the complete assembly. Older definition-level tokens are
rejected; list joints again when reusing old selectors.

`fusion assembly instances` lists full occurrence paths, legacy grounding,
Ground to Parent and external-reference state. `animation check` now observes
all supported joint axes after each sample and reports passive-joint motion,
other-instance motion. The transaction controller verifies state after abort.
These observations do not automatically establish independence or complete pose
restoration. Grounding is never changed by these commands.

Instance-routing regression tests use shared component fixtures. The dog assembly
copy test encountered external-reference import/detachment failures, so independent
motion of the actual dog instances has not yet been verified. Do not interpret
unit-test success as validation of this assembly's kinematics.

### Design editing and interference

`fusion design sketches offset --sketch Outline --entities '["CURVE_TOKEN"]' --distance-mm 2`
creates a parametric offset. Supply end-connected curve tokens in flow order.
Positive distance offsets right (outward for circles); negative offsets left.
Topology must match. Driving source dimensions preserves the intended parametric
relationship; dragging unconstrained geometry across its offset can change sides
in Fusion's solver. Inspect resulting geometry after edits.

`fusion design sketches trim --sketch Outline --entity CURVE_TOKEN --x-mm 15 --y-mm 0`
removes the segment nearest that sketch-space point. Without intersections, it
deletes the whole curve. Fixed/linked curves are refused. Refresh geometry tokens
and profile indices after editing. Both mutations use Design CLI checkpoints.

```text
fusion design motion joints list
fusion design assembly instances
fusion design interference check --entities '["occurrence:Base:1","occurrence:Slider:1"]'
fusion design motion inspect --samples 21 --entities '["occurrence:Base:1","occurrence:Slider:1"]' --tracks '[{"joint":"@root::joint:Slide","axis":"slide","keys":[[0,0],[0.4,-15],[0.6,-15],[1,0]],"easing":"ease-in-out"}]'
```

Inspect accepts 2–32 distinct root solid body names/tokens or explicit occurrence
paths, containing at most 100 solid body instances. Overlapping inputs and native
child body definitions are refused. It reports pair intersection volumes in mm³
at uniform samples plus keyframes, with at most 120 analyzed poses. The default
uniform count is 21. Coincident faces are excluded. Pair-volume totals can overlap
and are not union volumes. Motion inspection restores the starting pose by a
verified transaction abort and creates no interference bodies.

Sampling can miss thin or brief collisions between poses. This is kinematic
interference inspection, not continuous collision detection, clearance checking,
contact simulation, or native Animation authoring. Joint orientation controls the
sign of motion; test a small displacement before choosing trajectories.
