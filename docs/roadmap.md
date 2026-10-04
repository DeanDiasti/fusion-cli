# Roadmap

The current release focuses on typed commands, explicit selectors, bounded
operations and independent native verification. New capabilities should complete
useful CAD workflows while preserving those properties.

## Next capabilities

- **Design refinement:** extrusion up to a face, arbitrary revolve axes, spline
  fit-point editing and projection across assembly contexts.
- **Reusable modeling:** parametric bracket/enclosure/hinge recipes built on the
  verified command catalog, with dimensional and geometry checks.
- **Assembly inspection:** clearance/distance measurements and richer sampled
  interference reports, including exportable summaries.
- **Manufacturing output:** sketch DXF, batch part exports and assembly bills of materials.
- **Native presentation:** persistent component transforms, exploded views and
  camera sequences, verified after save/reopen before enabling action writes.
- **Portability:** a Windows installer and live platform/version matrix.

## Blocked or experimental paths

Native component rotation authoring, Form entity operations and configuration
cell edits require safe persistent fixtures and verified execution/rollback.
Moved-component through-all extrusion remains refused after native failures in
that scenario. These should remain explicitly unavailable until their proof gates
pass. Public API presence, mock success and storyboard duration alone do not prove
successful geometry or persistent native animation.

Continuous collision detection, physical contact/dynamics, automatic rigging and
video publishing are separate substantial features. Sampled joint previews and
interference reports do not establish these capabilities.

See the current release report for supported cases and open an issue to propose a
bounded implementation, official API reference and synthetic test scenario.
