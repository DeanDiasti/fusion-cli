# CadBot CLI and Fusion chat guide

Chat with a Codex-powered CAD assistant **inside Autodesk Fusion**. The CadBot
palette accepts prompts and reference images and shows streaming responses,
named CAD tool calls, arguments, results, and errors.

## CLI release 0.5.0

The typed CLI has 257 commands, with native Fusion and HTTP integration evidence
for build `41b3c0f4c7e81a3a` on Fusion 2705.1.15/macOS. The release gate covers 251
commands with passing cases and six explicit unavailable paths. Form entity
operations and configuration cell editing are disabled pending safe live
fixtures; native rotation authoring remains disabled, with planning available.
This release adds sketch offset/trim, eased coordinated previews, and sampled
interference reports. See [release scope and verification](release-0.5.0.md).

```bash
./scripts/fusion help
./scripts/fusion doctor
.venv/bin/python scripts/check_release.py --runtime
```

## Use in Fusion (macOS)

1. Run `./scripts/install_addin.sh` after installing the Python environment below.
2. Save your work and restart Fusion to clear cached add-in modules.
3. Open **Scripts and Add-Ins → Add-Ins → CadBot → Run**.
4. Wait for **Ready** in the palette, then type a request. If needed, click
   **Sign in** to complete ChatGPT sign-in in your browser.
5. Enable **Run on Startup** in Fusion if desired.

**You do not need to launch an agent in a terminal.** Fusion starts its background
process when the chat opens and stops it when the add-in shuts down.

- **Images:** click **＋ Image**, paste, or drag and drop PNG/JPEG/WebP images.
  Up to four images per message, 5 MB each. Remove a thumbnail before sending
  to omit it. Images are sent to Codex with your message.
- **Tool activity:** expand a tool card to inspect its arguments and results.
- **Stop:** interrupts the agent. A CAD operation already executing may finish;
  Stop does not undo geometry that has already been created.
- **New chat:** starts a fresh conversation without clearing the Fusion design.
- **Reconnect:** restarts the agent process if it disconnects. Saved conversations and their Codex thread IDs can be resumed after reconnecting
  or restarting; reopening a chat does not restore its Fusion design.

## Initial setup

Create a virtual environment for a fresh checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/install_addin.sh
```

Use a Python version supported by `openai-codex==0.154.0` (this project was tested
with Python 3.14). The SDK uses the local Codex runtime and your Codex sign-in. If no runtime is available, install Codex from its official distribution.
The installer copies the add-in and agent files into Fusion's AddIns folder,
records the project's virtual-environment path, and backs up an older installation.
Keep the project and `.venv` in place; reinstall after moving them or editing code.

## Architecture

```text
Fusion chat palette
    │ Fusion HTML events: send / poll / stop / new / sign-in
    ▼
ChatSession → managed Python worker → Codex SDK (streaming conversation)
                                         │ named MCP CAD tools
                                         ▼
                                 agent/cad_mcp.py
                                         │ authenticated localhost HTTP
                                         ▼
Fusion bridge → custom-event dispatcher → Fusion main-thread CAD API
```

The SDK runs outside Fusion's bundled Python so its dependencies cannot prevent
Fusion from loading the add-in. SDK startup, generation, and pipe I/O run off the
Fusion UI thread. CAD operations remain on Fusion's main thread. Codex uses a
read-only filesystem sandbox and automatic approval review; rejected operations
appear as tool errors. The palette uses text rendering for model output.

## Diagnostics and verification

Errors appear in the palette. Startup and cleanup diagnostics are also recorded
in `~/cadbot_debug.log`. If the bridge port is occupied, close the older add-in
instance before retrying. If the worker is missing, reinstall from the project.

Run local regression tests (no model or Fusion needed):

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node tests/test_palette.cjs
node tests/test_motion_player.cjs
```

Optional live Codex test, using **only synthetic fixture data and a generated red
image**, never the active Fusion design:

```bash
.venv/bin/python tests/smoke_chat.py
```

This verifies streaming, MCP delivery, and image input. Real CAD geometry is checked by the separate native and HTTP gates documented
in the release report. The optional Codex test is not part of the offline gate.

Use `./scripts/fusion` for terminal commands. `help`, command `--help`, and
`--version` work without Fusion. `doctor` checks authentication and the exact
loaded build. Add `--json` before a command for machine-readable help. Exit codes
are 0 for success, 1 for runtime/tool failure, 2 for invalid input, and 130 for
interruption. A timed-out mutation is never automatically retried.

## CAD tools

Discover the supported catalog with `./scripts/fusion help design` and inspect
runtime restrictions with `./scripts/fusion app capabilities`. The CLI covers
sketches, profiles, solids, components, joints, construction geometry, surfaces,
meshes, sheet metal, materials, parameters, and timeline operations. Availability
depends on the operation, active design, and installed Fusion API.

## Local bridge

The HTTP bridge listens on localhost:8765 and requires `X-CadBot-Token`.
The token comes from `CADBOT_BRIDGE_TOKEN`, the add-in's `.bridge_token` file,
or the development fallback `cadbot-dev-token`. The managed worker inherits the
same token automatically. The installer generates a random token with owner-only
file permissions on first install and preserves an existing token. The terminal
client discovers the installed token automatically. Requests are limited to
loopback and never forward credentials through proxies or redirects. Raw mutation
and administration tool calls are disabled; use the structured CLI. This is a
single-user local tool. Installation stages the full package before replacing it
and restores the prior installation if the swap fails.

### Saved conversations

New conversations are saved automatically. Use the Conversations picker above the chat to reopen one and continue its original Codex thread. Messages, tool activity, and model settings are restored. Switching is disabled while a request runs. A resumed conversation uses the currently active Fusion document; opening a chat does not reopen or restore a design.

CadBot keeps its history and attached reference files in `~/Library/Application Support/CadBot/conversations`, outside the add-in installation. Chats created before this history feature are not automatically imported. Reconnect and restart preserve saved chats.

### Restore before a message

New messages include a **Restore before this message** menu. Choose **Undo design to here**, **Branch chat from here**, or **Undo design + branch chat**. Undo is executed by CadBot, without a model call, and reverses the selected message and later recorded work in the same Fusion document. Branching retains the original conversation and places the selected request back in the composer.

Design undo is session-only. External Fusion commands, outside model edits, document changes, reconnects, and restarts can invalidate older checkpoints. The menu disables those design options; conversation branches remain available for messages recorded with the new IDs. Any external command currently invalidates conservatively, including some commands that do not change geometry. Start a new message to establish a fresh checkpoint chain. Archive snapshots and redo controls are not part of this implementation.

The native adapter uses Fusion's hidden PTransaction interface with explicit markers and model-state verification. Rerun the in-Fusion undo smoke test after Fusion upgrades. See `docs/message-checkpoints.md` for implementation and compatibility details.

### Structured Fusion CLI

The chat agent uses one `fusion` tool with a traditional command string. Start with
`fusion help`, `fusion help bodies`, or `fusion bodies combine --help`.
There is no Python executor, shell evaluation, or arbitrary API access.

Examples:

```text
fusion design inspect
fusion bodies list
fusion bodies combine --target arm --tools '["ring"]' --operation join
fusion features extrude --sketch base --distance-mm 10 --operation join
fusion parameters list --query length
fusion timeline list
```

Commands have validated flags; lengths are millimeters and angles degrees. Names
with spaces require quotes. List flags accept JSON arrays. Help is generated from
the same catalog used to parse commands. Supported groups cover existing sketch,
feature, inspection, parameter, timeline, export and reset helpers, plus body
listing and Combine. Combine currently requires bodies in the same component;
use body tokens from `bodies list` to disambiguate duplicate names.

Edits require an active chat message and run through its transaction controller.
Read-only commands and help do not create undo entries. The tool card shows the
command and result. This covers registered commands, not every Fusion operation.
Additional capabilities require deliberate command implementations.

For optional terminal use, `./scripts/fusion bodies list` sends the same command
to the running add-in. No terminal is needed for chat. Standalone terminal edits
are rejected without an active message checkpoint.

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

All mutations use the existing message checkpoint. These commands were verified
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
commands require an active CadBot message checkpoint.

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
A verified preview adds no committed message undo step. Motion errors remain
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
rejected; list joints again when resuming an older conversation.

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
and profile indices after editing. Both mutations use Design message checkpoints.

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
