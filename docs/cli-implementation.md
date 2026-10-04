# Fusion CLI implementation status

## Release 0.5.0 — 2026-10-03

Build `41b3c0f4c7e81a3a`, protocol 3, was validated on Autodesk Fusion
2705.1.15/macOS. The catalog contains 257 canonical commands: 41 Administration,
196 Design, and 20 Animation. See [release evidence and reproducible checks](release-0.5.0.md).

| Section | Passing command cases | Explicit unavailable paths | Unverified / failures |
| --- | ---: | ---: | ---: |
| Administration | 40 | 1 | 0 / 0 |
| Design | 191 | 5 | 0 / 0 |
| Animation | 20 | 0 | 0 / 0 |

A passing case does not certify every input, option, or geometry. Animation
rotation has a passing planning case; its authoring path returns a verified
refusal. The unavailable paths are not counted as successful feature executions.

## Changes from the review

- Added parametric topology-matched sketch offset and segment trimming, with
  dimension association, geometry, and checkpoint restoration checks.
- Added occurrence-aware motion-joint discovery, easing, holds, configurable
  feasibility samples, and once/loop/ping-pong HTML playback.
- Added current-pose interference and sampled coordinated motion inspection,
  with root-assembly scope checks and mm³ pair-volume reporting.
- Fixed palette status polling during temporary capture: the status callback
  reports busy without validating an uncommitted pose against the saved signature.


- Added planar face/construction-plane sketch supports with component ownership
  checks and returned coordinate frames; face sketches start empty.
- Added paginated body topology discovery and linked/independent projection of
  same-component native geometry.
- Added through-all cut/intersect, explicit participant bodies, and positive,
  negative, and two-sided extents. Native gates verify volume, thickness changes,
  excluded-body isolation, associations, and checkpoint restoration.

- Added three-point arcs, open/closed fitted splines, standalone sketch points,
  and profile inspection with sketch-space area, perimeter, and centroid.
- Added explicit profile selection for extrude/revolve and sketch token lookup
  across components. Features are created in the sketch's owning component.
- Made help and argument validation work offline; added `doctor`, JSON help,
  deterministic exit codes, and separate authentication, connection, and stale
  build diagnostics. Mutations are never automatically replayed after timeout.
- Restricted transport to authenticated loopback, bounded request/response
  sizes, rejected malformed envelopes, duplicate flags, and nonfinite numbers,
  and prevented raw mutation tools from bypassing checkpoint dispatch.
- Made installation staged and recoverable with credential preservation and a
  random private token on first installation.
- Tied coverage to the loaded source fingerprint. Historical cases cannot certify
  a new build, and a failing current case takes precedence over a passing one.
- Added a persisted native storyboard fixture to verify real timeline playback
  over HTTP, including intermediate positions, completion, and context cleanup.

## Release boundaries

Form creation/inspection/rename/deletion and configuration cell editing are
explicitly blocked by the CLI release policy. Earlier evidence represented
missing safe test fixtures as capability checks; the new gate calls the actual
CLI dispatcher and verifies that these paths refuse before touching native CAD
state. Empty Form creation has previously blocked Fusion's main thread. A safe
Fusion-emitted TSM fixture and editable configuration cell fixture are required
before these paths can be enabled.

Cloud project deletion is unavailable in the installed public API. Native
Animation component rotation authoring is also unavailable; only its plan and
refusal are verified. Flange creation, public flat-pattern workspace activation,
and arbitrary Edit Form topology manipulation remain outside the exposed typed
API. Revolve uses component origin X/Y axes; extrusion supports distance and through-all. Through-all in moved/rotated
components is refused because native intersection failed in that fixture; face
sketching and projection in moved components are verified.

## Next CAD capabilities

1. Extrude-to-face and arbitrary-axis revolve.
2. Projection across assembly contexts and spline fit-point editing.
3. Native through-all support for moved/rotated components after resolving Fusion's
   intersection failure; keep the verified preflight refusal until then.
4. Safe fixtures for disabled Form/configuration paths and persistent native
   action verification before enabling rotation authoring.

Every new mutation must preserve checkpoint behavior and include independent
native geometry and cleanup checks. Re-run the release gates after Fusion or
add-in upgrades; the current evidence applies only to the recorded build/platform.
