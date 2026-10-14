# Registration engine and printed-guide boundary

Reviewed 2026-10-12. This is an engineering rationale, not a claim of universal
registration superiority or clinical fit validation. An exhaustive inventory of
every open-source registration project is not possible; the primary sources
below cover the principal implementation alternatives considered.

| Framework | Primary source | Relevance to this workflow |
|---|---|---|
| SimpleITK / ITK | [Registration overview](https://simpleitk.readthedocs.io/en/main/registrationOverview.html) | Multi-resolution metric/optimizer framework and rigid, affine and B-spline transforms. The current candidate uses bounded local CPU rigid anatomy registration with declared QC and human review. |
| ANTs / ANTsPy | [Registration documentation](https://antspyx.readthedocs.io/en/stable/registration.html) | Rigid/affine and deformable/SyN alternatives. Their availability does not establish patient-specific guide pose; changing backend requires comparative evidence on this acquisition domain. |
| elastix / ITKElastix | [Official repository](https://github.com/SuperElastix/elastix) | Modular rigid/nonrigid image registration and Python integration. Parameter maps and physical transform direction require explicit adapter validation, not silent interchange with the guide transform. |
| VoxelMorph | [Official repository](https://github.com/voxelmorph/voxelmorph) | Learned registration and dense spatial transforms. Trained-model/domain validation is required; a deformation field is not the rigid pose of an already printed guide. |

The current product implementation is `utils/guide_registration_cpu.py`, composed
by `web/guide_registration.py` and the captured `GuidePlacementService`. It is not
a downloaded-model demonstration or a fake registration matrix. Actual CPU
registration, overlays and human review are exercised in
`test_actual_product_guide_registration_and_review_on_synthetic_phantom`.

When a guide is observable and its region/material evidence is selected, the
workflow reconstructs that observed surface and performs bounded multistart
rigid surface fitting. Otherwise, anatomy registration provides an explicitly
estimated rigid guide pose, not a confirmed physical position. Corresponding
landmarks/manual rigid estimates are mathematically distinct evidence routes.
Ambiguity, failed fit, missing evidence, changed image content or changed guide
geometry cannot automatically become accepted initialization channels.

All printed mesh triangles, main bores and auxiliary bores receive the same
proper rigid SE(3) transform. No affine scale/shear or nonrigid displacement is
applied to that manufactured object. Optional future soft-tissue deformation
must remain a separate anatomical resource; it cannot be relabelled as a guide
matrix or used to warp the printed mesh. A stronger anatomical similarity score
alone cannot establish the guide's rigid pose.

Current CT overlays, candidate identity, physical printed-guide identity and
clinical-version-bound signed receipts are required for human acceptance.
Accept/reject decisions invalidate prepared channels and preserve original
manufacturing identity. Synthetic geometry and display tests do not prove real
printing strength, positioning accuracy or surgical feasibility.
