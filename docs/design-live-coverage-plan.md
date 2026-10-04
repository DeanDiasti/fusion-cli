# Design live-coverage fixture plan

The coverage matrix currently has 106 Design commands without a passing live
case. This is a verification backlog, not a list of 106 missing implementations.
Every live gate below uses an unsaved disposable document and records the exact
command, expected subset, actual response, and pass result.

## Reusable fixtures

| Fixture | Command families | Current assessment |
|---|---|---|
| `live_design_coverage_http.py` assembly fixture | inspect, assembly instances, components, occurrences, joints | Implemented paths omitted by the earlier gate. Safe to verify with empty disposable components and an origin joint. |
| `live_design_coverage_http.py` sketch/body fixture | legacy sketch aliases, line editing, fixed state, dimensions, body combine, selection | Implemented paths omitted by the earlier gate. Safe to verify on disposable sketches and overlapping extrusions. |
| `live_design_coverage_http.py` construction/timeline fixture | construction list/create/rename/delete, timeline inspect/roll/navigation/groups, viewport screenshot | Implemented paths omitted by the earlier gate. Timeline group content deletion needs its own isolated feature group before it can be asserted. |
| `fusion_design_remaining_smoke.py` topology fixture | joint face/edge/vertex placement, loft rail/centerline, sweep path/guide selectors | Newly implemented public-API paths. Pending live execution after add-in reload. |
| Surface fixture | patch, inspect, stitch, thicken, delete | Implemented. Needs two adjacent surface profiles and separate delete/thicken branches so consuming operations do not invalidate later selectors. |
| Solid-feature fixture | revolve, chamfer, circular/rectangular patterns, hole, shell, draft, feature edit/delete | Implemented. Needs one disposable body per topology-changing family because indices and tokens become stale. |
| Sheet-metal fixture | rules, component creation, conversion, fold/unfold/refold, flat-pattern lifecycle | Implemented public or preview paths, but license/API availability is runtime-dependent. Each unavailable preview operation must be recorded as a concrete runtime blocker rather than counted as passed. |
| Material fixture | inspect, copy, edit, apply, clear, delete | Implemented. Requires selecting a copyable asset from the installed library and deleting only the disposable design copy. |
| Configuration fixture | initialize, row CRUD, activate, cell edit | Implemented API surface, but configuration initialization changes document mode. Safe only in a dedicated disposable document; column-dependent edits need an observed editable column. |
| Form fixture | create-from-TSM, inspect, rename, delete | Lifecycle is implemented, but a version-compatible TSM fixture is still required. General vertex/edge/face editing is a true installed public-API blocker. |
| Motion fixture | drive, check, render, open | Implemented. Uses a disposable revolute joint and temporary-transaction restoration; `open` requires the render output path. |

## True implementation blockers

- Typed flange creation: installed `FlangeFeatures` is read-only and exposes no
  public `createInput`/`add` path.
- Flat-pattern workspace activation: the installed public API exposes flat
  pattern creation and data access but no activation method.
- General T-Spline topology editing: public `TSplineBody` exposes naming, TSM
  serialization, and texture mapping but no vertex, edge, or face collections
  and no geometry transform methods.

All other rows remain coverage omissions until a disposable gate records a
passing expected/actual result or a specific runtime capability failure.
