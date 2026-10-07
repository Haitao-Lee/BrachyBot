# CTV target-semantics audit and remediation

Date: 2026-10-07 (Asia/Shanghai)

Baseline: `/home/lht/snap/brachyplan/BrachyBot`, commit
`45bdd13f108824311b6a0d8fb267b797299adc55`. The initial checkout was clean.
The independent `BrachyBot-release` checkout and both running services were
outside the mutation scope. No patient data, model weights, clinical targets,
prescription, guide truncation policy, or inference defaults were changed.

## 1. Findings and disposition

| Review claim | Verification | Remediation / qualification |
| --- | --- | --- |
| Nine selector routes resolve to registered engines | Confirmed | Registry/selector tests retained. Reachability does not prove installed assets, successful inference, or clinical applicability. Prostate is a T2-weighted MRI route, not another CT model. |
| GTV label 2 becomes a pancreatic obstacle in direct planning | Confirmed | Direct trajectory/seed context now resolves the effective binary union. Radiation-volume construction accepts explicit semantics; the pancreatic standalone default remains compatible. |
| Manual needle safety interprets nodal GTV as artery | Confirmed | Manual dose/safety and geometry checking resolve the same target union and use separately merged OAR/hard anatomy. Nodal target identity does not suppress a real overlapping OAR obstacle. |
| Dose evaluation omits label 2 while manual DVH includes it | Confirmed | The grid/unit resolver prioritizes `ctv_binary_array` and source-aware legacy projection. Raw explicit dose callers can declare source semantics. Legacy evaluation/optimization handlers now use the same physical-Gy and grid resolver. |
| Data Tree and tumor screenshot identity assume label 1 | Confirmed | Server payload declares target labels; Data Tree, screenshot identities, catalog authority, and cached payloads share target classification. Promoted arbitrary target labels are supported. |
| Site-model semantic strings disagree with registry | Confirmed | Site engines and liver/kidney cascade results emit canonical registry semantics/source identity; the wrapper no longer overwrites these with incompatible provenance. Historical source/semantic aliases remain readable at the compatibility boundary. |
| Site `full_label_array` is a SITK image, unlike other engines | Confirmed | It is now an ndarray, with a separate geometry-bearing `full_label_mask` used for wrapper alignment. This avoids double-orienting an already-LPI array on nonidentity input directions. |
| Pancreatic direct engine lacks source semantics | Confirmed | Direct output includes canonical source, tumor route, binary target and completion metadata. Existing inference, vessel labels, calibration and defaults remain intact. |
| Statistics have different centroid/volume fields | Confirmed schema variation | Wrapper normalizes volume in mm3/cm3 and centroids in array ZYX and physical XYZ using the aligned image; engine-specific extra evidence is preserved. Direct pancreatic statistics also carry ZYX coordinates. |
| All-zero successful predictions imply missing model | Confirmed | Completed empty inference emits `no_tumor_detected`, not a missing-installation diagnosis. It explicitly does not establish absence of disease. Actual engine failures retain their original diagnostics. |
| Pancreatic companion OAR and embedded anatomy can duplicate rows | Reproduced with controlled masks | Only identical masks with the same anatomy name are deduplicated. Same names or partial overlaps do not prove equivalence and are not merged. This is a conditional duplication defect, not a claim that every live case has duplicates. |
| Deprecated BiomedParse site IDs silently migrate | Confirmed compatibility policy | Aliases are retained; results expose requested/resolved route and migration metadata. Existing sessions/tool aliases are not broken. |
| Hidden SAT3D controls are dead code | Not established | Explicit interactive SAT3D routes remain registered. Hidden selector visibility alone does not justify deleting tools or interactive controls. No deletion was performed. |
| Liver/kidney accept known non-CT modality | Confirmed | Registry-based validation runs before model allocation in the wrapper and direct cascade engine. Known modality/phase conflicts are rejected; contrast phase is not guessed from voxel intensities. |

## 2. Repaired contract

`utils/ctv_targets.py` is the shared consumer-side projection boundary:

1. `ctv_full_labels`: original source labels for anatomy/target provenance.
2. `ctv_array` / `ctv_mask`: effective display labels may be label-coded after
   Structure Set classification. Their positive IDs are not globally pancreatic.
3. `ctv_binary_array`: authoritative planning/DVH union, restricted to 0/1.
   It wins over legacy aliases. Invalid numeric labels or mismatched grids fail
   closed instead of silently falling through to another representation.
4. Before a binary companion exists, a registered model's semantics govern
   projection: pancreatic label 1 only; HECKTOR/SegRap labels 1 and 2; a classified
   Structure Set uses the union of all active CTV objects, regardless of label ID.
5. Hard anatomy is a separate OAR/obstacle input. An initialized classified
   Structure Set is not overwritten by stale embedded model sidecars. Known GTV
   target IDs cannot become vessels merely because an old UI row says so.

The frozen legacy needle sampler and `build_needle_safety_context` retain their
existing pancreatic compatibility contract and physical/index mathematics.
Current case paths project to the binary target before entering that sampler.
Raw model-label callers have an explicit source-aware safety builder. This keeps
source interpretation separate from validated physical segment sampling rather
than changing both sides of a frozen performance reference.

All CTV ingestion paths touched by this audit replace the binary companion and
full-label/embedded-anatomy sidecars. New CT loading clears the companion and
semantics. Legacy manual-mask hydration updates it with the explicitly selected
target label. Upload Mask staging and explicit Move to CTV remain unchanged.
Monitor's proposed-seed target-membership gate consumes the same target union.

## 3. Frontend and persistence

`/api/viewer/label_volume` publishes `X-CTV-Target-Labels` after source/effective
structure classification. Explicit catalog classification takes priority over
label names and old state. A label renamed to "artery" remains a target when the
catalog classifies it as CTV; an artery row is not promoted just because its ID
is 2. Both nodal GTV and promoted CTV contribute to tumor screenshot identity.

Label cache format is now v6 and includes target identities. Earlier cache
payloads refresh from the case-owned server once; they are not repaired by
guessing source meaning. Existing visibility, color, opacity, stable object IDs
and presentation restoration remain under their existing owners. Frontend asset
versions are advanced only for the two changed scripts.

## 4. Validation and evidence scope

Validation is detached under
`/tmp/brachybot-ctv-semantics-stage-20261007-0wJqQZ`, with deployed assets located
through `BRACHYBOT_DEPLOY_ROOT=/home/lht/snap/brachyplan`.

- Initial relevant model/structure/planning/safety/dose regression: **107 passed**.
- Source-aware contracts and frozen planning reference plus Chromium identity
  tests: **42 passed** before three additional lifecycle/safety regressions.
- Full suite before final Monitor-membership integration: **2697 passed,
  2 skipped, 31 warnings, 4 subtests passed** in 78.32 seconds.
- Final exact product/test overlay, including Monitor membership and canonical
  cascade output: **2697 passed, 2 skipped, 31 warnings, 4 subtests passed** in
  81.16 seconds. Log: `/tmp/ctv-semantics-delivery-tests-20261007.log`.
- The first broad iteration exposed four planning-reference failures caused by
  interface drift (2690 passed, 2 skipped). The frozen sampler/helpers were then
  preserved byte-for-byte; neither the planning guard nor its baseline manifest
  was relaxed or updated to accept changed behavior.
- Python compilation and both changed JS syntax checks pass.
- Chromium executes the actual product target/screenshot-identity functions
  with synthetic catalogs/payloads. This is not a full live-patient UI smoke.
- The existing Flask viewer test verifies target-identity transport for all
  three GTV routes, both original and restored-source variants.

The two skips require public-deployment dependencies and a real nginx test
binary. Existing SWIG and `datetime.utcnow()` deprecation warnings are reported,
not hidden. No paid provider calls, GPU model inference, real-patient planning,
clinical performance experiment, service restart, commit or push was performed.

The guide's dependency manifest is renewed only with paired evidence at
`docs/benchmarks/surgical_guide_dependency_renewal_2026-10-07-ctv-final.json`:
four fresh-process before/after replays, alternating order, one/four needles,
isotropic/oblique-anisotropic grids and two resolutions. CT inputs, meshes,
needle paths, auxiliary holes, QA and selected-needle counts match. The directly
imported canonical guide helper AST is unchanged. Timings are descriptive
fixture timings, not clinical latency or a significance claim. Older evidence
files remain preserved.

## 5. Activation and existing results

Code delivery alone does not update already-imported Python modules. Safely
restart only the LAN service after active work is quiescent, then refresh the
browser to load new script/cache contracts. The public service is independent.

Affected old plans/dose/report artifacts are not automatically recalculated
by this patch. A previous direct-planning or dose-evaluation result that omitted
nodal GTV must be regenerated and reviewed against the corrected target union.
An old completed result cannot be retrospectively certified from a code fix.

Checked delivery uses a 27-file SHA-256 manifest bound to the clean baseline
commit, with preimage checks and recoverable mode-0700 backups. No shared
dependency guard is disabled. At the pre-delivery check, LAN listener PID
1709933 and public listener PID 1703529 still had their original separate
checkout working directories; these observations are point-in-time, not a
promise that another operator cannot subsequently restart either service.

The current review validates software contracts, not all nine installed model
routes on real patient data, clinical safety, treatment efficacy, or independent
physical dose accuracy. Site-specific contour, prescription and OAR review
requirements remain in force.
