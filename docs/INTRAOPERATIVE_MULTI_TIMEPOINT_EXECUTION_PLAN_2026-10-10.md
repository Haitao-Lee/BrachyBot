# Multi-timepoint workspaces and intraoperative continuation planning

- Version: 0.3 design and execution contracts.
- Date: 2026-10-10; requirements updated 2026-10-11 (Asia/Shanghai).
- Status: confirmed requirements and partially implemented candidate; complete product integration and clinical commissioning remain pending.
- Authoritative application checkout: `/home/lht/snap/brachyplan/BrachyBot`.
- Inspected HEAD: `0d840e38bea3fb36b8e9b3cf3acb33220062f3bc`, with existing uncommitted changes preserved.
- Scope of this delivery: this document only. No product patch, deployment, inference, patient mutation, or server restart.

## 1. Purpose and interpretation of the user's clarification

The intended system manages multiple imaging timepoints for one patient inside one Session and one shared conversation. An intraoperative timepoint uses its own current image and anatomy, reconstructs observed implanted seeds, computes their contribution with the existing CNN dose engine, and optimizes only additional interventions. If an existing printed guide is reused, its immutable manufactured geometry and physically realized channels constrain the additional paths.

The user's conceptual dose-continuation approach is accepted. The earlier audit identified that the current implementation does not propagate that initial dose through its optimizer; it did not reject the user's approach.

### 1.1 Confirmed decisions

| ID | Confirmed requirement | Consequence |
|---|---|---|
| D01 | One Session shares information across multiple timepoints, but each timepoint has independent mutable state. | Shared read access; explicitly scoped writes and revisions. |
| D02 | The printed preoperative guide must be reused, not replaced with a newly printed guide during the intraoperative continuation. | Preserve manufactured artifact identity and estimate a rigid placement. |
| D03 | Seed positions and directions are reconstructed from intraoperative evidence. | Do not inherit a preoperative seed axis as authoritative truth. |
| D04 | Seeds were generally deposited in straight batches through needles, although individual seeds may migrate or rotate. | Use a three-dimensional deposition-line prior without forcing every seed to share it. |
| D05 | Existing implanted seeds and their dose are fixed initial conditions. | Every optimizer reset, refinement, fallback, and repair retains the baseline. |
| D06 | More useful auxiliary channels should provide more feasible continuation candidates while respecting manufacturing constraints. | Optimize feasible path coverage, not raw hole count. |
| D07 | A timepoint marked intraoperative requires an explicit associated preoperative timepoint. | Intraoperative creation or relabeling cannot silently leave the source unbound. |
| D08 | Preoperative planning is a reference; intraoperative choices and observed seed counts may differ. | No equality requirement or mandatory one-to-one mapping to the original plan. |
| D09 | The intraoperative image is the reference for continuation anatomy and dose. | Never silently fall back to the preoperative CT. |
| D10 | Normalized and Gy dose fields must be unambiguous. | Fix the legacy intraoperative unit contract and its readers, writers, exports, and migration. |
| D11 | Supplied direction code can inform reconstruction, with a replaceable adapter for later user-provided code. | Preserve an explicit method/version/source contract. |
| D12 | Session save and load must include the entire multi-timepoint model. | Migration, checkpointing, hydration, archive, restore, export, and garbage collection are first-class workstreams. |
| D13 | Detected implanted seeds must be reconstructed and displayed in vivid, distinct colors. | Separate implanted and planned roles; persist appearance and show uncertainty without relying on color alone. |
| D14 | If the reconstructed existing dose already meets the configured coverage goal, do not add sources. | Preserve/evaluate full target, hotspots and OAR; no unnecessary optimization or guide generation. Coverage alone does not establish overall safety. |
| D15 | Prefer realized unused guide channels, then search outside the guide if they cannot meet the goal. | Preserve first-phase additions and fixed implants, treat the positioned guide material as a hard obstacle, and validate new skin-entry paths against OAR, implants and already selected needles. |
| D16 | A request without a timepoint qualifier targets the Table Viewer mounted when the human submits it. | Capture stable Session/timepoint identity before waits or queueing; retain it through retries, child image analysis, tool calls, callbacks and publication. Never consult a later navigation default. |
| D17 | All new controls, status, errors and dialogs follow the global language manager. | Use supported locale codes and structured message identities; live language changes preserve values, IDs and custom names. Conversation reply language retains its separate existing human-language contract. |
| D18 | An explicit different timepoint must be resolved and authorized, not inferred from a stale tool argument. | Same-Session read comparison can use explicit IDs. Noncurrent clinical mutation needs human target confirmation; until that receipt flow is integrated, request selection/resubmission rather than execute on another workspace. |

### 1.2 Proposed defaults, not user-approved clinical parameters

- The first validated continuation path is a same-treatment, CT-based workflow. Other modalities can be stored and displayed; inference capabilities remain modality-specific.
- One timepoint can store multiple images and has one designated planning reference image.
- The timepoint INPUT form uses its normal Image field; the stage badge chooses the workflow. A second intraoperative Image field inside the same timepoint is not proposed.
- Same-timepoint image background visibility is mutually exclusive in the normal three MPR views. Selecting another image does not silently change the planning reference or registration of clinical overlays.
- Soft deletion, an impact preview, and dependency checks precede irreversible purge.
- New guides may still be generated in preoperative workflows. Intraoperative reuse neither alters the printed guide nor generates a replacement by default.
- Source-plan completion requirements, research-versus-clinical operating mode, source strength/time semantics, mechanical tolerances, and handling of in-situ needles remain unresolved in Section 19.

## 2. Code baseline: facts verified by source inspection

This is targeted architectural inspection, not an assertion that every application file has been exhaustively audited.

| Component | Current source behavior | Required change |
|---|---|---|
| `agent_runtime/core.py:330,419` | One `AgentMemory.planning_results` mapping and one UI state per Session. | Session conversation/catalog plus scoped timepoint result views. |
| `web/server.py:609` | Agent cache is keyed by account and Session. | Keep one conversation coordinator; obtain explicit timepoint contexts for executors. |
| `web/workspace_store.py:41,2641,2690` | Schema version 1; single agent/UI/report/operation snapshot; other versions rejected. | Versioned migration reader, multi-timepoint storage, and compatibility adapter. |
| `web/workspace_store.py:3495` | Full checkpoint replaces the single `planning_results` and prunes arrays not referenced by it. | Timepoint CAS publication and graph-wide reference retention. Active-only pruning would delete inactive timepoint data. |
| `web/workspace_store.py:3618` | Hydration has a lightweight metadata phase and a heavy artifact phase. | Preserve this pattern; hydrate only requested timepoints with generation fencing. |
| `web/app/static/js/brachybot-ui-api.js` | Global current CT, metrics, seeds, report-related state, and annotations. | Per-timepoint state stores with one mounted set of UI components. |
| `agent_runtime/chat_workflows.py:7230,7270` | Existing intraoperative flow requires a source plan and equal planned/detected counts. | Explicit source binding; unequal counts are normal and not an automatic failure. |
| `agent_runtime/chat_workflows.py:7380` | Shared FrameOfReferenceUID or equal origin/direction is treated as verified frame correspondence. | Coordinate metadata is not anatomy or guide placement validation. |
| `agent_runtime/chat_workflows.py:7448` | Continuation discards the intraoperative image argument, reads preoperative CT, removes covered target voxels, and calls the normal planner. | Intraoperative anatomy, fixed baseline dose, and complete-target evaluation. |
| `plans/core.py:490`; `plans/reinforcement.py` | Multiple initialization/reset/reconstruction paths begin from zero dose. | Baseline-preserving rule, RL, fallback, and repair APIs. |
| `agent_runtime/chat_workflows.py:7641` | Legacy intraoperative path stores normalized values under `dose_distribution_gy`, alongside a separate scaled field. | A typed physical-dose contract and provenance-based legacy repair. |
| `web/surgical_guide.py:635,4527` | Auxiliary bores are generated and deconflicted; final manifest lacks a complete reusable axis contract. | Store realized axes, dimensions, material bounds, QA, and printed-guide identity. |
| Supplied SeedFinder `test_single_ct.py` | CT inference returns source CT, final mask, center CSV, and point JSON; preprocessing resamples to 1 x 1 x 5 mm. | Thin inference adapter plus original-space reconstruction/QC. |
| Supplied `seed_pipeline_deepdec_roi.py` | 3D PCA helper exists; another helper forces XY-plane axes; final export is centers, not per-seed directions. | Do not confuse unused helper functions or Fiducial orientation with measured seed axes. |

The supplied inference package is located at `C:\work_and_study\code\seed implantation\seedfinder_inference`. Existing demo outputs are algorithm products, not independently established ground truth. No demo inference was run for this design.

## 3. Identity, ownership, and dependency model

### 3.1 Entities

| Entity | Required identity and fields |
|---|---|
| Session | `session_id`, owner, patient linkage, shared conversation, global language, catalog revision, treatment-episode references. |
| Timepoint workspace | UUID, display title, `preoperative`/`intraoperative`, acquisition timestamp/timezone or unknown, source-preoperative ID, optional previous-intraoperative ID, episode ID, lifecycle status, revision. |
| Image | UUID, timepoint ID, original filename, owned artifact reference/hash, modality/phase, grid/physical frame, content revision, role, acquisition metadata. |
| Structure | UUID, source image ID, label map/target semantics, classification, source/provenance, mask artifact and geometry, revision. |
| Implant observation set | UUID/revision, source image, detector/method manifest, detections, review state, coverage/FOV assessment, center-to-component associations. |
| Physical seed identity | Session/episode-scoped UUID, distinct from detector-local label and observed point index. |
| Seed observation | Observation UUID, optional linked physical seed UUID, actual LPS center, axis or unknown, dimensions/source metadata, evidence, uncertainty, review state. |
| Plan revision | UUID, timepoint, immutable inputs, fixed observation set, initial dose, candidates, additional seeds, total evaluation, status. |
| Guide design | Immutable geometry revision, local coordinate frame, bore manifest, parameters, source-plan revision, manufacturing checks. |
| Manufactured guide | UUID, exact design and exported STL hashes, manufacturing confirmation, optional material/process/marker records. |
| Guide placement | UUID/revision, manufactured guide ID, target intraoperative image, rigid transform, landmarks/segmentation evidence, QC/review state. |
| Registration | Source/target image revisions, transform kind/direction, artifacts, ROI, parameters/backend version, QA state, purpose. |
| Report/annotation/export | UUID, timepoint or explicit multi-timepoint scope, referenced revisions, current/stale status, artifact/provenance and presentation. |

An inferred deposition line is not an observed physical needle. It has its own type and must not invent skin entry, needle tip, or an actual needle length.

### 3.2 Scope and invariants

1. Account and Session ownership remain strict; no lookup crosses them without a separate authorized workflow.
2. Information inside a Session is discoverable across timepoints. A shared catalog does not authorize arbitrary writes to all timepoints.
3. Every result-producing job binds its target timepoint and exact input revisions at submission.
4. Names, filenames, array labels, and `seed_1`/`needle_1` display indices are never global identities.
5. Direct references name stable IDs and revisions, not the source timepoint's mutable latest object.
6. All geometry has a declared frame and units. The application API contract is physical LPS millimeters; viewer RAS conversion occurs exactly once at its boundary.
7. A guide can deform neither when positioned nor when the anatomy is registered.
8. Display changes never change dose inclusion, implanted status, structure classification, or optimization locks.
9. Accepted implanted observations are immutable optimizer inputs. Corrections create a new observation revision; they are not unrestricted plan drags.
10. One physical seed observed in several scans is counted once in a selected baseline, not once per observation.
11. A source-timepoint change invalidates affected derived results; it does not rewrite an existing manufactured guide or a historical observation.
12. Every dose result records units, grid, calibration, model/source assumptions, and temporal basis.

### 3.3 Shared Agent and scoped legacy support

Retain one Session-level conversation coordinator and tool/capability catalog. Create a `TimepointContext` per request or job and a `ScopedMemoryView` for legacy computational helpers. Calls such as `retrieve('ct_image')` resolve only within that captured context.

Do not implement switching by temporarily replacing global `agent.memory`, `state.ctPath`, or the agent's active timepoint during an asynchronous job. That would race with chat, Monitor, another browser, and late callbacks.

Session memory owns conversation, context accounting, preferences explicitly marked Session-wide, and the timepoint index. Timepoint memory owns clinical arrays, configuration overrides, plan state, current metrics, guide placements, report drafts, and clinical annotations.

API compatibility permits an omitted timepoint only for a legacy single-timepoint Session or an explicitly captured trusted UI request context. Ambiguous multi-timepoint writes fail with a structured target-selection response. The HTTP target selector cannot be a mutable cookie-only global setting.

## 4. UI and Data Tree contracts

### 4.1 Timepoint strip and panels

- Mount one set of INPUT, ANALYSIS, VIEWERS, and REPORT components under the timepoint strip.
- Create one empty preoperative timepoint for a new Session. Existing Sessions migrate to one default preoperative timepoint.
- Add a timepoint through the plus button; stage defaults to preoperative. Changing to intraoperative requires choosing its source preoperative workspace.
- Rename and reorder without changing identity. Stage changes after computations require an impact preview and a new workflow revision; they do not reinterpret existing dose or observed facts in place.
- Remember selected timepoint per browser/user view. A background job on A cannot redirect the user away from B.
- Show compact task, unsaved, interrupted, stale, or review-needed badges; do not put complete event logs on the strip.
- Use the existing modal, keyboard, spacing, typography, and global-language patterns. The display term `Table Viewer` versus `Timepoints` remains a naming decision, not a database identity.
- Passing deterministic input/geometry checks can advance automatically under the approved operating policy. Review only consequential uncertainty or missing prerequisites; do not require one modal confirmation per seed or repeat source selection at every stage.

### 4.2 Image and structure behavior

- INPUT displays `Image`; internal compatibility IDs may remain until safely migrated.
- Each timepoint stores multiple images with one explicit planning reference. Image display selection and planning-reference selection are different actions.
- The standard three MPR views have at most one image background selected, including the valid state where none is shown. The latest upload selects its background only if the upload still owns the active timepoint/view generation.
- Preserve supported window/level, opacity, metadata, dimensions, zoom, slice, export, and context-menu functionality per image. HU-specific controls apply only to compatible CT data.
- Switching an image does not delete, recolor, reclassify, or change the saved visibility of unrelated masks, plans, or annotations.
- An overlay from another image/frame is rendered only through an accepted purpose-appropriate transform. Otherwise explain that it is not registered, retain its intended presentation, and offer registration or separate comparison.
- Structure records own `image_id`; uploaded masks remain staged until classification into CTV/OAR. Uploading a CTV-named file alone is not target selection.
- Preserve source-specific multi-target CTV semantics and use the binary target-union contract for dose/planning.

Recommended current-timepoint tree:

```text
Images
  <uploaded image filename> [planning reference / displayed / modality]
Segmentation
  <source image display name>
    CTV
    OAR
    Guide skin surface
    Uploaded masks
Planning
  Implanted seeds
    Accepted observations
    Review needed
  Observed in-situ needles [if provided]
  Additional plan
    Candidate paths
    Planned needles
    Planned seeds
  Dose
    Existing implanted contribution
    Additional contribution
    Predicted total
  Printed guide placement
Artifacts & Annotations
  <existing structured families, scoped to this timepoint>
```

A Session overview can group these by timepoint. Avoid duplicating the same role simultaneously as both timepoint stage tabs and mandatory nested Preoperative/Intraoperative image containers. That earlier UI variant is not assumed to be required by the latest design.

### 4.3 Implanted-seed reconstruction and vivid presentation

Reconstruct every current accepted or review-needed detection at its actual center. For a supported axis, use the source model's actual capsule dimensions; for an unknown axis, use a direction-neutral point/halo instead of a fictitious oriented capsule. A deposition-line estimate is drawn dashed and labeled as estimated, not as an actual inserted needle.

Proposed role defaults, subject to visual QA:

| Role | Initial color | Redundant encoding |
|---|---|---|
| Accepted implanted seed | Bright cyan `#22D3EE` | `Implanted` label and locked-geometry badge. |
| Additional planned seed | Warm gold `#FBBF24` | `Planned` label and plan-state badge. |
| Review-needed detection | Violet `#C084FC` | Dashed halo and `Review needed` label. |
| Rejected detection | Muted, hidden by default | Available in detection review, excluded by explicit review decision. |

These are proposed distinct category colors, not a claim of tested accessibility. Verify contrast against anatomy and dose maps, including color-vision-deficiency simulation. Do not make dose coloring erase the implanted/planned distinction. Optional stable per-deposition-group colors are a display mode, not proof of needle identity.

- Accepted implanted seeds are visible by default; unresolved detections are visible during reconstruction review.
- Individual and group visibility, opacity, color, focus, and context actions use one presentation executor. Tests must cover single-item behavior, not only Show all/Hide all.
- Use stable object IDs and a canonical presentation registry scoped by Session/timepoint/image/family/object ID; no label-only cross-timepoint fallback.
- Tree colors, capsules, MPR projections, legends, report illustrations, and corresponding annotations agree. User-edited appearance overrides defaults and survives cold restore and late resource loads.
- MPR seed overlays use actual slice/slab intersection, not projection of every seed onto every slice. Cross-timepoint comparisons need accepted spatial correspondence or separate image views.
- Hiding an implanted seed does not remove its contribution from the baseline dose. A proposed removal opens an observation-correction action and invalidates dependent calculations; it cannot imply physical removal from the patient.
- Seed labels are screen-space readable, globally localized, and decluttered. No permanent mesh enlargement to make seeds visible. A transient halo or outline is an explicitly visual effect.
- For inferred deposition lines without observed tips, do not generate needle-tip distance annotations or report skin-entry/tip distances as though known.

## 5. Implanted-seed detection adapter

### 5.1 Supplied model integration

Use the supplied package through a thin versioned adapter; preserve its validated preprocessing and model defaults. Deploy it in an isolated compatible inference environment with hash-checked weights, safe loading, owned output paths, resource/GPU leasing, cross-process device locking, cancellation, and bounded execution. Do not alter the application's existing model environments to satisfy the new adapter.

The adapter records source image hash/grid/modality, model hash, code version, preprocessing, detector parameters, native final labels, exported points, component associations, and completion status. Preserve the native artifact and provide a separate original-reference-grid mask using physical resampling and nearest-neighbor label interpolation.

The final point list can contain split centers or post-filter differences not recoverable from a binary mask alone. Generate center-to-component provenance before component IDs are discarded, or retain sufficient intermediate associations. Do not silently regenerate a different number of centers from the binary mask.

### 5.2 Detection and observation are separate

The observed intraoperative count is not required to equal the original plan count. Preoperative matching is optional and cannot create, remove, snap, or orient current seeds as truth.

Store `detected_count`, `accepted_count`, `review_needed_count`, and `excluded_count` separately. Corrections must have a reason and create a new revision. A successful detector returning zero is different from a failed detector, but zero is not proof of an empty implant when scan coverage or image quality is insufficient.

The user intends the image reconstruction to define the actual baseline, not the preoperative prescription list. A reviewed observation set implements that intent without claiming automatic detection is infallible. Configurable research preview can use unreviewed estimates, visibly labeled; operational acceptance must follow the agreed review policy.

For subsequent scans, associate observations to physical seed identities only with adequate geometric evidence. Preserve unmatched, newly observed, and out-of-FOV identities. Do not concatenate earlier and later center lists. If current dose cannot account for potentially present seeds outside the scan or uncertain associations, report an incomplete baseline and block unsupported total-dose claims.

## 6. Three-dimensional seed-axis reconstruction

### 6.1 Method contract

Implement a replaceable `SeedOrientationProvider` with a proposed interface:

```text
estimate_seed_axes(
  image_ref, original_ct, detections, native_labels,
  component_point_associations, optional_observed_needles,
  optional_accepted_guide_placement, orientation_profile
) -> SeedAxisReconstruction
```

Return each center unchanged unless a separate reviewed center-refinement action is requested. Every axis result includes its method/version, evidence sources, fit diagnostics, ambiguity status, and estimated/observed distinction. A later supplied algorithm replaces the provider without changing baseline, display, persistence, or tool schemas.

### 6.2 Proposed algorithm

1. Read original-resolution CT neighborhoods around detected LPS centers. Use native labels as support, not as permission to substitute voxel coordinates for physical coordinates. Preserve one-to-many split-component associations.
2. Extract candidate seed-core support using a bounded, recorded intensity/local-background method. Exclude obvious neighboring devices or bone when evidence supports exclusion; do not assume every bright voxel belongs to that seed.
3. Fit a weighted three-dimensional covariance/PCA axis in physical millimeters. Use the dominant eigenvector, eigenvalue ratios, extent, sample support, and residuals to assess identifiability. Intensity weighting is an algorithm parameter requiring validation, not a universal truth.
4. Generate plausible deposition-line hypotheses from nearby centers and optional local-axis observations. Use robust 3D multi-line fitting, e.g. bounded RANSAC followed by weighted total least squares, with uncertainty-scaled perpendicular residuals.
5. Assign seeds to hypotheses conservatively. Closely spaced parallel lines, crossing lines, missing seeds, and displaced points require competing hypotheses or an unassigned state; simple connected-component/DBSCAN membership alone is not sufficient.
6. Refine each supported group axis using its inliers, recording group extent, residuals, support count, competing fit score, and optional relation to an accepted actual needle or guide bore.
7. Fuse the local capsule-axis estimate with the deposition-line prior. Prefer strong local evidence if a seed has rotated. Use a well-supported group axis when local geometry is unresolved, but label it `estimated_from_deposition_line`.
8. Leave unresolved axes unknown. Do not substitute the global mean direction or a fixed X/Y/Z direction without a visible, explicit assumption.

For reproducible implementation, a weighted local covariance is computed from physical support points and its principal eigenvector is the candidate local axis. Antipodal local/group axes are compared using `acos(abs(dot(u_local, u_group)))`. If fusion is supported by the evidence, combine unoriented axes through weighted projectors `w_local * u_local*u_local^T + w_group * u_group*u_group^T`, rather than averaging signed vectors that can cancel. Large disagreement triggers a rotated-seed/association diagnostic; it does not force the local axis to agree with the group. Weights and acceptance rules must be recorded and validated.

Two points always define a line, so two-point collinearity is not sufficient evidence of a correctly identified deposition group. A group with too little evidence needs independent local/needle support; a single seed with an identifiable original-image axis can still be used.

The supplied `extract_seeds_and_directions` offers a useful 3D PCA starting point, but its unconditional `[0,0,1]` fallback must not become an accepted estimate. The supplied `cluster_needles_xy_plane` explicitly forces zero Z direction and a global-mean singleton fallback. It is not the universal reconstruction provider for oblique 3D needles.

### 6.3 Axis ambiguity and uncertainty

A capsule's geometric axis is an unoriented line: `u` and `-u` are equivalent geometrically. Store this distinction. A deterministic sign convention is only for serialization; it does not establish needle insertion direction, skin entry, tip, or an asymmetric source's head/tail. Verify whether the CNN/source contract is sign-symmetric before treating the two orientations as interchangeable for dose.

Store diagnostics such as support voxels, covariance eigenvalues, line-fit RMS, association ambiguity, and angle disagreement. Do not call an uncalibrated score a probability or a clinically validated confidence interval. Numeric thresholds belong to a versioned validation profile, not ad hoc constants tuned on the three supplied demos.

Unknown axes remain in the observation set and visible reconstruction. They are not silently dropped from dose to improve apparent coverage or speed. An accepted total-dose result requires adequate directions under the approved source/dose policy; otherwise request review or provide a clearly labeled sensitivity preview rather than an invented precise result.

The straight-line prior guides reconstruction and reduces noise; it does not prove that each seed retains its original needle direction after deposition or migration.

## 7. Dose units, source assumptions, and fixed baseline

### 7.1 Required dose artifact contract

Each artifact carries:

```text
dose_id, timepoint_id, image_id, grid_id, quantity, unit,
component = existing | additional | total,
temporal_basis, source_model_id, source_strength_reference,
calibration_id, model_hash, inference_preprocessing_hash,
observation_revision, plan_revision, created_at, validation_status
```

`quantity` distinguishes absorbed-dose prediction from dose rate; `temporal_basis` distinguishes the agreed integral/reference-time prediction from delivered-to-date or remaining dose. Source/date fields can be explicit unknowns for storage, but unsupported values cannot produce an operationally accepted physical-dose result.

At service/report/export boundaries, absorbed dose is explicitly Gy. Normalized model values, if retained, have a distinct unit and name. Prescribed dose is independent from the model-to-Gy calibration. Never use the prescription as a calibration factor.

### 7.2 Fix the existing intraoperative Gy inconsistency

Audit all consumers before changing aliases. Add or extend the shared dose resolver so `dose_distribution_gy` and any physical-Gy alias contain physical values, while `dose_distribution` is either explicitly typed or retained as a documented normalized compatibility field. Calculate DVH and exports from the same declared physical artifact.

For legacy snapshots, use writer provenance, stored unit/calibration metadata, and corresponding physical/normalized artifacts to establish the interpretation. Do not infer units solely from the numeric magnitude, Session stage, or filename. If the legacy record is ambiguous, retain it as historical/unverified and request a reproducible recomputation; never multiply or divide twice to make it look plausible.

Acceptance includes known normalized-to-Gy examples, baseline-plus-additional addition on matching grids, non-default calibration, unchanged prescription, old snapshot repair, reports, DICOM/NIfTI exports, and a double-scaling negative control.

### 7.3 Continuation input and optimizer invariants

Use a validated, immutable `ContinuationBaseline`:

```text
timepoint/image/grid revisions;
accepted implanted seed centers, axes, dimensions and source assumptions;
baseline dose in the optimizer's explicitly declared units;
complete CTV union and OAR structures;
optional observed in-situ needles;
optional accepted rigid guide placement and realized bore manifest;
configuration, geometry, dose and uncertainty signatures.
```

For every evaluated candidate:

`D_total(x) = D_existing(x) + sum(D_new_seed_i(x))`.

The optimizer starts at the baseline coverage, dose and OAR values, not zero. Reward is evaluated against total dose and marginal benefit. All full-volume evaluation uses the complete target; a deficit map only prioritizes candidates. Existing hot regions remain existing hot regions even when no additional action can fix them.

The baseline must survive rule-stage initialization, rule-stage reconstruction, seed removal/reorientation, RL episode reset, policy warm starts, beam/greedy selection, coverage repair, candidate refill, mode fallback, deadline exit, rollback, preview emission, and final dose recomputation. Subtraction/removal is allowed only for additional seeds. The baseline is counted exactly once.

A proposed shared optimizer boundary accepts `candidate_paths`, `baseline_dose`, `baseline_unit`, `baseline_grid_signature`, `fixed_seed_geometry`, `complete_target_mask`, OAR policy and `path_constraints`. The baseline is a read-only array or protected copy with a signature; the optimizer's working total is initialized from it. Rule and RL results return only additional decisions plus a typed total evaluation. Assert unchanged fixed geometry and baseline signature before commit. Legacy preoperative calls use an explicitly constructed zero baseline, not an implicit reset inside shared helpers.

A zero-addition result can be correct if current coverage/constraints and requested objectives support it. A failed or empty supplemental candidate search must not erase the baseline or publish an empty total plan. Serialize implanted observations and supplemental plan entries in a typed result; do not manufacture a fake trajectory with no points to hold implanted seeds.

### 7.4 Cache identity and model domain

Single-seed dose cache keys include owned Session/timepoint/image content and grid signatures, model/preprocessing/calibration/source contract, seed position/axis/weight, and relevant configuration. Baseline aggregate keys also include the observation revision. Model weights may be shared read-only; clinical maps and mutable state are scoped.

The deployed CNN remains the computational engine. This design does not replace it with TG-43 or Monte Carlo. Independent calculations/phantoms are a validation route, not a claim that the operational engine has changed. CT with implanted metal, large reconstruction artifacts, CBCT intensities, and other source models need domain checks; a valid file or identical array size does not establish supported inference.

## 8. Reusing the manufactured guide and initializing remaining paths

### 8.1 Separate anatomy and guide transformations

Store anatomy registration independently from guide placement. Anatomy may use an accepted rigid/affine/deformable transform for its declared purpose. A manufactured guide uses only a proper rigid transform `p_intra = R p_guide + t`, with `R^T R = I` and `det(R) = +1`.

Create a stable guide-local manufacturing frame. Record its mapping to the original preoperative frame. Apply the accepted intraoperative rigid placement to original vertices and bore axes; do not repeatedly transform already transformed vertices. Directions use `R u`, never a point transform with translation.

Direct image/marker observation is preferable for guide placement. Manual correspondences may initialize/refine the placement. Anatomy-based fitting can propose a rigid pose near the guide footprint, but a deformable field or global body alignment does not prove the printed guide's actual pose. Symmetry, incomplete visibility and fit degeneracy must be assessed.

A same FrameOfReferenceUID or identical NIfTI origin/direction provides coordinate metadata, not proof of stable anatomy or a physical guide placement. The anatomy may have moved inside that frame, and a guide may have shifted independently.

### 8.2 Realized-bore manifest

For each actual manufactured bore, preserve its UUID, kind, guide/design hash, local centerline and unit axis, inner/outer intersections, connected traversable extent, effective radius and clearance, guiding length, manufacturing outcome and source provenance. Preserve candidate-but-skipped bores separately and exclude them from initialization.

Legacy center-only auxiliary manifests may be reconstructable from frozen primary geometry, construction parameters and the exact STL. Such reconstruction is a versioned audit, not a regenerated guide design. A center alone cannot certify a through-hole; ambiguous legacy bores remain ineligible until geometry is checked.

### 8.3 Candidate construction and enforcement

Extend each eligible placed bore into the current intraoperative body/CTV frame. Determine current skin intersection, reachable target intervals, depth limits, observed implant/in-situ needle clearances, OAR traversability, and image coverage. Preserve bore identity on every candidate and every final supplemental needle.

Refinement is constrained to that bore's actual feasible corridor. No free lateral translation or arbitrary axis change is allowed. Short auxiliary bores may permit bounded angulation only if their geometry and validated mechanical profile support it; they are not automatically equivalent to long sleeves.

Consumed/occupied/blocked channels are tracked with reasons. Whether a previously used channel can be used again is an explicit policy depending on current observations and mechanical access; never assume an old group remains an obstacle needle after it has been withdrawn. Prefer capsule/segment geometry over center-only distances for interference.

The generated body has a finite, constrained candidate set. An automatic coverage-repair routine cannot quietly add free-space paths or unmanufactured holes. If guide-constrained continuation is infeasible, return the best valid incomplete result and the reason. Freehand alternatives, if authorized later, are a separate mode and clearly distinguished from guide-compatible recommendations.

No intraoperative guide-reuse stage rewrites the printed STL. Anatomy/plan changes can invalidate the placement or a path without changing the manufactured artifact.

## 9. Denser auxiliary channels with usable mechanical guidance

Increase useful candidate-path coverage when designing a new preoperative guide. Preserve already manufactured guides exactly. A density-profile change affects a newly authorized guide generation, not the stored physical guide used during surgery.

### 9.1 Design strategy

1. Generate a physically distributed candidate set over the usable plate region, with candidate axes derived from accessible target corridors and existing planned directions.
2. Deconflict full cylinder/segment geometry rather than only 2D center distances. Check primary sleeves, other auxiliary channels, boundaries, fixation features, and keep-out regions.
3. Prefer candidates that add reachable target/depth coverage or distinct useful alternate corridors. Nearby redundant holes add manufacturing risk without necessarily adding useful planning capacity.
4. Select a subset under material bridge, edge distance, guiding length, connectivity, print-process, load and clearance constraints. A deterministic staggered or blue-noise-style layout is a candidate approach, not a fixed mandated algorithm.
5. Verify actual final bores after subtraction, morphology, clipping, mesh cleanup and export. A requested bore that became shallow, disconnected, merged, blocked or removed must not be listed as a realized continuation path.
6. Store every considered candidate with an acceptance/rejection reason and every realized bore with its full axis/geometry contract. The actual STL and manifest must agree.

The optimization target is a trade-off between useful path coverage, structural reserve, guidance accuracy, fabrication reliability, and computational size. Maximum requested count is not the objective by itself.

### 9.2 Manufacturing gates

Geometry QA covers actual wall/bridge minima, edge distances, through-hole clearance, sleeve transitions, connected components, self-intersections, mesh closure, channel coalescence and guiding length. Mechanical validation additionally depends on resin/material, layer direction, process, tolerances, sterilization, fixation and representative needle loading.

The current `GUIDE_MINIMUM_WALL_MM = 0.35` is an existing software constraint, not evidence that any density/layout is mechanically sufficient. Do not lower it simply to achieve a hole count, and do not claim clinical printing strength from watertightness alone. Define reviewed density profiles and bench/phantom acceptance before operational release; first compare candidate counts, realized counts, rejected reasons, target access, geometry QA and measured fabrication/guidance behavior.

Retain the existing 5 mm finite-FOV truncation policy unless separately authorized to change it. Any change to frozen guide performance dependencies requires impact review and renewed paired evidence, not a hash-only guard update.

## 10. End-to-end workflow and durable state machine

Recommended job stages:

```text
input_validation
  -> anatomy_ready
  -> detection_ready
  -> observation_review / reconstruction_ready
  -> baseline_dose_ready
  -> guide_pose_review / guide_ready / no_source_guide
  -> candidates_ready
  -> supplemental_plan_ready
  -> total_validation_ready
  -> report_ready [only if requested/authorized]
```

Stages can have `pending`, `running`, `ready`, `review_required`, `blocked`, `failed`, `cancelled`, `interrupted`, or `superseded` status. Evidence and status are distinct: a successful detector can still require review, and a failed supplemental search can leave valid baseline dose available.

Independent tasks may run concurrently only after their required inputs are committed and only under the GPU/resource policy. Guide/anatomy registration can be prepared independently of seed dose when doing so does not compete unsafely for resources. Baseline dose cannot start using provisional seed axes without declaring the preview policy.

Persist phase receipts with job ID, scope, immutable input signature, output artifact/hash, revision, method version, time, and QA/review state. Freeze random seeds and optimizer configuration where repeatability is required. A submitted job never reads the browser's newly selected timepoint as its current input.

No-source-guide handling differs from unverified-guide handling. If the selected source has no guide, use the agreed normal candidate initializer in the intraoperative frame. If a guide exists but is unverified/unusable, do not silently discard the reuse constraint. Expose that condition and await the explicitly permitted alternative mode.

Plan output includes `implanted_observation_ref`, `baseline_dose_ref`, `supplemental_plan`, `additional_dose_ref`, `total_dose_ref`, constrained channel associations, complete-target/OAR metrics, unmet objectives, and evidence status. Planned additions never become implanted facts solely because a plan or report was generated.

## 11. Persistence: schema migration, save, load, archive and recovery

This section is mandatory implementation scope, not optional UI polish.

### 11.1 Logical durable layout

Keep all paths under the existing account-owned Session root. A proposed layout is:

```text
<session-root>/
  session.json                       # catalog/conversation references; projection
  shared/                            # owned shared immutable artifacts
  timepoints/<timepoint-id>/
    inputs/                          # owned image and imported-mask artifacts
    revisions/<revision-id>/         # immutable computation manifests
    artifacts/                       # masks, seeds, dose, guide poses, reports
    presentation.json                # compact per-timepoint UI projection
  registrations/<registration-id>/
  manufactured-guides/<guide-id>/
  staging/<job-id>/                   # uncommitted outputs; not current data
  trash/<deletion-id>/                # retained recoverable references
```

Exact on-disk placement can reuse existing artifact APIs. Identity and ownership must not depend on this directory spelling. Do not expose absolute server paths as client-chosen export destinations.

Use the existing SQLite store for transactional metadata; introduce timepoint/catalog/revision/artifact-reference/job metadata through explicit migrations. Database metadata is the publication authority; filesystem manifests/snapshots are immutable evidence or regenerable projections, not a second independently writable authority. Keep array encoding/decoding and safe-path enforcement; extend them to all timepoint and cross-timepoint references.

### 11.2 Migration from current schema 1

1. Accept and inspect schema 1 through a migration reader; do not merely bump `WORKSPACE_SCHEMA_VERSION` and reject every existing Session.
2. Generate one stable default preoperative timepoint. Move references to the old image, structures, planning configuration/results, report, viewer settings, appearance and clinical annotations into it.
3. Keep conversation/messages, global language, context accounting and genuinely shared preferences at Session scope. Preserve attachment-to-message relationships while assigning artifact timepoint provenance where known.
4. Preserve original IDs as scoped aliases so old annotations, colors, report figures and exports remain resolvable. Do not invent new names/roles from a file basename.
5. Register old root-level array/artifact references before any garbage collection. Reuse valid artifacts instead of duplicating the CT and every dose map.
6. Validate owner/path bounds, critical references, target semantics, units and complete known object mappings. Apply the explicit legacy dose policy in Section 7.2.
7. Publish the migration atomically with an idempotent marker and recoverable original manifest/backup. An interrupted migration repeats safely without creating multiple default timepoints.
8. Preserve a legacy single-timepoint API projection for compatibility, but make its scope explicit. It cannot be an unrestricted alias to whichever timepoint is currently visible in another browser.

Downgrading to an old server after multi-timepoint writes is not a supported live operation. Rollback before new writes can restore the validated old snapshot; rollback after new writes needs a compatible reader or a tested export/migration path. Never run old and new writable servers against the same runtime to simplify migration.

### 11.3 Save and checkpoint transactions

- Separate Session conversation/accounting saves from per-timepoint clinical state and per-timepoint presentation patches.
- A timepoint patch names its expected revision and only modifies that scope. Saving B cannot replace A's report or array registry.
- Session catalog changes use their own compare-and-swap/revision boundary. Avoid forcing every independent clinical array update through an obsolete whole-Session snapshot.
- Generate heavyweight outputs in quota-reserved staging. Flush and atomically publish immutable files, then commit metadata references and a job receipt in the database transaction. On failure, keep the prior current revision intact.
- If publication precedes the metadata commit, a crash can leave an orphan, not a visible partial plan. If metadata is committed, every referenced file must already be published and verified.
- Fsync behavior and atomic-rename assumptions must be checked on the configured local/NAS filesystem; do not claim universal power-loss durability from Python return codes.
- Serialize edits/checkpoints with timepoint locks; acquire ordered locks for multi-timepoint metadata operations. Avoid holding GPU work, image decode or network calls inside database/Session locks.
- Current clinical inputs have immutable revision signatures. Preview/mouse-drag changes never publish clinical artifacts as committed observations.
- Browser `presentation_seq`, timepoint revision and load generation reject late appearance writes. Defaults apply only when no valid saved override exists; an empty restore phase cannot reset saved colors/opacities.

### 11.4 Reference retention and garbage collection

The current active-results-only array pruning must be replaced before multi-timepoint data is enabled.

Compute reachability across all live timepoints, retained plan/observation revisions, Session chat attachments, reports, registrations, manufactured guides, guide placements, recoverable trash, and pinned reader/job revisions. Release artifacts only after their last owned reference and retention period expire.

Sharing immutable artifacts inside one Session uses explicit references/refcounts or a graph collector. Deleting a timepoint cannot remove a guide artifact or original image still referenced by another timepoint. Unreferenced staging cleanup must not race with a job that is still publishing.

### 11.5 Load and hydration

1. Verify authentication, Session ownership and catalog schema; read only lightweight metadata first.
2. Restore shared chat/context accounting and the timepoint strip without loading all CT/mask/dose arrays.
3. Restore the browser's selected timepoint, or a documented default if it was deleted. Background hydration must not change another browser's selection.
4. Stage authoritative presentation records before creating placeholder tree rows or meshes. Mark the target timepoint as loading, not empty.
5. Lazily load the selected timepoint's reference image, requested structures, implanted reconstruction and selected dose. Check owned paths, revisions and critical hashes before calculation or accepted rendering; defer full cold-artifact scans.
6. Create a private candidate scene, restore colors/visibility/opacity/camera/settings, then publish it only if the timepoint and view generation still match.
7. A late response for A can populate A's cache, but cannot paint A over B. Missing/corrupt artifacts are reported as such without wiping known records or marking them clinically empty.
8. Current/stale/review states are restored from dependency signatures. Hydration never reruns detection, registration, dose, planning or guide generation simply to reconstruct the interface.

Scene/GPU caches are bounded and evicted independently of durable state. Switching tabs is not equivalent to flushing the whole Session or compressing its shared conversation.

### 11.6 Restart, cancellation and continuation

Persist committed stage outputs and job input signatures. On server restart, reconcile durable jobs with actual live workers/leases. A previously running stage with no worker becomes interrupted, not completed or permanently running.

Resume from the first missing/invalid committed stage when model/config/input signatures agree. Restart an uncheckpointable optimizer stage from its saved baseline and candidates; do not promise instruction-level GPU/RL resumption without implemented optimizer-state serialization.

Do not automatically resume a clinical planning job on boot without the agreed user/operating policy. Provide an explicit Resume action and explain which stage will be repeated. Cancellation and repeated Resume requests are idempotent; exactly-once current-result publication is enforced even if computation is retried.

A cancelled/superseded job may retain useful immutable historical artifacts, but cannot publish them as current or overwrite a successor. Recovery preserves implanted observations and manufactured guides.

### 11.7 Delete, archive, restore and export

- Preview owned data, bytes, running jobs and outgoing dependencies before deletion.
- Fence/cancel and drain affected workers before moving data to recoverable trash. Restored timepoints retain IDs, appearance and dependency references.
- A referenced preoperative timepoint cannot be silently hard-deleted. Support impact-aware refusal, retained frozen dependency artifacts, or an explicitly confirmed multi-timepoint deletion; do not delete other timepoints merely because their source was removed.
- When deleting the last live timepoint, the recommended UI returns to an empty default preoperative workspace only after successful deletion; the old data remains recoverable according to retention.
- Archive/restore operates on all live referenced timepoints and shared artifacts, not only the visible one. Verify hashes and avoid dangling cross-timepoint links.
- Session exports contain the catalog, all selected timepoints, required dependency closure, transforms, source/model/calibration metadata, shared conversation when selected, and checksums. Single-timepoint export includes sufficient referenced guide/registration facts or explicitly marks omitted dependencies.
- Import validates traversal, archive expansion/size, schema, hashes and ownership. It remaps IDs and references as one graph and verifies patient/Session association; imported IDs cannot address another user's data.
- All artifact creation/exports use the existing quota transaction. Do not duplicate large arrays merely to populate multiple tabs.

## 12. Unified API and natural-language tool contracts

### 12.1 Proposed service boundaries

| Service | Responsibility |
|---|---|
| `SessionCatalogService` | Timepoint metadata, source/episode links, rename/reorder/stage/delete impact. |
| `TimepointContextResolver` | Ownership, stable target selection, revisions, scoped legacy memory adapter. |
| `TimepointArtifactStore` | Transactional references, checkpointing, hydration, reachability, archive/export. |
| `ImplantReconstructionService` | Detection provider, orientation provider, observations/review/corrections. |
| `RegistrationService` | Purpose-specific anatomical transforms and QA. |
| `GuidePlacementService` | Manufactured-guide identity, rigid placement, realized-bore transformation. |
| `ContinuationPlanningService` | Baseline dose, constrained candidates, optimizer integration, evaluation. |
| `TimepointComparisonService` | Comparable read-only summaries and accepted spatial comparisons. |

Names are proposed architectural boundaries, not already implemented modules. Share authoritative executors between UI buttons and chat tools; do not create divergent browser-only mutations.

### 12.2 Tool capabilities

Expose typed operations for workspace create/list/rename/stage/link/delete-impact/delete/restore, image upload/reference/display, structure classify/segment/propagate, implant detect/reconstruct/review/correct, registration/guide pose estimate/review, baseline dose/recompute, supplemental planning/evaluation, compare/report/export, and job status/cancel/resume.

Each tool includes a clear read/mutate/presentation classification, required scope and revisions, prerequisites, permission/confirmation requirements, estimated cost class, supported modalities, and output/receipt schema. Mixed-effect tools are action-sensitive. Capability documentation must explain the actual UI functions, not only list button names.

Scope-aware API routes or headers can extend the current Session addressing. The client supplies timepoint IDs but not ownership credentials or trusted filesystem paths. The server verifies them. Heavy calls return a job ID/status stream; they do not block the chat completion connection for the entire workflow.

The current Intraop route/button becomes a front end to the scoped continuation service. A compatibility adapter cannot retain the count-equality, preoperative-image, or zero-baseline behavior under another name.

### 12.3 Semantic decisions, not keyword whitelists

The Agent sees a compact Session catalog and retrieves evidence on demand. Explicitly named targets outrank the active UI tab. Deictic phrases such as "this scan" use the captured initiating view context; an ambiguous destructive or cross-timepoint mutation prompts for selection.

Authorization binds both action and target scope. A grant to replan B does not authorize regenerating its guide, rewriting A, or including every timepoint. Preserve the existing denial/effect ceiling for requests such as "only", "do not", "compare, don't modify", and "export, don't generate".

Read-only cross-timepoint analysis is permitted within the owned Session but does not imply authorization for registration generation, structure propagation or expensive dose recomputation. Retrieval returns current/stale/unknown status, source revisions and actual units. Do not inject arrays, full meshes or every historic report into the LLM context.

Shared context accounting continues to distinguish actual retained prompt/context size from cumulative per-turn input usage. Adding timepoints does not imply that all their artifact bytes are tokens in the conversation.

Tool receipts state exactly which timepoint and version was read/changed and whether the outcome is current, historical, partial, blocked or waiting for review. Final replies must summarize requested outcomes; a screenshot fallback cannot replace a dose or workflow answer.

## 13. Monitor, annotations, reports and comparison

Monitor event/evidence keys extend the current fences to include timepoint, image/observation revision, baseline-dose signature, plan revision and guide-placement revision. Drag previews remain separate from committed observations/plan changes.

- Feedback explains current implanted contribution, suggested additions, unmet objectives and the evidence for guidance. Do not say a displaced seed was manually dragged unless an actual software edit did that.
- Locate highlighted objects with real world centers, reversible focus and stable IDs. Current visibility/opacity is preserved; no hidden camera/data mutation is used to imply a verified location.
- Switching timepoints never routes another timepoint's Restore/Keep action to the currently displayed plan. Restore applies only to an unimplemented software plan edit, not a physical implant event.
- New image import invalidates dependent evidence by its captured signature; a screenshot from an older scan is retained as historical, not re-captioned as current.
- Reconstructed seed displays are immediate after committed reconstruction; subsequent dose/plan phases show separate running states and advancing elapsed time. Do not hold completed images behind an unnecessary final LLM analysis.

Reports distinguish actual reconstructed centers/axis source from prospective needles/seeds and inherited preoperative references. Accepted printed-guide channel entry coordinates and planned tip-relative distances are reported for additional valid needle geometry. Inferred deposition groups with no observed tip cannot populate those fields by guessing.

Each timepoint has its own report. A Session-level treatment summary optionally references immutable report/observation/plan revisions and lists the sequence of events, comparisons and outstanding questions. Previous plans are not evidence of completed implantation.

Comparisons require the same metric definition, source/time semantics, prescription convention and appropriate anatomy correspondence. A V100 delta is not automatically attributable to a single edit when image, segmentation, baseline or configuration changed. Never add dose grids from two successive observations of the same implant as independent doses. Surface/voxel comparisons require accepted registration; nonspatial tabular comparison can disclose noncomparability without silently creating one.

## 14. Performance and experience

- Restore catalog and shared chat first; stream selected timepoint metadata and scene readiness without hydrating every timepoint.
- Use one mounted UI, bounded image/mesh caches, batched CNN inference, and immutable artifact reuse. Clinical cache identities remain scoped even when model weights are shared.
- Coalesce presentation saves separately from immediate clinical metadata transactions. Avoid full-array checkpoints on every opacity click, tab switch, drag or token event.
- Run orientation reconstruction on bounded ROIs and spatially indexed center neighborhoods. Cap hypothesis search and report ambiguity/time-budget termination; never truncate detections silently for speed.
- Candidate count reduction uses reproducible spatial/coverage-aware selection. Preserve the full realized-bore inventory while clearly recording the optimization subset. An exhausted subset can be expanded within the real guide, not replaced with unmanufactured paths.
- Progress exposes queued/running/review/ready phases, elapsed time, measured stage durations, and cancellation. Show useful partial committed results rather than repetitive chat status cards.
- Warmup and expensive background work are visible/authorized, not a hidden consequence of switching tabs. Respect the existing cross-process GPU lease and LAN/public deployment isolation.
- Quantify p50/p95 restore, switch, detection/orientation, baseline dose, guide placement and continuation times on the target hardware. No measured latency or safety claim is made by this document.

## 15. Implementation map and phased delivery

### 15.1 Existing areas requiring changes

| Area | Primary files/paths |
|---|---|
| Memory and request/execution scope | `agent_runtime/core.py`, `execution_authorization.py`, `execution_scope.py`, `request_parse.py`, `action_plan.py`, `response_contract.py`. |
| Existing intraoperative orchestration | `agent_runtime/chat_workflows.py`, `web/routes/planning_routes.py`, legacy Intraop UI executor. |
| Context resolution/agent lifecycle | `web/server.py`, `web/request_identity.py`, `web/chat_tasks.py`, `web/server_support.py`. |
| Persistence/auth/session lifecycle | `web/workspace_store.py`, `web/routes/session_routes.py`, workspace snapshot and UI bridge endpoints. |
| Input/structure/frame handling | `web/uploaded_mask_service.py`, `web/structure_service.py`, `utils/ctv_targets.py`, data/viewer/planning routes. |
| Dose and optimization | `plans/dose_pre/model_loader.py`, `inference.py`, `evaluation_inputs.py`, `plans/core.py`, `reinforcement.py`, `coverage_repair.py`, `utilizations.py`, `tool_factory/seed_plan/planning_pipeline.py`, `model_support.py`, `tool_factory/dose_eval`. |
| Detection/orientation | `tool_factory/seed_seg`, new thin supplied-model adapter and orientation provider. |
| Guide design/placement | `web/surgical_guide.py`, `plans/guide_geometry.py`, `tool_factory/surgical_guide`, new rigid-placement/bore-manifest services. |
| UI/timepoint/Data Tree | `web/app/index.html`, `brachybot-ui-api.js`, `brachybot-workspace.js`, `brachybot-viewer-volume.js`, `brachybot-viewer-layout.js`, `brachybot-3d-manual.js`. |
| Analysis/annotation/Monitor/report/export | Existing DVH, planning-distance annotation, Monitor, report editor/export/plan-table, data-export and tool/UI documentation modules. |

Audit call sites and state keys, not just these named files. Each legacy `retrieve/store`, global scene access, request header, cache key, saved presentation alias and export path needs an explicit scope decision.

### 15.2 Delivery phases and exit gates

| Phase | Deliverable | Exit gate |
|---|---|---|
| P0 | Approved design decisions, baseline fixtures, risk inventory. | Resolve operational-blocking open items or declare research-only limitations. |
| P1 | Timepoint model/context and schema-1 migration/save/load. | No cross-timepoint writes or data loss; legacy Session restore and interruption tests pass. |
| P2 | Timepoint UI, Data Tree and scoped old tools. | Existing single-timepoint behavior remains correct; scoped chat/UI parity and appearance restore pass. |
| P3 | SeedFinder adapter, 3D axes, vivid reconstruction, corrections. | Physical roundtrip, unmatched/sparse/crossing cases, uncertainty and appearance tests pass; real demo results assessed without treating prior outputs as gold. |
| P4 | Frozen manufactured guide, full bore manifest, rigid placement. | No mesh deformation or hash change; pose/through-bore QC and negative controls pass. |
| P5 | Baseline-aware rule/RL/fallback/repair and unit fix. | Fixed seed baseline survives every branch; interference, total target/OAR evaluation, units and exports agree. |
| P6 | Cross-timepoint Monitor/report/export/recovery/performance. | Multi-tab/browser, late response, crash, delete/archive/restore and end-to-end validation pass. |

Use feature flags and compatibility adapters at coherent boundaries. Do not enable multi-timepoint UI before storage/scoping contracts are ready. Do not enable operational continuation before fixed-baseline and guide-placement gates are met. Clinical commissioning requires the separately agreed physical/clinical validation; a green software suite alone is not that gate.

## 16. Acceptance matrix

The following are meaningful scenario families; fixtures and expected outcomes must be independent of the implementation under test.

| ID | Scenario | Required outcome |
|---|---|---|
| T01 | Open an existing schema-1 Session with CT, masks, plan, annotations and edited colors. | One equivalent preoperative timepoint; no data/appearance loss or automatic recomputation. |
| T02 | Interrupt migration before artifact registration and before metadata publication. | Idempotent recovery; no duplicate default timepoints or pruning of old artifacts. |
| T03 | A and B contain identically named images/seeds/annotations. | IDs, edits, focus, report and dose remain correctly scoped. |
| T04 | A job completes after the user switches to B. | Result stored in A; B's scene/forms/current status unchanged. |
| T05 | Two timepoints checkpoint concurrently. | Both survive; neither overwrites the other's report/results. |
| T06 | Two browser tabs select different timepoints and issue writes. | Captured targets and lease/revision policy govern, not a shared active-tab pointer. |
| T07 | Restore bright implanted colors and opacity before/after late meshes arrive. | Exact saved appearance; per-seed/group controls both work. |
| T08 | Hide an implanted seed. | Display changes only; baseline dose and count inclusion unchanged. |
| T09 | Mark a timepoint intraoperative without a source selection. | Prompt for source; no silent unbound execution. |
| T10 | Rename/reorder source timepoint after intraoperative linking. | Stable reference unchanged. |
| T11 | Observed count differs from the full preoperative plan. | Normal reconstruction; no automatic equality failure or forced matching. |
| T12 | Sparse single seed, two centers, three collinear centers. | Distinct identifiability handling; no fabricated universal axis. |
| T13 | Oblique seed groups under rotated/anisotropic image geometry. | Correct physical 3D axes; no forced zero Z or double RAS/LPS flip. |
| T14 | Close parallel groups, crossing groups and a migrated/rotated seed. | Competing/unassigned states preserved; strong local axis not overwritten by group average. |
| T15 | Touching component exports multiple centers. | Explicit component/point associations; no cloned entire-component axis for both without evidence. |
| T16 | Zero detections in good coverage versus failed/partial scan. | Distinct states; no incomplete scan treated as proven zero implant. |
| T17 | Subsequent scan reobserves the same seeds and adds some. | No double counting; ambiguity/out-of-FOV evidence retained. |
| T18 | Same origin/direction or shared frame UID with moved anatomy/guide. | Metadata alone does not certify registration or guide pose. |
| T19 | Correct rigid guide placement and a deliberately scaled/reflected transform. | Correct pose accepted by checks; nonrigid/improper pose rejected for guide use. |
| T20 | Symmetric or partially visible guide matching has multiple plausible poses. | Ambiguity exposed; no automatic authoritative placement. |
| T21 | Requested auxiliary hole is absent/blocked in final STL. | It is not eligible as an initializer. |
| T22 | Changed anatomy makes an old channel unsafe or unable to reach CTV. | Candidate rejected with reason; guide geometry remains immutable. |
| T23 | Refine/repair proposes a needle outside its bore corridor. | Rejected; no silent freehand substitute. |
| T24 | Nonzero baseline with zero additions, and with known additions. | Baseline retained once; total dose and complete-target/OAR values correct. |
| T25 | RL reset, rule reconstruction, fallback and coverage repair. | Every path retains baseline and fixed-seed locks. |
| T26 | New needle/seed intersects a fixed seed or observed in-situ needle. | Physical interference prevents accepted publication. |
| T27 | Existing dose already violates an objective. | Report immutable existing condition; do not delete seeds or falsely claim repair. |
| T28 | Ambiguous legacy Gy alias and proven normalized legacy record. | Ambiguous historical state flagged; proven conversion occurs once. |
| T29 | Non-default calibration and unchanged Rx; export/reload. | Unit-safe agreement across dose, DVH, report and export. |
| T30 | Correct an observation after baseline/plan/report completion. | New observation revision; dependent current results stale, historical evidence retained. |
| T31 | Crash after file publication but before database commit. | Prior state stays current; orphan reclaimable; no partial accepted result. |
| T32 | Crash after stage commit; Resume is requested twice. | Valid stages reused; stage recompute if needed; one current-result publication. |
| T33 | Delete/restore a timepoint referenced by guide/registration/report. | Impact policy applied; no dangling or unexpectedly deleted dependent artifacts. |
| T34 | Archive/export/import a Session containing several timepoints. | Complete reference graph, scoped IDs, hashes, appearance and provenance preserved. |
| T35 | Failed hydration or late empty UI save. | Clinical metadata and saved appearance not reset to empty/default. |
| T36 | "Only recompute intraoperative dose; do not replan or generate a guide." | Exact effect boundary and target receipt. |
| T37 | "Use the printed guide for remaining paths" while another tab is active. | Named target and frozen guide used; no geometry regeneration. |
| T38 | Compare two scans of the same implant. | Comparable summaries/spatial checks; no accidental dose summation. |
| T39 | "Undo implantation" versus "undo the pending planned needle." | Clarify physical versus software action; no claim to reverse surgery. |
| T40 | Orientation/profile/provider changes after interruption. | Dependent stages recomputed; old cached dose not reused as current. |

Add bounded real-image, phantom/printed-guide, independent direction and dosimetry validation. The supplied three demo outputs alone cannot establish detection, orientation, mechanical or clinical validity. Freeze independently reviewed thresholds before operational release and avoid tuning them to the acceptance set.

## 17. Dependency and invalidation rules

| Change | Invalidate | Preserve |
|---|---|---|
| Image content/grid or planning reference | Affected structures/alignment, observation axes, baseline dose, candidates, plan, current report. | Original input, historical artifacts and manufactured guide. |
| CTV/OAR revision or traversability | Candidate safety, optimization and evaluation/report. | Valid image-based seed observation; single-seed dose if its physical input signature is unchanged. |
| Seed center/axis/source assumption | Baseline aggregate and affected single-seed maps, interference checks, continuation and report. | Prior observation evidence. |
| Guide placement | Transformed channels, candidate geometry, supplemental plan and report. | Frozen STL and anatomy registration unless separately dependent. |
| Manufactured guide selection | Placement/candidates/continuation. | Previously manufactured artifacts and existing implanted baseline. |
| Prescription/constraints | Metrics/objective-dependent plan/report. | Physical dose maps if source/model/calibration inputs are unchanged. |
| Model/calibration/temporal basis | Dose-dependent results and comparisons. | Observed physical positions and manufactured geometry. |
| Color, opacity, visibility, label, camera | Relevant visual output/capture only. | Clinical dose and optimizer baseline. |

Invalidation is a server-owned dependency-graph operation, not a collection of UI keyword callbacks. Never use the absence of a stale badge as proof that dependencies were validated.

## 18. Safeguards and exclusions

- Preserve independent LAN/debug and public-release code/runtime/services. This design does not authorize a restart or public deployment.
- Preserve unrelated working-tree changes, existing model defaults, anatomical label semantics, finite-FOV policy and accepted UI behavior.
- Restrict artifact paths/URLs by account, Session and timepoint; apply quota and request limits to new endpoints. Use opaque IDs, not user-controlled paths.
- Do not send patient images, seed coordinates or case reports to public registration/detection services during development or Agent browsing. Local processing is the default.
- Do not infer radionuclide/source strength, actual implantation date, a needle tip, physical guide placement, or clinical safety from color, filenames, planned positions, or a model success flag.
- Intraoperative mode must not declare a new printed guide necessary merely because the old design's source plan is stale. Evaluate the frozen real guide and current placement/corridors instead.
- A preoperative label selects the unchanged planning workflow, not proof that no implant exists. If the Session already explicitly records implanted material for the chosen image/episode, show the conflict rather than silently running a zero-baseline workflow. Do not launch hidden expensive detection for every preoperative upload.
- Software correction of an observation does not move a physical seed. Software Undo cannot be phrased as reversing implantation.
- Do not claim support for arbitrary tumor sites or modalities simply because the metadata layer accepts them.

## 19. Remaining decisions to freeze

These are the few unresolved choices that affect execution or operational acceptance; already confirmed requirements are not reopened.

| ID | Open decision | Proposed handling pending user confirmation |
|---|---|---|
| O01 | Is the first target same-operation CT research validation, or operational patient-facing use, and are CBCT/reimplantation across days required immediately? | Architect extensibly; validate same-treatment CT first. Preserve explicit research-only limits if clinical gates are not approved. |
| O02 | Must the associated preoperative workspace have a completed source plan, or is an image-only source permitted? | Mandatory association is confirmed. Treat plan availability as a separate prerequisite; do not assume count/geometry equality. User to decide whether image-only association can run without a guide. |
| O03 | What source model, strength/reference date and temporal integral does the existing CNN calibration represent? | Keep the current CNN; audit training/calibration provenance and freeze the unit/time contract before accepted baseline dose. |
| O04 | Are needles still in situ at intermediate scanning, and how are actual axes/bending provided? | Support imported/manual observed-needle records; block unsupported physical-clearance conclusions if needed records are missing. |
| O05 | Is the printed guide reliably visible, what material/markers exist, and who accepts a placement? | Implement direct/manual rigid positioning plus candidate estimation; no unverified anatomy-only automatic acceptance. |
| O06 | What needle/guide clearance, guide material/printing/load profile, orientation uncertainty and registration tolerances are accepted? | Versioned validation profiles and phantom/bench review. No invented clinical or mechanical safety thresholds. |
| O07 | Are freehand alternatives allowed when printed-guide continuation is infeasible? | Resolved by the user's later 2026-10-10 instruction: enable a bounded guide-first/outside-guide second phase after undercoverage, with the reviewed rigid guide as a hard obstacle. Do not treat this as permission to ignore an unplaced guide, move fixed implants, or generate a replacement guide. |
| O08 | Should implanted seeds use category colors or stable different colors for each reconstructed deposition group? | Default vivid implanted-versus-planned category colors; optional per-group mode, with uncertain group identity disclosed. |

If the associated preoperative timepoint has no manufactured guide, skip guide transfer as requested and initialize paths in the intraoperative frame. If the user requires a completed source plan under O02, validate that separately rather than inventing it.

## 20. Source basis and evidence limits

Engineering choices in this draft are proposed designs, not clinical recommendations or demonstrated outcomes. The image-geometry/QA review informed requirements for physical coordinates, uncertainty, failure handling and independent acceptance; it does not establish clinical commissioning.

- [AAPM TG-132: image registration and fusion in radiotherapy](https://aapm.onlinelibrary.wiley.com/doi/full/10.1002/mp.12256): registration quality, purpose-specific validation, uncertainty and commissioning. No patient-specific tolerance is adopted from it here.
- [AAPM TG-43U1 report](https://www.aapm.org/pubs/reports/detail.asp?docid=85): source dosimetry and source-strength framework. This draft does not assert that the CNN implements TG-43 or that its Gy scaling proves temporal/source equivalence.
- [SimpleITK registration overview](https://simpleitk.readthedocs.io/en/master/registrationOverview.html): registration framework and transform mapping convention. The point-push and image-resampling directions must be explicitly adapted.
- [SciPy symmetric eigenproblem documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.eigh.html): a numerical building block for covariance axes, not clinical validation of the orientation estimator.
- [ITKElastix](https://github.com/InsightSoftwareConsortium/ITKElastix), [ANTs](https://github.com/ANTsX/ANTs), [ConvexAdam](https://github.com/multimodallearning/convexAdam), [uniGradICON](https://github.com/uncbiag/uniGradICON): locally deployable registration candidates. Select a rigid baseline and a bounded reference/fast route after domain-specific evaluation; do not install every backend or run them all per patient by default.

No source above guarantees accurate guide placement, robust orientation from thick-slice CT, mechanical strength at a particular wall thickness, or clinical benefit of the planned system. Those require the acceptance evidence described here.

## 21. Deliverable status

Completed in this design delivery: targeted code inspection; interpretation of the user's clarification; vivid implanted reconstruction requirement; proposed orientation/continuation/guide contracts; full persistence/migration/recovery design; implementation map; invalidation rules; acceptance matrix; and explicit unresolved decisions.

Not completed or claimed: product refactoring, the Gy bug patch, orientation implementation, inference integration, denser-guide implementation, registration installation, migration of real Sessions, any benchmark/product test result, patient/GPU runs, or clinical/manufacturing approval.
