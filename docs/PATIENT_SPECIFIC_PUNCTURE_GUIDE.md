# Patient-Specific Puncture Guide

## Scope

BrachyBot can generate a patient-specific, CT skin-fitting puncture guide from
the active case's planned or manually edited needle geometry. The guide is a
planning and manufacturing-preparation artifact, not a cleared medical device
or a substitute for institutional manufacturing, sterilization, fit, or
clinical approval workflows.

The feature is implemented natively in the Python/Web deployment. Operators do
not need to compile or launch the legacy `surgical_guide` C++ desktop program.

## Geometry contract

All geometry uses the existing BrachyBot/SimpleITK physical patient-world
coordinate system in millimetres. The implementation does not add RAS/LPS
sign flips. This same contract is used by the CT, planner, manual needle
editor, 2D/3D viewers, DICOM import paths, and exported STL vertices.

The native implementation was checked against the useful stages of the legacy
C++/VTK/CGAL workflow:

1. Threshold the CT to obtain a connected patient body surface.
2. Intersect each planned needle's external-to-target centreline with that
   surface to obtain a skin entry.
3. Construct a local skin-offset plate and fuse outer sleeve solids.
4. Subtract finite, coaxial inner guide bores.
5. Extract and validate a closed triangle mesh before STL export.

Rather than relying on `vtkBooleanOperationPolyDataFilter` for near-coplanar
surfaces, the native implementation performs the solid operations on an exact
isotropic physical lattice in the bounded guide region and extracts one final
isosurface. This avoids the known fragility of polygonal boolean operations
while preserving the requested physical dimensions. The source CT is not
globally resampled or mutated.

## Web controls

Open **Input → Manual Fine Planning → Puncture guide parameters**. All values
are saved with the current case and applied only when **Generate guide** is
pressed.

| UI parameter | Units | Default | Meaning |
| --- | --- | ---: | --- |
| Skin threshold | HU | -300 | CT threshold used to define the patient body surface. |
| Skin clearance | mm | 1.0 | Offset from the thresholded skin surface to the plate. |
| Plate thickness | mm | 3.0 | Printable shell thickness. |
| Patch margin | mm | 24.0 | Surface patch radius around each selected entry. |
| Channel diameter | mm | 2.2 | Inner guide-hole diameter. The UI converts it to the internal radius exactly once. |
| Sleeve outer diameter | mm | 6.0 | Outer support sleeve diameter. It must exceed the channel diameter. |
| Sleeve outward/inward length | mm | 8.0 / 8.0 | Sleeve extents on either side of the skin entry. |
| Geometry resolution | mm | 1.0 | Isotropic local construction lattice. Smaller values improve detail but cost time and memory. |

The **Guided needles** multi-select can create a guide for a deliberate subset
of planned needles. Leaving it empty includes every current planned needle.

## Versioning and stale-state handling

Each successful generation creates an immutable guide version. Up to five
versions are retained per case; each stores its parameters, selected needle
IDs, source-plan signature, skin-entry coordinates, triangle mesh, and STL QA
metadata. The saved-version selector can inspect an earlier version without
changing the active planning geometry.

Any change to planning needle or seed geometry marks all saved guide versions
as stale. This is intentional: a stale guide is still auditable, but it must
not be assumed to fit the new plan. Generate a new version after confirming
the edited plan.

## STL validation and export

Before export BrachyBot verifies finite vertices, valid face indices, and
strict two-face edge closure. The exported bytes are parsed and verified a
second time. The **Validate imported STL** control performs the same read-only
mesh QA on an external STL (maximum 64 MiB) and never replaces the active guide
or patient geometry.

This geometric QA does not validate printer calibration, material, sterility,
patient fit, collision-free insertion, source loading, or clinical suitability.
Those remain explicit local quality-control and clinician responsibilities.

## Tests

`tests/test_surgical_guide.py` verifies:

- watertight guide generation and STL round-trip validation;
- rejection when CT or planned needle geometry is missing;
- physical-coordinate correctness on anisotropic CT with a flipped slice
  direction; and
- version retention, parameter provenance, and grouped stale invalidation.
