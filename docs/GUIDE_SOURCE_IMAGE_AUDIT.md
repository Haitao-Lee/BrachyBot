# Original printed-guide source image audit — 2026-10-13

Scope: local bounded sidecar in `timepoints-implementation-20261010`.
Changed only `web/guide_service.py`, `web/guide_registration.py`, the new
`tests/test_guide_original_source_image.py`, and this note. No pipeline,
planning-run, surgical-guide generation, reference, remote, freeze, or production
changes. This is provenance/rigid-storage contract evidence, not clinical or
manufacturing validation.

## Reproduction and actual paths

The fixture uses real `WorkspaceStore` and `TimepointImageService` uploads for
different synthetic acquisitions A/C in one preoperative collection and B in
an associated intraoperative timepoint. A and C deliberately have equal grids
and different pixels. The immutable synthetic printed mesh and saved parent
Planning belong to A. The fixture selects C through `update_image`, without
changing the printed mesh or resetting the selection back to A.

Two distinct pre-repair observations matter:

1. A normal A-to-C reference change archives A's results in `image_resources`
   and clears the current agent results (`TimepointImageService._set_reference`).
   `GuidePlacementService.guide_records` ignored those archives. The two initial
   regression cases failed with "The exact source guide version is unavailable".
   This path was already closed; it did **not** demonstrate a wrong completed pose.
2. With the old immutable parent retained in current Planning history through
   a real owned `save_timepoint_results` write, the registration start path was
   reachable. `GuideRegistrationJobs.start` called `_target_ct_image(source)`
   and `_target_image(source)`, capturing C. The baseline retained-parent test
   failed on the exact image-ID assertion: captured C versus expected A.
   That test intercepts only dispatch to inspect actual job inputs; it does not
   substitute an optimizer or claim fit accuracy.

Pre-repair overlay similarly called `_target_ct_image(source)`; publication and
current-candidate fences compared `_target_image(source)`. They could agree on
the wrong acquisition because all followed the current selection.

The saved parent already contains `timepoint_resource_state.fingerprints.image`.
`capture_resources` constructs that leaf from canonical physical pixel content,
reference image ID, and the source/volume/voxel/geometry/frame/modality receipt.
`PLANNING_VALUE_KEYS` preserves `timepoint_resource_state` in the parent snapshot.
It is a fingerprint, not an explicit ID. Registration did not previously resolve it.

## Repair and fences

`GuidePlacementService._guide_source_image` now resolves the selected guide's
`planning_id` against current and acquisition-archived parent snapshots. It
rejects conflicting parent image leaves and conflicting guide/manifest source
Planning metadata. Archive/current reference IDs are lookup hints only.

An owned candidate must match the frozen parent image fingerprint. Both the
original upload and selected volume file hashes are checked through
`TimepointImageService.source_file`; decoded pixel and physical-grid receipts
are checked too. The fingerprint includes the unique image ID, so a verified
match is exact provenance resolution rather than first-image selection.
Search is bounded to at most eight candidate IDs and 64 million cumulative
decoded voxels, with header checks before pixel allocation. Parent-only cases
without an archive ID can search a small collection. A larger unresolved search
fails closed and asks for provenance review.

The job read-set records the verified original image, acquisition receipt,
parent leaf, Planning ID and resolution policy. Image-derived publication,
validation, current-candidate access and overlay re-resolve and compare that
provenance. Review invokes those checks. The candidate signature covers the
read-set, so the existing signed overlay receipt's candidate hash also binds
the source provenance without changing the route's receipt schema.

Overlay resamples that same original source image. Target B still uses its
explicit current reference. The existing rigid local-guide-to-source composition
and manufactured mesh checks are retained. Source reference selection is never
changed by resolution.

Archived guides are now discoverable, including after source-image deletion.
Direct `visible_guide`, or `auto` with a selected visible-guide ROI, does not
load a source acquisition. A real child test demonstrates that the existing
surface reconstruction/rigid fit can publish a review-pending candidate after
A is deleted. Its synthetic cube-versus-mesh fixture is not a fit-quality or
acceptability claim. No optimizer or surface algorithm was changed.

Existing image-derived candidates without verified original-source provenance
must be estimated again. Current source/target clinical and lifecycle CAS
dependencies remain conservative: a later source reference/clinical change
can still invalidate a captured job or candidate, even if A's bytes survive.

## Explicit legacy policy

- A single owned acquisition with no saved parent image leaf is allowed only
  when the collection has exactly one image record and no acquisition resource
  archive. Its recorded policy is `legacy_single_owned_acquisition`, with
  `original_acquisition_verified=false`. A second or deleted historical image
  prevents this compatibility fallback; filtering to one active image is unsafe.
- A legacy single-CT state without an owned collection uses
  `legacy_single_ct_content_fenced`. This verifies current scoped CT content,
  not historical acquisition identity; that limitation is recorded explicitly.
- If a single-CT parent *does* have an image leaf, it must match. Its policy is
  `saved_parent_single_ct_fingerprint`; changed pixels cannot take the legacy
  bypass. Multi-image legacy records and archived states cannot use this fallback.

## Bounded verification

Interpreter: `C:\Users\hunte\anaconda3\python.exe -E -X utf8`.
`C:\gsi1013new` was verified nonexistent before the first run; distinct baseline,
repair and neighboring-test subdirectories keep test stores separate.

- Baseline normal-switch regression: **2 failed**, guide unavailable because
  archive discovery was missing.
- Baseline retained-parent job-input regression: **1 failed**, captured C's ID
  instead of A's ID.
- Final new suite: **17 passed**, 3 SimpleITK SWIG deprecation warnings,
  **47.26 s**. Includes actual image and visible-guide child jobs, payload capture,
  original-A overlay pixels, review/restart, deletion/missing/altered files,
  parent conflict, missing provenance, version ambiguity and legacy policies.
- Neighboring `test_guide_registration_workflow.py`,
  `test_guide_registration_cpu.py`, `test_guide_tool_manifest.py`, and
  `test_timepoint_images_integration.py`: **38 passed, 1 failed**, **71.59 s**.
  The sole failure is the existing child-crash assertion requiring
  "child exited without a result"; Windows returned
  `[WinError 109] 管道已结束。` after the job reached `failed`. The receive/error path
  is unchanged by this sidecar. No Linux-baseline equivalence is claimed.
- Final neighboring rerun with that identified Windows child-crash assertion
  explicitly deselected: **38 passed, 1 deselected**, **66.61 s**. This rerun
  uses the final service code; the earlier failure remains reported above.

Windows tests use two explicit harness accommodations: POSIX directory fsync is
unsupported, and Linux `os.kill(pid, 0)` liveness probes send `CTRL_C_EVENT` on
Windows. Test fixtures bypass directory fsync and recognize their own test-job
owner PID. Image decoding, owned file/receipt checks, store/CAS, child algorithms
and publication are real. The first runs exposed these platform issues;
successful runs do not validate native Windows durability or worker liveness.

## Remaining interactions and possible separate scope

The verified standard path requires no API/UI selector or minted field in
`web/surgical_guide.py`; its existing parent image leaf supplies the proof.
Missing/mismatched multi-image evidence deliberately blocks image registration
instead of retroactively assigning C or any first acquisition. Direct visible
guide fit remains available through the existing method/ROI contract.

The current HTTP route converts service exceptions to a generic localized
registration error; the detailed provenance reason is logged. The overlay now
includes `source_provenance`, but the existing UI does not display an acquisition
label. A dedicated visible provenance/recovery experience would require changes
to `web/routes/guide_registration_routes.py` and
`web/app/static/js/brachybot-guide-registration.js`, with route/browser tests.
Those files are outside this sidecar and were not edited.

If multiple acquisition histories contain different prints with the same numeric
guide version, this service fails closed on conflicting geometry/manifest/Planning
provenance. Selecting a specific print among those collisions requires adding
Planning/manifest identity to the request and inventory selection contract across
the same route/UI files, `GuideRegistrationJobs`, and service lookups. It must not
be implemented by choosing the first version entry.

For future guides whose parent lacks any frozen image leaf, permanently minting
an image receipt in the bore manifest would require `web/surgical_guide.py`,
generation-contract tests and the owner's dependency-hash/reference renewal.
That expansion was not needed for the confirmed parent-fingerprint path and
was not performed. Main retains expensive full guards, reference renewal and
any later deployment/freeze work.
