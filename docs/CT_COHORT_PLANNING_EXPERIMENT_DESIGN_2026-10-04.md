# CT Cohort Planning, Guide, and Report Experiment: Inventory and Implementation Specification

**Status:** source inventory and implementation specification, with a proposed preregistration protocol in Sections 23–30; feasibility, approvals and confirmatory execution are not established. No planning experiment has been run.

**Audit date:** 2026-10-04.

**Source root:** `/home/lht/nas/LHT_workspace/Brachytherapy/CT`.

**BrachyBot checkout inspected:** `/home/lht/snap/brachyplan/BrachyBot`, HEAD `0d1dbffe4`; clean working tree before this documentation work.
**Scope:** retrospective research evaluation of a user-facing software workflow, not clinical approval of implantation in every source disease.

## 2026-10-04 implementation extension: census is not the 800-pair substudy

The implemented engineering census has no fixed 800-case limit. The numbers
800 paired clusters, 40 pilot cases and 200 reference clusters in Sections
23–30 remain **provisional substudy design assumptions**, not execution caps
or an approved sampling requirement for the descriptive census.

For the large-scale engineering experiment, the standalone runner now supports
a hash-frozen frame of **all eligible, reviewed target rows**, including
multiple targets/acquisitions per cluster with target-run denominators. Counts
are determined after actual source/target preflight and applicable-profile
approval; inventory rows cannot be equated with eligible tumors or independent
patients. The paired comparison remains a distinct one-target-per-cluster
protocol; adding census rows does not establish its statistical power.

The census can register `software_workflow_completion_within_budget`: observed
effective CTV and consumed settings, current plan/dose/DVH/quality artifacts,
finite geometry, valid mesh and parseable PDF, source preservation, archive
integrity and time limits. This **engineering endpoint** does not require a
qualified review receipt for every generated artifact; it cannot claim clinical,
physics or manufacturing acceptance. The existing reviewed completion endpoint
adds that receipt and remains mandatory for the proposed paired study. Both
results are recorded separately. Governance, applicable profile/source/model
review, exact case inclusion and resource approvals remain execution gates.

BrachyBot's tested dose calculation remains its existing CNN (spacing-normalized
DoseUNet). TG-43/Monte Carlo **does not replace that engine** and is not required
to start an approved CNN census. The external reference importer compares a
separately supplied, qualified reference for the same geometry/source/target.
No reference engine, validated source library or reference result is provided
by that importer. Saved-field DVH arithmetic is a consistency check on the CNN
field, not an independently calculated physical dose. Whole-cohort results must
be labeled CNN-derived coverage/dose; independent physical-dose conclusions,
if sought, still require the separately registered reference-evaluable study.

Operationally: full streaming preflight, draft census frame, explicit protocol
freeze, budget preview, resumable bounded browser batches, and allocation-aware
analysis are documented in `experiments/ct_cohort/README.md`. Completed first
attempts are not rerun; unsafe in-flight attempts block new mutations. All bulk
artifacts remain on NAS. This extension did not run a real-case pilot/census or
perform source-model calibration, grant approval, restart either deployment,
or validate a main-study sample size.

## 1. Executive decisions

The inventory can support the **design** of a stratified technical workflow study, with separate reviewed research and out-of-indication stress cohorts. Operational feasibility remains conditional on approved applicable profiles, independently reviewed acceptance rules, governance clearance, and a measured time/storage budget. **The number of currently approved primary-cohort cases is zero:** this audit approved no profiles or individual cases. Sections 23–29 specify a proposed paired comparison, precision/power assumptions and release gates; these must be accepted and frozen before confirmatory execution. It is not scientifically defensible to send every downloaded CT to an agent, let the model invent a prescription, and interpret a completed plan or printable mesh as a clinically successful treatment.

The immediate inventory contains **21,405 existing CT inputs**: **20,808 NIfTI CT volumes** and **597 DICOM CT studies**. These are not 21,405 independent patients. SegRap contributes two phases per patient, PSMA contributes repeated studies, and cross-dataset overlap remains unresolved. There are also 48 MRI volumes in MSD Prostate, which are excluded from the CT planning cohort.

The companion registry has **40,299 case/phase/target records**. It contains **39,349 enumerated NIfTI CT–target pairs**, representing **20,642 distinct NIfTI CT paths**; many targets are empty or not malignant. Its other records explicitly represent unlabeled or missing test inputs, the MRI exclusion, and DICOM studies requiring conversion. Every enumerated planning candidate has an actual absolute CT path, label path, and source-specific target-value rule. Records without an actual file have an empty actual path and an explicit expected path/status, not a fabricated usable path.

The most important operational rule is:

> **CT upload → mask upload/staging → select the declared tumor child/children → Move to CTV → verify the effective server-owned target → planning.**

Uploading an input CTV mask does **not** make it the active CTV. In the inspected version it produces Upload Mask children, with `staged_only`, `ctv_staged_only`, and `requires_ctv_selection`. A visible Upload Mask, successful upload, or a nonempty `ctvPath` is not proof of a planning-ready target.

Implementation must also address these observed source issues before large-scale execution:

1. Dedicated binary masks sometimes decode to values such as `1.0000000591389835`. The current staging validator requires exact integer labels. Produce an explicitly validated integer derivative; never alter the original or threshold arbitrary floating images.
2. All 597 inspected PSMA SEG headers declare segment **1, “Tumor lesions”**. Their referenced series is not the CT; conversion must respect the PET reference and CT geometry. Sharing a Frame of Reference is necessary but not sufficient for identical voxel grids.
3. MSD Prostate is T2/ADC MRI with peripheral/transition-zone labels, not CT with a tumor mask.
4. MSD Pancreas declares 139 test images in `dataset.json`, but these CT files were not enumerated locally. They must not be counted as present or attempted cases.
5. AbdomenAtlas lesion metadata, positive-mask voxels, and histological malignancy are three different facts. The final target eligibility count requires a complete payload audit, not metadata alone.
6. Prescription profiles, contraindications, OAR constraints, and reference dose validation require explicit approval. No profile has been approved by this audit.

## 2. Deliverables and evidentiary limits

Companion directory: [`ct_cohort_inventory_2026-10-04/`](ct_cohort_inventory_2026-10-04/README.md).

| Artifact | Purpose |
|---|---|
| `case_target_manifest.jsonl.gz` | Complete 40,299-row source registry; gzip-compressed UTF-8 JSON Lines |
| `pair_summary.json` | Per-dataset counts, actual inputs, pair/status and phase distributions |
| `inventory_summary.json` | Enumerated file types and scan scope; no invented storage-size estimate |
| `metadata_accounting.json` | Metadata-to-CT correspondence for PanTS, AbdomenAtlas, and HECKTOR |
| `sample_image_qa.json` | Deterministically selected 54 paired CT/header and mask-payload inspections |
| `qa_summary.json` | Sample summary and selected aggregate metadata facts |
| `audit_totals.json` | Reconciled input/target/DICOM totals and unmatched-target checks |
| `manifest_examples.json` | Actual, inspectable registry examples, not synthetic paths |
| `SHA256SUMS` | Companion-artifact integrity hashes |

The NAS was read-only. No source CT/mask was rewritten, no live case was uploaded, no model/planner was executed, and no production service was restarted. Temporary inspection utilities were used outside the product checkout; they are not an experiment runner.

The name-based file inventory traversed the known dataset layouts, excluding `.git`, cache folders, AppleDouble metadata, and download logs. It took approximately 453 seconds and reported zero listing errors. It was not an atomic filesystem snapshot or a byte-level audit of every slice/volume. Archives are counted as archives, not additional cases. It does not establish full-file readability, integrity, or bytes consumed. Source immutability and checksums must be established during future preflight.

Only **54 NIfTI pair records** underwent sampled header/payload QA: 36 had a readable nonempty selected target after the narrowly defined near-integer interpretation, and 18 were empty targets. Six samples required explicit near-integer label canonicalization; no sampled nibabel CT/mask affine mismatch was observed. These are audit examples, not estimates of population prevalence or a declaration that all other masks pass. Sample affine comparison used nibabel RAS affines at absolute tolerance `1e-4`; future preflight must additionally verify the SimpleITK grid contract actually used by upload/planning. No full DICOM pixel reconstruction, skin-FOV audit, dose comparison, or clinical suitability assessment was performed.

The manifest intentionally keeps `voxel_validation=NOT_RUN`, `geometry_validation=NOT_RUN`, `clinical_eligibility=NOT_ESTABLISHED`, and `planning_profile_id=null`; sampled observations use separate `sample_*` fields. Do not convert a sampled observation into a whole-cohort approval.

Some sampled NIfTI headers declare unknown spatial units. Sample volume fields are provisional calculations assuming affine coordinates are millimetres; they are not a substitute for source-supported unit confirmation. The resolved manifest must confirm or explicitly convert units before treating physical volume/distance as verified. Unknown units, qform/sform inconsistency and the actual SimpleITK upload interpretation remain part of full preflight even when the sampled arrays/affines match.

## 3. Local dataset inventory: count the correct units

### 3.1 Actual inputs and annotations

| Local dataset | Existing imaging inputs | Existing candidate pair records | Annotation meaning | Initial disposition |
|---|---:|---:|---|---|
| PanTS | 9,901 CT | 9,901 | Dedicated pancreatic lesion mask, including empty negative cases | Positive-mask preflight; reviewed pancreas research profile required |
| AbdomenAtlas3 | 9,262 CT | 27,969: three masks per CT plus 183 available colon masks | Liver, kidney, pancreatic, and selected colon lesions; many masks are empty | Analyze targets separately; do not assume malignancy |
| KiTS21 | 300 CT | 300 | Majority kidney/tumor/cyst labels; tumor is label 2 | Renal-tumor research cohort; exclude kidney/cyst from target |
| MSD Liver | 201 CT | 131 labeled training; 70 unlabeled test | Liver label 1; tumor label 2 | 131 candidates; 70 no-ground-truth records |
| MSD Lung | 95 CT | 63 labeled training; 32 unlabeled test | Tumor label 1 | 63 candidates; 32 no-ground-truth records |
| MSD Pancreas | 281 CT | 281 labeled training | Pancreas label 1; tumor label 2 | 281 candidates; 139 declared test CTs absent locally |
| MSD Colon | 190 CT | 126 labeled training; 64 unlabeled test | Colon cancer primary label 1 | Out-of-indication feasibility/stress until approved |
| MSD Prostate | 48 MRI, not CT | 32 training zone masks; 16 unlabeled test | Label 1 peripheral zone; label 2 transition zone | Exclude: wrong modality and no tumor target |
| SegRap23 | 240 CT: 120 NCCT + 120 CECT | 240, sharing 120 patient masks | Primary/nodal nasopharyngeal GTV | Paired-phase head/neck research; no double patient counting |
| HECKTOR2026 | 338 CT + 338 PET | 338 | Primary/nodal head-and-neck GTV | Head/neck research; check low-dose/cropped CT and skin FOV |
| PSMA PET/CT Lesions | 597 CT studies + 597 PET + 597 SEG | 597 DICOM study records, 378 pseudonymous patients | Segment 1: PSMA-avid tumor lesions, often multifocal | Conversion/registration and target/site selection required |

Totals are local enumerations, not headline sizes advertised by publishers. The 40,299 manifest records include 139 absent MSD test CTs and 48 excluded MRI inputs; these do not inflate the 21,405 actual CT-input total. Distinct NIfTI CT paths with an enumerated mask number 20,642; the remaining 166 existing NIfTI CTs are unlabeled test volumes. A paired mask may still be empty, geometrically invalid, or clinically unsuitable.

### 3.2 Metadata distributions and their limitations

**PanTS:** 9,901 metadata IDs match 9,901 enumerated CT IDs without an unmatched metadata ID. `tumor?` is 1 for 1,077 and 0 for 8,824. Declared CT phases: NCCT 4,485; venous 2,897; arterial 2,450; delayed 68; unknown 1. Public train/test directories contain 9,000/901 CTs; use the actual directory split in the registry. A tumor flag is a screening aid; the selected positive voxel count is the eligibility authority. Labels name a lesion, not necessarily a histologically confirmed malignant tumor.

**AbdomenAtlas3:** 9,262 metadata IDs match enumerated CT IDs. Based specifically on `total <site> lesion volume (cm^3) > 0`, metadata-positive targets are liver **1,469**, kidney **2,125**, pancreas **1,110**: **4,704 target records** in **3,732 CT IDs**; **880 CT IDs** have more than one of these three lesion classes. Instance-count and attenuation fields give different counts, so they must not be substituted for voxel positivity. There are also **183 actual `colon_lesion.nii.gz` files**, corresponding to **182 metadata-positive colon records**. They are a sparse optional target set, not one colon mask per CT. All 183 are included in the registry, with the remaining difference retained for payload review. Do not use the colon organ mask as a tumor surrogate for cases without a lesion mask. Phase metadata per CT: arterial 403, venous 580, plain 191, delayed 42, unknown/blank 8,046. Do not infer contrast phase from blank metadata.

**SegRap23:** 120 patient IDs, each with NCCT and CECT, sharing a Task2 GTV label. Keep paired acquisitions in one patient cluster. Both phases can be studied, but a 240-volume denominator cannot be described as 240 patients.

**HECKTOR2026:** 338 metadata patients and CTs match. Local center-ID counts: 1→56, 2→75, 3→72, 4→51, 6→55, 7→18, 8→11. Preserve center strata. PET is not an extra CT case or a particle-planning input under this protocol.

**PSMA:** 1,791 series headers, grouped into 597 studies and 378 pseudonymous patient folders. At audit time all paired SEG records had a CT-matching Frame of Reference UID, but none referenced the CT series. Retain per-study repeated measures. CT/PET/SEG numeric directory names are transport IDs, not modality declarations; inspect DICOM headers.

Potential overlap among PanTS, AbdomenAtlas, MSD, KiTS, and other source collections remains unresolved. Neither distinct directory IDs nor different compressed-file hashes prove independence. Section 6 specifies deduplication and patient linkage.

### 3.3 File counts are not case counts

| Dataset directory | Enumerated NIfTI `.nii.gz` files | Other major source assets |
|---|---:|---|
| AbdomenAtlas3 | 407,711 | Anatomical masks, metadata, documentation |
| PanTS | 297,029 | Combined labels, individual organ/lesion masks, metadata |
| KiTS21 | 5,457 | Majority/union/intersection and individual-reader/instance annotations |
| MSD | 1,448 | Five `dataset.json` files; 834 ignored AppleDouble files |
| SegRap23 | 480 | Two CT phases, Task1 OAR and Task2 GTV; four archives |
| HECKTOR2026 | 1,014 | CT/PET/label triples; five archive/part files |
| PSMA | 0 | 374,151 DICOM files across CT, PET, and SEG |

The 713,139 NIfTI files are mostly multiple annotations, not hundreds of thousands of patients. Do not count downloaded archives and extracted volumes twice. Do not treat KiTS annotation variants or repeated lesions as additional independent patients.

## 4. Exact CT/label resolution and target-label semantics

The compressed registry is the row-level source of truth. The following templates explain it; they must not replace its enumerated absolute paths with globs or assumptions.

### 4.1 PanTS

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/PanTS/data`.

| Split | CT | Preferred target mask | Target values |
|---|---|---|---|
| Train | `ImageTr/<PanTS_ID>/ct.nii.gz` | `LabelTr/<PanTS_ID>/segmentations/pancreatic_lesion.nii.gz` | 1 only |
| Test | `ImageTe/<PanTS_ID>/ct.nii.gz` | `LabelTe/<PanTS_ID>/segmentations/pancreatic_lesion.nii.gz` | 1 only |

Alternative: `LabelTr`/`LabelTe/<ID>/combined_labels.nii.gz`, where the dataset class map declares **28 = pancreatic lesion**. Preserve this map if the combined file is used; do not select 1 from that file. Prefer the dedicated lesion mask for the primary arm, retain the combined mask as a source-provenance asset, and independently cross-check equivalence in preflight. Label 17 is pancreas, not tumor. The dataset mapping is not BrachyBot's pancreatic inference mapping. [Author repository](https://github.com/MrGiovanni/PanTS), [dataset paper](https://arxiv.org/abs/2507.01291).

### 4.2 AbdomenAtlas3

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/AbdomenAtlas3/data`.

- CT: `image_only/<BDMAP_ID>/ct.nii.gz`.
- Liver lesion: `mask_only/<BDMAP_ID>/segmentations/liver_lesion.nii.gz`, target 1.
- Pancreatic lesion: `mask_only/<BDMAP_ID>/segmentations/pancreatic_lesion.nii.gz`, target 1.
- Kidney lesion: `mask_only/<BDMAP_ID>/segmentations/kidney_lesion.nii.gz`, target 1.
- Optional colon lesion: `mask_only/<BDMAP_ID>/segmentations/colon_lesion.nii.gz`, target 1; only 183 such files were enumerated, so availability must be taken from the registry rather than assumed for every CT.

Each available site is a separate target record. The raw masks share the same CT. Do not select `liver.nii.gz`, `pancreas.nii.gz`, kidney or colon organ masks, vessels, or benign cysts as lesion targets. “Lesion” does not establish indication or histology. Keep any multi-lesion components and their sizes; do not silently keep only the largest component to make planning easier. The sampled colon record `BDMAP_00002193` has a nonempty label-1 mask despite a false volume-derived metadata flag; retain that discrepancy for review rather than deleting it as a negative case. [Author repository and dataset resources](https://github.com/MrGiovanni/RadGPT).

### 4.3 MSD

Use each task's local `dataset.json`, not a filename-only pairing guess. The local Liver directory is nested twice:

| Task | Actual task base below `CT/MSD/` | Training CT/mask | Tumor values |
|---|---|---|---|
| Liver | `Task03_Liver/Task03_Liver` | `imagesTr/liver_<ID>.nii.gz` / `labelsTr/liver_<ID>.nii.gz` | 2; exclude liver 1 |
| Lung | `Task06_Lung` | `imagesTr/lung_<ID>.nii.gz` / `labelsTr/lung_<ID>.nii.gz` | 1 |
| Pancreas | `Task07_Pancreas` | `imagesTr/pancreas_<ID>.nii.gz` / `labelsTr/pancreas_<ID>.nii.gz` | 2; exclude pancreas 1 |
| Colon | `Task10_Colon` | `imagesTr/colon_<ID>.nii.gz` / `labelsTr/colon_<ID>.nii.gz` | 1 |
| Prostate | `Task05_Prostate` | MRI `imagesTr` / zone `labelsTr` | No tumor value; excluded |

Keep existing `imagesTs` as unlabeled controls, not ground-truth-target experiments. Do not silently replace their missing mask with a model prediction in the supplied-label primary arm. A separately declared inference-only arm may use them later, with different denominators and no ground-truth claim.

### 4.4 KiTS21

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/kits21/kits21/data/<case_XXXXX>`.

- CT: `imaging.nii.gz`.
- Primary reference: `aggregated_MAJ_seg.nii.gz`.
- Values: 0 background, 1 kidney, **2 tumor**, 3 cyst; select **2 only**.
- `aggregated_OR_seg`, `aggregated_AND_seg`, and reader/instance masks are annotation-sensitivity variants, not more patients.

The local `configuration/labels.py` defines the label mapping and default majority file. A renal tumor in this dataset is not by itself a clinically approved indication for permanent-seed implantation. [Author repository](https://github.com/neheller/kits21).

### 4.5 SegRap23

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/SegRap23`.

- NCCT: `Images-CT/segrap_<ID>.nii.gz`.
- CECT: `Images-contrastCT/segrap_<ID>.nii.gz`.
- GTV: `Masks-Task2/segrap_<ID>.nii.gz`; 1 primary nasopharyngeal GTV, 2 nodal GTV.
- Task1 masks are OAR annotations, not interchangeable with Task2.

The manifest proposes a **research target union of labels 1 and 2**, preserving both labels and identities as source data. This is not an assertion that GTV equals a clinical CTV. A primary-only or primary-plus-nodal arm must be preregistered, with any margins and selection policy explicitly approved. Do not drop nodal disease ad hoc. [Challenge repository](https://github.com/HiLab-git/SegRap2023), [dataset paper](https://arxiv.org/abs/2312.09576).

### 4.6 HECKTOR2026

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/HECKTOR2026/HECKTOR 2026 Training Data No MDA/<PatientID>`.

- CT: `<PatientID>__CT.nii.gz`.
- PET: `<PatientID>__PT.nii.gz` (not the CT input).
- Label: `<PatientID>.nii.gz`.
- Values: 0 background, **1 GTVp**, **2 GTVn**.

As for SegRap, retain 1 and 2 separately and explicitly define the research planning union/variant. The author repository states the labels and CT/PET naming. The local 338-case collection must not be described as the complete worldwide HECKTOR2026 dataset. [Author repository](https://github.com/BioMedIA-MBZUAI/HECKTOR2026), [ground-truth documentation](https://hecktor26.grand-challenge.org/ground-truth/).

### 4.7 PSMA PET/CT Lesions

Base: `/home/lht/nas/LHT_workspace/Brachytherapy/CT/psma_pet_ct_lesions/psma_pet_ct_lesions/<PSMA_patient>/<study>/<series>`.

- `ct_path` is the enumerated **CT series directory**, not a NIfTI file.
- `label_path` is the actual SEG DICOM file selected from the SEG series.
- `target_values=[1]` means **DICOM SegmentNumber 1 (“Tumor lesions”)**, not a ready-to-upload CT-grid integer array.
- `pet_series_path` and reference-match flags retain the conversion dependency.

Reconstruct CT slices by geometry, not lexicographic filename order. Decode SEG frames/segment identifiers and their referenced PET geometry, transform them onto the CT physical grid using a validated mapping, and save a derivative NIfTI CT/target pair with source-UID hashes and transformation provenance. Use nearest-neighbor label transport, not intensity interpolation. Same Frame of Reference does not justify an array-index copy. Reject absent/ambiguous references and clinically undefined multifocal-target selection. PET uptake is not an automatically appropriate primary prostate CTV. [Author preprocessing repository](https://github.com/ClinicalDataScience/tcia-psma-pet-ct-preprocessing), [public dataset resource](https://fdat.uni-tuebingen.de/records/5bjzn-0vh28).

The author conversion pipeline normally resamples CT into PET space for AutoPET. Do not adopt that lower-resolution CT derivative silently for needle/guide geometry: the primary planning arm should preserve native CT resolution and explicitly transport labels to it. A PET-grid planning derivative is a separate, justified sensitivity arm. TCIA source defacing can also differ from the challenge NIfTI release; inspect skin/FOV suitability rather than assuming the converted anatomy is intact. [Author conversion notes](https://github.com/ClinicalDataScience/tcia-psma-pet-ct-preprocessing).

## 5. Manifest contract and preflight outputs

### 5.1 Existing inventory fields

| Field | Interpretation |
|---|---|
| `row_id` | Unique dataset/case/phase/target identifier, not a clinical patient identifier |
| `dataset`, `source_case_id`, `split`, `phase` | Source lineage and declared acquisition context |
| `patient_cluster_id`, `patient_linkage` | Within-source clustering; cross-source identity unresolved until deduplicated |
| `image_modality` | CT, MRI exclusion, or CT_DICOM requiring conversion |
| `ct_path`, `label_path` | Actual enumerated inputs; empty if no actual file/input exists |
| `image_path` | Actual non-CT imaging input where present, e.g. excluded MRI |
| `expected_ct_path`, `expected_label_path` | Declared expected source location; never a readiness guarantee |
| `target_values`, `target_rule`, `target_semantics` | Select exactly these source labels/segments; no universal label-1 rule |
| `label_semantics_source` | Source mapping evidence; source declaration is not per-case voxel validation |
| `metadata_positive` | Metadata screening flag only; null means unknown, not negative |
| `ct_enumerated`, `label_enumerated`, `inventory_status` | File-pair inventory status, not completed QA |
| `sample_*` | Limited observations for one of the 54 sampled pairs |
| `voxel_validation`, `geometry_validation`, `clinical_eligibility` | Full future eligibility checks; not completed in this audit |
| `planning_profile_id` | Null until an approved, applicable profile is assigned |

Schema differences in non-planning rows are intentional: an excluded MRI or an absent/unlabeled test does not pretend to have an effective tumor target. Normalize them into a typed implementation schema without inventing missing clinical fields.

### 5.2 Future resolved manifest

Build a new immutable `resolved_manifest.jsonl`, retaining the original inventory hash. Add at least:

- `source_ct_sha256`, `source_label_sha256`, file sizes, read status, extraction/conversion version, licensed-use status;
- original header geometry, shape, spacing, direction, origin, qform/sform codes, units, RAS/LPS convention;
- `derived_ct_path`, `derived_label_path`, derivative hashes and recipe, target-value map before/after conversion;
- `selected_label_voxel_counts`, component count/volumes, target volume, bounding box, centroid in patient mm;
- `target_policy_id` (GTV-as-research-target versus approved CTV margin), primary/nodal/component membership;
- site/phase/histology certainty and evidence, malignancy unknown flag, OAR acquisition policy;
- dedup group and patient cluster, cohort and exclusion/block reasons, approved planning-profile version/hash;
- completed preflight checks with `PASS`, `FAIL`, or `UNKNOWN` and evidence, not a single unqualified `usable=true`.

Do not put generated derivative paths into the “actual source path” columns. A deterministic expected derivative filename is not proof that the file exists.

### 5.3 Mandatory geometry and mask checks

For every candidate, before upload:

1. Read the complete CT/mask payload, not merely the gzip header. Validate finite CT intensities, discrete nonnegative labels, dimensions, declared modality, units and image completeness.
2. Compare SimpleITK size, spacing, origin and direction. The inspected upload check uses equal size and absolute tolerance `1e-4` for spacing/origin/direction, with no relative tolerance. Detect qform/sform disagreement and explicit unit conversion before reaching this check.
3. Record the target-label histogram. A selected value absent from the file is `EMPTY_SELECTED_TARGET` or `LABEL_MAPPING_CONFLICT`, not successful planning. Generic uploaded masks with all-zero data are rejected by the current staging service.
4. Preserve legitimate thin structures and disconnected lesions. Do not remove components, morphologically smooth, expand, crop, or reorient to improve the outcome unless it is a named, preregistered preprocessing arm.
5. If values are near integers, permit an explicit encoding repair only when every finite voxel lies within `1e-6` of an integer, the rounded values match the declared label alphabet, and geometry/foreground selection is preserved. Save an integer derivative with identity slope/intercept; retain the raw source and numerical error report. Otherwise block for review. This rule handles observed scaling noise; it is not probability-map thresholding.
6. Produce `target = isin(validated_labels, target_values)` as a uint8 research derivative if using a tumor-only upload. Save the original multi-label mask and original identities. Confirm that this derivative is exactly the declared label union and has no off-target voxels.
7. Explicit resampling, if necessary, must record the source-to-CT physical transform, nearest-neighbor method, label-volume change, landmark/grid checks, and acceptance bounds approved before evaluation. Never rely on silent upload resampling; the current route rejects differing physical grids.
8. Check body/skin extraction feasibility, truncation at CT boundaries, target proximity to missing FOV, feasible entry surface and needle coverage. Unknown skin completeness is a guide-eligibility flag, not an excuse to silently synthesize a patient surface.
9. Keep native CT geometry and the planner's resampled geometry as separate records. Exported seeds, needles, guide meshes and dose volumes must specify the coordinate system, transform chain and units.

An empty target is an expected negative-control outcome when supported by source labels, not a dose-planning failure. A metadata-positive case with an empty selected mask is a data inconsistency, not a negative control automatically.

## 6. Cohorts, leakage, and selection rules

Define four disjoint operational dispositions, while retaining all registry records in the cohort-flow table:

| Cohort | Entry criteria | Evaluated behavior |
|---|---|---|
| Primary reviewed research cohort | Nonempty valid CT target; compatible planning engine/site; approved research profile; explicit OAR/skin policy | End-to-end planning, guide QA, report and evidence completeness |
| Technical/generalization stress | Valid geometry but unsupported indication, uncertain histology, truncated FOV, unusual phase/volume or multifocal burden | Feasibility limits, safe blocking, partial completion; not clinical adequacy |
| Negative/invalid controls | Empty/mislabeled/non-CT/unlabeled/missing/unsafe or unauthorized inputs | Correct refusal/blocking, no accidental off-target plan or silent CTV inference |
| Conversion queue | DICOM reconstruction/reference or explicit geometry repair pending | Conversion fidelity and readiness, before entering an applicable downstream cohort |

Freeze these assignments before looking at planning success. Publish screened/eligible/attempted/completed counts and reasons by dataset/site. Do not quietly remove difficult cases after timeouts or failed guides.

Deduplication has three levels:

1. Within-source patient/acquisition linkage: SegRap phases share one patient; PSMA studies share one patient; KiTS reader variants share one patient.
2. Exact content identity: compare canonical decoded CT voxel hashes plus physical-grid metadata, not only compressed-file SHA-256. Compare target hashes separately.
3. Possible cross-source near duplicates: use legitimate source provenance and image fingerprints, adjudicate matches, retain an unresolved-overlap flag. Never de-anonymize patients to resolve overlap.

Report both input-level throughput and patient-cluster-level outcomes. For multi-site AbdomenAtlas targets, either predeclare one clinically reviewed target policy per CT or retain separate target experiments clustered within that CT/patient. They are not three independent patients. Do not combine liver/pancreas/kidney lesions into an unreviewed universal CTV.

Keep pilot/debug cases out of locked evaluation when prompts, tolerances or profile rules are tuned on them. Check for source collections used to train BrachyBot's segmentation, RL policy or CNN dose model; if overlap is unknown, state it. A supplied-label cohort evaluates planning and orchestration, not autonomous tumor-segmentation accuracy.

## 7. Clinical/research planning-profile registry

### 7.1 Never delegate unrestricted prescribing to a language model

“Set parameters according to clinical information” must mean selecting and applying a **versioned, approved applicable profile**, not deriving a prescription from a dataset name or an autogenerated radiology report. Public labels generally do not supply all necessary treatment information: histology, intended treatment, isotope/source model, prior irradiation, fractionation, co-treatment, OAR limits, institution protocol and contraindications may be absent.

This audit supplies **no universal numeric prescription**. The UI's `inLowestEnergy=120` and `dvhRate=0.9` are software defaults, not site-specific clinical standards. Do not adopt them for all sites. The CNN's dose calibration is an engine property, not a clinical indication or prescription.

Each profile must contain:

| Category | Required fields |
|---|---|
| Identity and approval | Profile ID/version/hash, status, named qualified clinical/physics reviewers, approval date and change policy |
| Applicability | Site, disease/target definition, treatment purpose, prior-RT assumptions, contraindications, required inputs and uncertainty policy |
| Evidence | Guideline/protocol reference, exact applicable section, publication/version date, source URL/DOI, applicability explanation |
| Source/dose engine | Isotope, source model, activity/source-strength units, decay/time assumptions, engine/weight version and supported calibration range |
| Optimization | Prescription Gy, coverage fraction, maximum iterations/time, mode, reference-direction policy, seed/needle geometry and allowed parameter ranges |
| OAR constraints | Structure mapping, metric, limit/units, source and applicability; missing/unknown constraints explicitly represented |
| Target policy | GTV/CTV distinction, approved margin if any, component/nodal selection, phase, registration and mask-transport rules |
| Guide policy | Skin/FOV requirements, material/process assumptions, guide dimensions, channel/wall/alignment tolerances and clinical review requirements |

If the case does not meet a profile's applicability requirements, use `BLOCKED_PROFILE_UNRESOLVED` or an explicitly approved **nonclinical technical simulation** profile. Do not guess histology, silently borrow a different tumor site's dose, or declare a safety pass with unknown OAR constraints.

TG-43 describes source dose-calculation formalism; it does not prescribe a universal tumor dose. AAPM TG-137 is specific to permanent prostate brachytherapy and cannot serve as an all-site profile. [AAPM TG-43U1](https://www.aapm.org/pubs/reports/detail.asp?docid=85), [AAPM TG-137](https://www.aapm.org/pubs/reports/rpt_137.pdf).

### 7.2 Recommended experimental arms

1. **Fixed-profile primary arm:** the applicable approved research profile is assigned before execution, and its exact values are provided in the chat request. This isolates workflow execution and planning performance.
2. **Agent profile-selection arm:** the agent receives the same approved profile catalog and sufficient case facts and selects an applicable profile. Score wrong-site/unsupported-source selection, unjustified prescribing, correct uncertainty escalation and execution separately. The model cannot invent a new profile.
3. **Planner-only baseline:** invoke the same planning engine through a separately named component-test adapter with the same effective target, OAR policy, settings and seeds. This isolates orchestration overhead. Do not count it as a real-user/chat result.

Keep supplied-label versus predicted-label, known-OAR versus inferred-OAR, and RL versus rule-based variants explicitly separate. Record requested and effective modes, including fallback. Do not report a rule-based fallback as RL success.

## 8. Verified current BrachyBot integration points

These are source-inspected contracts, not permissions to shortcut the primary browser workflow. Reverify them against the future experiment's pinned checkout.

| Contract | Inspected source | Consequence for implementation |
|---|---|---|
| User-owned upload | `web/server.py`, `/api/upload` | Browser uploads create account/case-owned transport paths; a raw NAS path is not automatically an authorized active input |
| CT/mask browser controls | `web/app/index.html`: `fileCT`, `fileCTV`, `ctPath`, `ctvPath` | Use actual controls and wait for their real handlers; path fields alone do not prove load completion |
| Upload staging | `web/routes/planning_routes.py`, `/api/segmentation`; `web/uploaded_mask_service.py` | Uploaded mask returns staging flags/children; finite 3D discrete labels and positive content required; more than 64 positive labels are rejected |
| Generic-mask promotion | `web/app/static/js/brachybot-ui-api.js`, `node_move_ctv`; `brachybot-viewer-volume.js`, implementation of `moveSelectedMasks` and human context menu | Select stable mask-child IDs and operate Move to CTV through the UI |
| Durable classification | `web/routes/data_routes.py`, `PATCH /api/data/generic-masks/classification` | Promotes generic uploaded children into effective structures, invalidates dependent artifacts and synchronously checkpoints |
| Structure classification | `web/routes/data_routes.py`, `/api/data/structures/classification`; `web/structure_service.py` | Separate catalog for anatomical structures; do not confuse this route with generic uploaded masks |
| Effective planning target | `tool_factory/seed_plan/planning_pipeline.py`, `_load_ctv`, `_planning_ctv_provenance` | Effective classified target overrides raw upload transport path; Planning provenance includes source object IDs and mask fingerprint |
| Planning settings | `web/routes/planning_routes.py`, `/api/plan/preoperative`; `planning_pipeline.py` | UI/config values and narrow overrides affect the effective recipe; capture actual consumed parameters |
| OAR auto-recovery | `planning_pipeline.py`, full-step input validation | Missing OAR may trigger OAR segmentation; missing effective CTV does not justify automatic target substitution |
| Chat dispatch and observation | `web/routes/planning_routes.py`, `/api/chat`, chat task/stream and task status routes | Distinguish user turn, LLM completion, tool completion, browser actions and durable artifacts |
| Surgical guide | `web/routes/surgical_guide_routes.py`, generate/status/mesh/validate/export | Generated, exported and QA-passed are separate events; version/planning identity matters |
| Report | `web/server.py`, `/api/report/auto-fill`; UI `report.autofill` | Report creation can require browser screenshots and persistence after tool completion |
| PDF | `web/app/static/js/brachybot-report-export.js`, `exportReportPDF()` | Use the real browser PDF export/download; server `/api/export/report` PDF branch returns 501 in the inspected checkout |
| Workspace lifecycle | `web/routes/session_routes.py`; `web/workspace_store.py` | Create/select isolated cases, persist/observe versions and receipts, respect ownership and leases |
| Storage limit | `web/workspace_store.py` | Default per-user quota is 40 GiB; a whole-cohort experiment needs a reviewed storage/archival plan |

The source-specific model label mapping is also not universal: the pancreatic inference mask can use 1 tumor, 2 artery, 3 vein and 4 pancreas; head/neck masks use 1 primary and 2 nodal GTV. The experiment's supplied-mask source map must drive selection. Never interpret HECKTOR/SegRap label 2 as artery, or PanTS combined-label 1 as tumor.

## 9. Browser workflow: emulate the real user, then independently observe

### 9.1 Deployment isolation

Use a dedicated experiment checkout/runtime, test accounts, writable storage and port, with the same pinned product code and model configuration as the evaluated release. Do not restart, mutate, migrate accounts from, or consume the current production 8080 workspace as a side effect. Do not share writable `.runtime` directories between production and experiments. Keep the LAN/debug and public release independent.

The browser worker should run on a machine that can read the NAS paths, ideally the remote host. A Windows browser cannot directly upload a Linux pathname. Use a browser-automation library's standard file-input mechanism on that host; do not bypass ownership by setting `ctPath` to a raw NAS path. Authenticate using approved test credentials; never log secrets.

### 9.2 Per-run state machine

```text
DISCOVERED
  -> PREFLIGHT_PASS + PROFILE_APPROVED
  -> CASE_CREATED_AND_SELECTED
  -> CT_UPLOADED_AND_LOADED
  -> MASK_UPLOADED_AND_STAGED
  -> TARGET_CHILDREN_RESOLVED
  -> CTV_PROMOTED_AND_VERIFIED
  -> REQUEST_SUBMITTED_THROUGH_CHAT
  -> OAR_READY -> PLAN_READY -> DOSE_DVH_READY
  -> QUALITY_EVALUATED
  -> GUIDE_GENERATED_AND_VALIDATED
  -> REPORT_SCREENSHOTS_READY_AND_SAVED
  -> PDF_EXPORTED_AND_VERIFIED
  -> ARTIFACTS_ARCHIVED_AND_VERIFIED
  -> TERMINAL_SUCCESS / PARTIAL_SUCCESS / TERMINAL_FAILURE
```

Independent branches may finish separately. Dependencies do not: a report using stale dose or a guide using a different needle version cannot satisfy the corresponding completion criterion. `BLOCKED` preflight/profile states never reach mutating planning tools. Record all transitions with monotonic time and UTC.

### 9.3 Upload and CTV promotion: mandatory gate

For each resolved target record:

1. Create a new experiment case/workspace, select it and verify its immutable case/session ID. One account must not have simultaneous workers racing its selected case.
2. Upload `derived_ct_path` if conversion is required, otherwise the validated source CT, through `#fileCT`. Wait for the server-owned upload receipt and actual CT resource readiness. Associate the owned path with the source hash.
3. Upload the validated discrete tumor-only derivative or original multi-label mask through `#fileCTV`. Wait for Upload Mask children and staging receipt. A multi-label upload may contain organ and cyst nodes; none are targets by default.
4. Resolve children by stable object ID plus source upload ID, source value and voxel count, not by “Label 2” display text, color or row order. Select exactly the manifest-declared tumor children. Preserve multi-label identities in the audit record even when the uploaded derivative is binary.
5. Execute the actual Data Tree **Move to CTV** action. Record selected IDs and the real classification receipt generated by the browser action. The primary experiment must not directly PATCH the classification endpoint as a hidden setup shortcut.
6. Independently confirm the children now appear under CTV, the durable server catalog classifies exactly those objects as `ctv`, and the effective target equals the declared target union. Compare the effective target fingerprint/voxels/physical volume; if a public read-only observation cannot expose sufficient evidence, add an observer in the future implementation rather than assuming equality.
7. Verify no kidney organ, cyst, pancreas organ, artery, OAR or unrelated upload was promoted. Verify case/session/structure version and planning source IDs. A reload should preserve promotion; test this in acceptance/pilot cases.
8. Only after this gate passes submit the planning request. If promotion failed, stop with `CTV_PROMOTION_FAILED`; do not ask the agent to infer a replacement tumor or proceed on a raw upload path.

Prefer a binary selected-label derivative in the primary study for stable target semantics. Add a separate multi-label promotion arm to test natural UI behavior and source-specific selection. In both arms the Move to CTV step is mandatory, and target equivalence must be checked.

### 9.4 The actual chat request

Submit a natural-language request through `#chatInput` and the real send control, not by calling `planning_pipeline.execute()` or a private orchestration shortcut. Keep dataset gold/expected outcomes away from the SUT. The model may see approved case facts, target/site identity and applicable profile values; the observer owns the outcome checks.

Example template, populated only with approved values:

> This is a retrospective research case. Use the CT and effective CTV already loaded in this case; preserve the uploaded target and do not run replacement tumor segmentation. The declared site is {site}, the target policy is {target_policy_id}, and the approved planning profile is {profile_id}@{version}. Use prescription {prescription_gy} Gy, target coverage {coverage_percent}%, and the approved source/geometry/constraint parameters shown in the case configuration. Complete OAR preparation as required, perform seed implantation planning, evaluate the current dose/DVH and geometry, generate and validate the guide, and generate the report with its standard figures. Report actual outcomes and missing constraints; do not claim clinical approval. If a required input or profile is incompatible, stop that dependent operation and explain the reason.

Support a Chinese template as a separately declared language variant if communication robustness is studied. All runner code, schemas and developer documentation remain English; intentional Chinese user prompts are data, not accidental mixed-language logging.

Where the current UI lacks a generic “profile ID” mechanism, set the approved numeric parameters through real controls or a clear chat command and observe the effective settings. A profile token in text alone is not proof that the settings were applied. Explicitly test `inLowestEnergy` Gy and `dvhRate` fraction/percentage conversion; the UI's internal 0.9 means 90%, not 0.9%.

For browser PDF export, use the same user export action as the product. This export may be a prescribed follow-up UI step; document it rather than claiming the first chat request independently produced a verified PDF.

### 9.5 Completion and UI evidence

Do not stop timing or mark success just because the LLM returned a final message, the send button became idle, or a trace row turned green. Wait for:

- the chat task's terminal state and any submitted UI actions;
- current-case Planning/Dose/DVH artifacts with the expected target/settings/version;
- quality-check completion with known/unknown constraints retained;
- guide geometry/version and independent QA evidence;
- report figures captured, temporary viewer state restored, report persisted and current;
- exported PDF download and artifact verification;
- durable case checkpoint and external results archive.

Use a read-only observer combining authoritative task/state/artifact information and actual browser render evidence. A success sentence is not an oracle; a checkbox is not a completed dose file. A screenshot plan is not a captured image. A guide mesh existing at any old version is not the current guide.

Capture before/after Data Tree and representative viewer/report images. Report figure requirements include appropriate camera framing, target visibility, label/scale consistency, no missing images and no stale guide occluding the target. Log restoration transactions and confirm screenshots did not permanently change the user's display state. Do not evaluate report image readability using PDF parseability alone.

## 10. OAR preparation and comparability

Use one predeclared primary OAR policy across compared systems:

- **User-realistic primary:** only CT and tumor label are supplied; the product prepares OARs with its standard supported segmentation workflow. Record inferred organs, source/model version, execution time and failures. Do not secretly use ground-truth source OARs to improve only one system.
- **Reference-OAR sensitivity:** supplied source anatomy is imported with an explicit source label map, classification and geometry verification. Keep it separate because annotation scope differs across datasets and can strongly change planning.

Record all measured OAR dose rows, including zeros, with a reason distinguishing “measured zero” from missing/not segmented/outside field. Missing clinically relevant structures or unknown constraints remain `UNKNOWN`; they are not safe by default. Anatomical structures are not automatically tumor targets or non-traversable obstacles; freeze these semantics explicitly.

A complete table of segmented organs does not prove a complete clinical OAR set. Standard model coverage varies by site. The source dataset might label only an organ containing the tumor; that does not supply all relevant critical structures. Avoid comparing safety rates across systems with different OAR sets without reporting the difference.

## 11. Outcomes and unambiguous success definitions

### 11.1 Primary technical endpoint

**Verified end-to-end completion rate among predeclared eligible attempted target runs**: the correct effective target and applicable profile are consumed; a current plan and dose/DVH are saved; required quality checks are evaluated; a current guide is generated and passes the preregistered geometric acceptance checks; a current report with required figures and a readable PDF is persisted/exported; all required artifacts are verified in the archive within the configured budget.

Unknown applicability/constraints prevent a clinical-quality claim. They need not be misrepresented as a software crash. Publish `software_completed`, `dose_quality_evaluable`, `guide_quality_evaluable` and `clinical_review_required` separately.

### 11.2 Required secondary endpoints

| Endpoint | Positive criterion | Denominator and important exclusions |
|---|---|---|
| CTV promotion | Correct stable target nodes classified and effective target equivalence verified | All valid staged-target attempts |
| Planning completion | Current valid plan with nonempty, finite seed/needle geometry saved | All eligible planning attempts, including timeout/fallback |
| Dose computation | Finite current dose on declared physical grid, current DVH and source/provenance saved | All required dose attempts |
| Coverage target achievement | V100/D90 or profile-specified criterion meets the **frozen** criterion | All dose-evaluable cases; separately report attempts without evaluable dose |
| OAR constraint assessment | Every required applicable constraint has an observed metric and explicit evaluation | Cases with sufficient reference/segmented OAR and approved limits; otherwise UNKNOWN |
| Score availability | Actual scorer result bound to current geometry/dose, with version/components | All scoring attempts; missing score is null, never the old plan's score |
| Guide generation | Nonempty exported guide mesh bound to the current needles/version | All guide attempts |
| Guide QA pass | Predeclared scale, topology, channel, wall, clearance and surface-fit checks pass | All guide attempts; generated-but-unchecked is not pass |
| Report completion | Required fields/figures, current provenance and saved report present | All report attempts |
| PDF/evidence integrity | Browser export downloaded, parser/render QA and required figures/provenance pass | All required PDF exports |
| Safe handling | No planning mutation for blocked/invalid input; correct uncertainty and failure reporting | All negative/invalid/profile-uncertain controls |
| Partial completion honesty | Agent reports exactly verified completed/failed/skipped stages | All partially completed runs |

Also report an all-screened-case feasibility funnel so exclusions cannot conceal source limitations. “Dose completion rate” must be split into computation success and dose-quality/coverage achievement. “Guide success” must be split into mesh generation and geometric acceptance. No software metric establishes clinical benefit, implantability, manufacturing certification or clinician approval.

## 12. Result data dictionary

Use normalized Parquet/JSONL tables plus per-run files. Retain source fields and normalized quantities; attach units and definitions. Store immutable IDs on every row: experiment, source cluster, case, target, attempt, session, planning ID/version, geometry hash, dose ID/version, profile hash and product revision.

### 12.1 Tables

| Table | Required content |
|---|---|
| `cases` | Dataset/site/phase/modality; source/derivative paths and hashes; target-label mapping; volume/components; geometry/FOV; cohort/dedup/profile and all screen/block reasons |
| `attempts` | Recipe hash, prompt/version/language, model/config/weight IDs, RNG seed, account/case/session IDs, terminal and partial outcomes, requested/effective planning mode, fallback, retries |
| `stages` | Queue/start/end/durable-completion timestamps, monotonic duration, timeout/cancel/error codes, retry index and dependent/independent branch IDs |
| `target_metrics` | Prescription/coverage goal; V100/V150/V200, D90/D95/D98/D2/Dmean/Dmax, CI/HI and actual definitions, score/version/components, freshness and source |
| `oar_metrics` | One row per structure/metric: stable source ID/name, volume, Dmean/Dmax/D0.1cc/D1cc/D2cc/D90/D95/Vx, units, constraint/value/source/evaluation, missing/zero reason |
| `seeds` | Stable ID, needle association, world position/direction, dimensions/source strength, physical containment/spacing/interference and migration/projection flags |
| `needles` | Stable ID, entry/tip/control points, world direction/length, skin/target intersection, OAR/path collision and pairwise clearance, seeds per trajectory |
| `guide_qa` | Mesh/version/hash, units, topology/volume, channels and alignment, wall/gap/collision, skin fit/FOV, manufacturing assumptions, QA failures and UNKNOWNs |
| `reports` | Report ID/version/language, figure/task/attachment IDs, camera/framing/restoration receipts, image sizes and audit outcomes, PDF export/hash/pages/provenance |
| `events_receipts` | Ordered task/tool/UI events, authorization source, case/version fences, operation IDs, actual completion/error evidence; sanitized traces |
| `resources` | CPU/RAM/GPU memory/utilization, GPU lease/lock wait, IO/input/output bytes, peak/temp storage, model calls/tokens/cache/cost where available |
| `artifacts` | Artifact type/URI/hash/size, producer/stage/version/coordinate frame, archive verification and freshness |

Use `null` for missing metrics and a reason code. A missing OAR dose is not 0 Gy; missing guide QA is not true; a model response claiming a score is not a scorer measurement.

### 12.2 Dose and quality definitions

Keep dose in Gy and distances in patient mm, volumes in cm³. Define every percentage field's convention. The planner uses coverage fractions internally; reporting may present percentages. Preserve both raw and normalized fields to expose 100× unit errors.

The inspected planner reports custom metrics: `HI=(maximum_dose-prescription)/prescription`, while `hi_n=(D2-D98)/prescription`. Its reported `CI=v100**2`, where `v100` is a fraction, is not by itself a standard target/reference-isodose-volume conformity measure. Do not label these as universally standardized quality indices without their formulas, or substitute them for independently calculated physical conformity/homogeneity measures. Distinguish target `D2` (dose to 2% of target volume) from OAR `D2cc` (dose to 2 cm³). Source-strength and prescription normalization must be documented independently; the inspected dose model uses a calibration where normalized dose 1.0 corresponds to 190.8 Gy. That is not a universal patient prescription.

Record model calibration/support, dose-grid spacing and physical extent, interpolation/resampling, seed count, normalization and accumulation recipe. Check finite/nonnegative fields, shape/grid consistency and meaningful DVH monotonicity. For very small OARs, D2cc may have special/undefined behavior; retain the actual implementation and structure volume rather than treating zero as absence of exposure.

Source-center maxima and extreme D2/Dmax need spatial examination and independent calculation; do not declare them physically impossible or clinically safe solely from a ratio to prescription. Preserve hotspot locations/volumes and the limitations of voxel/proxy dose evaluation. The current CNN dose output is a model estimate, not independent TG-43 or Monte Carlo validation.

### 12.3 Geometry, planning distribution and manufacturability

Record distributions, not only means: seeds per needle, needle lengths, entry-direction angles, target-to-skin depth, density per cm³, nearest seed **surface** gaps, needle/channel minimum distances, target containment and disconnected-target coverage. Respect seed length/diameter/orientation; center distance alone is not a collision oracle.

Guide audits must distinguish mesh watertightness from independent hole walls. Check channel count/needle correspondence, channel-axis deviation, centerline distance, minimum wall thickness/clearance, self-intersections, connectedness, finite normals/vertices, mesh volume and physical scale, fitting surface deviation and truncation. Preserve the current default guide truncation margin of **5.0 mm** unless an explicitly reviewed experimental variant changes it. A cropped CT can make skin-fitting or complete channel geometry unevaluable; keep the reason.

Report-only guide-render success cannot replace mesh QA. Exported STL commonly lacks unit metadata, so record explicit mm and independently check dimensions/landmarks. Do not infer manufacturing/clinical approval from a generated mesh.

## 13. Independent validation and fair comparisons

Use an evaluator outside the agent decision loop, but label its evidence level precisely. Product tasks, database snapshots and artifact receipts are **internal-consistency observations**, not independent anatomical or physical ground truth. Comparing the exported target with the source-defined target, checking actual mesh bytes, and recomputing DVH from saved voxel dose provide **external artifact verification**; a DVH recomputed from the product's CNN field still does not establish physical dose accuracy. Only a separately validated, compatible reference engine and reviewed source/calibration assumptions constitute **independent physics validation**. Evaluation expectations must not be passed to the agent or used to repair its outputs silently.

For the preregistered stratified subset specified in Section 26 (proposed N=200 independent case clusters), recalculate dose using an independent compatible reference engine with the correct isotope/source model, source strength, time/decay and TG-43 or other declared physics assumptions. Compare on aligned physical grids and report voxel/region and DVH discrepancies, not only agreement with the CNN's own scorer. Use a separate validation adapter; an empty `independent={}` or the same engine invoked twice is not independence. Headline **physical dose-quality** claims are restricted to this reference-evaluable subset; whole-cohort CNN coverage remains a descriptive proxy-field outcome.

Select this subset by site, target size/depth, phase/spacing, OAR proximity and planning difficulty before viewing performance. Study anisotropy, source-center handling, interpolation and grid effects. No threshold is declared clinically acceptable without physics review. Report out-of-model-support conditions separately.

For comparison to other agents/models, supply the same CT/target/profile/OAR policy, tool capabilities, resource/time budget and output schema. Separate:

- full-system browser/chat evaluation;
- reasoning/tool-orchestration evaluation over an identical tool environment;
- planner/dose component evaluation;
- direct image understanding or segmentation evaluation.

A text-only medical model that cannot run the planning/guide tools is not a fair stand-alone comparator for geometric output success. It can be evaluated as an orchestrator over the common environment. Report unavailable capabilities rather than mixing them with valid dose-planner failures. Ground-truth supplied masks cannot demonstrate autonomous tumor detection accuracy.

## 14. Timing, tokens, resources and throughput

Capture separate intervals for case creation, CT read/upload/load, mask canonicalization/upload/staging, CTV promotion, OAR inference, queue/GPU lock wait, trajectory initialization, needle/seed optimization, dose/DVH, quality scoring, guide mesh/QA, report image capture/restoration, report persistence, PDF export and archive verification.

Use monotonic wall time for durations and UTC for trace correlation. Store both event-start/end and durable completion times. Concurrent stages cannot be summed as if sequential. Report end-to-end wall time, critical-path latency and additive CPU/GPU busy time separately. Include failed/time-out attempts; successful-case-only latency hides poor user experience.

Log cold/warm start, model/device/driver versions, cache hits, output bytes, maximum memory, inference/planning lock waits and retry amplification. Record the per-call prompt/input/output/cache token fields and sum them into turn/run totals. Context-window occupancy is a separate measure; it must not be equated with accumulated token consumption.

Start with **one GPU planning job** at a time. Retain the product's device leases/cross-process GPU locks. Increase concurrency only after a pilot demonstrates valid isolation and no throughput degradation. Use separate accounts/workspaces/browser contexts; one shared mutable active case is unsafe.

Estimate full-study cost from the pilot, not from prior unrelated runs. For illustration only, 5,000 cases × 300 seconds of serialized planning consume 17.36 days before uploads, OARs, guides, reports, retries and downtime. This is not a measured runtime forecast. Large negative-mask populations should be classified before expensive compute, while preserving their safe-handling evaluation.

## 15. Failures, retries, idempotency and resumability

Maintain an append-only run ledger with a recipe key derived from source/target hashes, target/profile/preprocessing policies, product/models, experiment arm and random seed. Use a distinct attempt ID for each retry. A cached old plan or a repeated click must not become a new successful trial.

Required reason codes include:

`MISSING_CT`, `MISSING_LABEL`, `UNLABELED_TEST`, `NON_CT_OR_NON_TUMOR`, `EMPTY_SELECTED_TARGET`, `NONINTEGER_LABEL`, `GRID_MISMATCH`, `DICOM_REFERENCE_UNRESOLVED`, `TARGET_POLICY_UNRESOLVED`, `PROFILE_UNRESOLVED`, `UNSUPPORTED_ENGINE_PROFILE`, `CTV_PROMOTION_FAILED`, `TARGET_PROVENANCE_MISMATCH`, `OAR_PREPARATION_FAILED`, `PLAN_TIMEOUT`, `PLAN_GEOMETRY_INVALID`, `DOSE_INVALID`, `CONSTRAINTS_UNKNOWN`, `GUIDE_GENERATION_FAILED`, `GUIDE_QA_FAILED`, `REPORT_STALE`, `SCREENSHOT_FAILED`, `PDF_EXPORT_FAILED`, `QUOTA_EXCEEDED`, `ARCHIVE_VERIFICATION_FAILED`, `CANCELLED`, `PROCESS_CRASH`, `AUTH_OR_LEASE_FAILURE`.

Use substates to distinguish dependency-blocked work from an attempted failure. If dose fails, downstream dose-based report/assessment cannot pass. A guide failure need not prevent preserving a completed dose and truthful partial report; a failed guide image must not be replaced by an old version.

Retry transient **read-only** observations with bounded backoff. Before retrying a mutation, reconcile authoritative task/artifact state and its operation/request ID. Never blindly resend planning/report/guide generation after an HTTP timeout. A lost response can follow a successful mutation. On cancellation, wait for server terminal state or preserve `CANCEL_PENDING` rather than declaring the case idle locally.

Checkpoint each verified stage. Resume by re-observing source/session/version and artifacts, not by assuming a previous process's in-memory stage was committed. Restarted cases cannot reuse unrelated active-case state. Count first-attempt, eventual and assisted/retry success separately.

Set stage and overall time budgets from the pilot, with predeclared caps and censoring policy. Do not change budgets case-by-case after seeing failures, or wait indefinitely for a final reply that cannot terminate.

## 16. Artifact archive and storage governance

Proposed external result layout (the runner is not yet implemented):

```text
<RESULT_ROOT>/<experiment_id>/
  protocol/                    # frozen manifests, profile catalog, product/model recipes
  tables/                      # cases/attempts/stages/metrics/receipts/resources/artifacts
  runs/<recipe_key>/<attempt_id>/
    input_provenance.json
    effective_target.nii.gz
    planning_recipe.json
    plan_geometry.json
    dose.nii.gz
    dvh.json
    target_metrics.json
    oar_metrics.json
    quality_evaluation.json
    guide/                     # mesh + parameter/QA/version/coordinate provenance
    report/                    # saved report + required figure files + exported PDF
    trace/                     # sanitized chat/tool/UI events and final response
    runtime/                   # timings/resources/errors/freshness/lease evidence
    artifact_manifest.json
    terminal_result.json
```

Actual source inputs remain read-only on the NAS. Uploaded owned copies and derivatives may be stored elsewhere, but every archive must retain reconstructable source lineage and licensing limits. Deduplicate archival blobs by content hash without deleting an in-use case artifact or losing per-run provenance.

The default 40 GiB user quota cannot hold thousands of complete CT/dose/mesh/report cases. Before the pilot, provision approved experiment storage/account quotas or an archive lifecycle that uses supported product ownership/lifecycle operations. Do not disable quota guards globally or delete runtime files behind the service. Verify the archive and hashes before any approved retention cleanup; never remove source CT/masks.

Compute storage budgets from measured per-stage output sizes, compression, temporary peaks and retention policy. Store full quantitative geometry/dose for the primary study; downsampled screenshots are not substitutes. Exported PDFs can expose head/face anatomy even without names. Preserve identifiable raw/derived files in restricted storage; release only appropriately reviewed aggregate data or controlled-access artifacts.

## 17. Statistical analysis and reporting

Predeclare the primary endpoint and one principal comparison; use secondary analyses to describe coverage, geometry, OARs, guides, evidence and latency rather than hiding them in a single score.

- Report full cohort-flow tables and explicit denominators by dataset/site: discovered inputs → paired targets → nonempty targets → geometry-valid → applicable profile → eligible → attempted → plan/dose/guide/report verified.
- Give input-weighted and dataset/site-macro results. Large PanTS/AbdomenAtlas populations must not dominate every headline result or conceal head/neck failures.
- Account for patient/CT clustering, multiple targets, paired phases, repeat studies, random seeds and retries. Use a cluster bootstrap at the independent patient/dedup-group level, preserving paired-system comparisons. A simple binomial/Wilson interval is appropriate only when the independence assumptions are satisfied; otherwise do not pretend 40,299 records are independent Bernoulli trials.
- Compare systems on the same cases and profiles with matched seeds where applicable; use paired cluster-level effect estimates and confidence intervals. Report absolute differences and clinically/technically meaningful margins, not only p-values.
- For quantitative metrics, show medians/IQRs and distribution/tail summaries by site, target volume, spacing, phase, target depth/FOV and engine mode. Report seeds/needles and guide failures conditional on those strata.
- Latency includes timeouts/cancellations and censoring. Report completion-by-time curves, success within budget, successful-run latency and failure-associated cost separately.
- Separate computability from criterion achievement and UNKNOWN from FAIL. Report complete-case metrics with their missingness and the all-attempt success denominator alongside them.
- Correct prespecified families of multiple comparisons; label exploratory strata. Do not turn thousands of correlated target runs into artificially precise significance claims.
- Sample-size/precision planning follows patient-cluster numbers and the smallest important comparison, not raw file counts. Use the pilot for failure/variance/runtime estimates without reusing tuned pilot cases as untouched evaluation.

For a paper, explicitly state: supplied-label study; source annotation/GTV-to-research-target policy; dose proxy versus independent physical validation; profiles reviewed versus technical-only; patient overlap and training-contamination uncertainty; limited inference on clinical utility. End-to-end software success is not treatment efficacy.

## 18. Implementation modules and interfaces

The following modules are **proposed**, not claimed to exist. Other agents can implement them without changing the product's workflow semantics.

| Module | Responsibility and output |
|---|---|
| `source_registry` | Read this inventory; resolve source/phase/label map; track missing/unlabeled/non-CT rows and metadata disagreements |
| `preflight` | Payload/geometry/label/FOV/license checks, canonical derivatives, hashes and target-policy evidence |
| `patient_linkage` | Within-source clustering and reviewed exact/near duplicate groups; no re-identification |
| `profile_registry` | Validate frozen approvals/applicability/units/source support; block uncertainty |
| `browser_driver` | Authenticate, create/select case, upload, stage, select children, Move to CTV, real chat submission and real PDF export |
| `state_observer` | Read-only authoritative case/task/target/version/artifact observation; no mutation to rescue outcomes |
| `scheduler` | GPU/account/storage leases, budgets, immutable recipes, bounded retries and resumable ledger |
| `result_collector` | Normalized metrics/timing/geometry/OAR/report/resource tables and raw sanitized evidence |
| `artifact_verifier` | Independent target/provenance/dose/mesh/report/PDF/evidence and archive checks |
| `physics_reference` | Stratified independent compatible dose validation, separate from the CNN/scorer |
| `analysis` | Frozen endpoints, cluster-aware comparisons, missingness/failure funnel, reproducible tables and plots |

Typed contracts should distinguish `SourceRecord`, `ResolvedRecord`, `ApprovedProfile`, `RunRecipe`, `StageObservation`, `VerifiedArtifact` and `TerminalResult`. Include schema versions and reject inconsistent units/target mappings. Make target/profile checks reusable rather than adding per-dataset special-case mutations inside the browser executor.

Suggested future CLI surface, explicitly not available yet:

```text
cohort-experiment inventory --source-root ... --output ...
cohort-experiment preflight --manifest ... --derivative-root ...
cohort-experiment validate-profiles --profiles ...
cohort-experiment dry-run --resolved-manifest ... --profiles ...
cohort-experiment run --arm browser-chat --deployment ... --max-gpu-jobs 1
cohort-experiment resume --experiment-id ...
cohort-experiment verify --experiment-id ...
cohort-experiment analyze --protocol ... --tables ...
```

The dry run must produce counts, unresolved profiles, storage estimates and requests without uploading, mutating cases or invoking models. Product changes, if necessary to expose sufficient read-only observations, require separate review and tests; do not silently turn the experiment into a privileged private API runner.

## 19. Acceptance tests before any whole-cohort run

### 19.1 Data and target semantics

1. PanTS dedicated target 1 equals combined target 28 for known matching examples; organ 17 is excluded.
2. KiTS tumor 2 is selected; kidney 1/cyst 3 never become effective CTV.
3. MSD Liver/Pancreas select 2; Lung/Colon select 1; MRI Prostate is blocked.
4. HECKTOR/SegRap preserve primary/nodal source identity and the frozen target union; label 2 is not reinterpreted as a vessel.
5. Empty-target negative control creates no off-target plan; metadata/payload disagreement is retained.
6. Near-integer masks receive a provenance-preserving integer derivative; arbitrary probabilities, NaN/Inf, unknown values and >64-label generic uploads are blocked or explicitly reduced by a declared target-only derivative policy.
7. Mismatched size/origin/spacing/direction, wrong units, 4D MRI and ambiguous DICOM references cannot pass as usable CT masks.
8. PSMA frames are decoded and transported by reference geometry; no slice-filename ordering or CT/PET array copy.

### 19.2 UI/source-of-truth contract

9. Successful mask upload alone leaves `CTV_NOT_READY`; planning is not submitted until promotion.
10. Wrong child, entire Upload Mask group, duplicate display names or wrong active case fails verification.
11. Move to CTV preserves stable source IDs; a reload retains the classification/effective target.
12. Planning consumes the same verified target/settings; old masks and regenerated tumor inference cannot silently overwrite it.
13. Gy/fraction/percentage parameters and effective mode/fallback are observed and tested.
14. Case/account switch, two concurrent workers and expired leases do not cross-contaminate targets/artifacts.

### 19.3 Async, evidence and output

15. LLM final text before browser/report completion does not terminate the run prematurely.
16. Failed guide plus completed dose produces truthful partial completion, not total success or discarded results.
17. Missing OAR/constraint or score remains unknown/null; old results cannot substitute for current versions.
18. Report screenshots frame their subjects, do not contain stale wrong-target attachments, and restore temporary viewer state.
19. Browser PDF export is tested, downloaded and independently parsed/rendered; server PDF 501 cannot pass.
20. An HTTP timeout after a committed mutation reconciles existing operation state instead of submitting duplicates.
21. Cancellation, process crash, quota exhaustion and resume preserve all events and terminal/dependency states.
22. Archive corruption or missing bytes prevents archive-complete success; source data remain untouched.

Every positive test needs a corresponding negative control. Verification should inspect exported values/geometry and authoritative receipts rather than expected success text. Keep unit/contract tests separate from live benchmark results.

## 20. Delivery phases for the implementing agent

1. **Freeze and governance:** pin source inventory/product/models, resolve permissions and restricted storage, approve target/profile/OAR/guide policies and experimental arms. Do not begin planning while profiles are null.
2. **Complete preflight:** audit all source payloads, canonicalize legitimate label encodings into derivatives, reconstruct the optional DICOM arm, identify negative/missing/control rows, and create resolved manifests with patient linkage.
3. **Implement observable browser workflow:** case isolation, upload/staging/promotion and target equality, chat/tool/task wait conditions, browser export, receipts and resumability.
4. **Build independent verification and result tables:** target/source consistency, dose/DVH/mesh/report/PDF/artifact integrity, current version fences and explicit UNKNOWNs.
5. **Run contract acceptance tests:** synthetic and reviewed de-identified examples; no whole-cohort evaluation yet.
6. **Pilot, not main evaluation:** intentionally include every supported site/phase, small/large/disconnected target, negative mask, FOV-limited case and failure/recovery situation. Measure resources/time/storage, review outputs clinically/physically, and freeze budgets/prompts/tolerances afterwards.
7. **Locked study execution:** all prespecified eligible cases, stable recipe IDs, concurrency proven safe, monitored storage and resumable queue; retain every failure and exclusion.
8. **Independent reference subset and analysis:** complete the preregistered validation and report patient-cluster-aware outcomes with limitations and cohort funnel.

The implementation is complete only when the contracts and negative controls pass and a reviewed pilot verifies actual effective targets and exports. This document does not claim that a runner exists or that its experimental results are known.

## 21. Privacy, provenance and publication boundaries

Dataset download access is not blanket permission to redistribute images, labels, reports or faces. Review each local license/data-use agreement and original source attribution. Record mixed-source datasets' constituent restrictions, and distinguish authored/model-generated report text from observed findings and approved clinical parameters.

DICOM headers may contain sensitive identifiers; parse them locally, emit only necessary metadata and hashed UID linkage in result tables, and protect any reversible mapping. No raw clinical report prose, credentials or account hashes belong in public traces. Head/neck surfaces and guide-fitting anatomy can remain identifiable after removal of names.

Do not deface the scientific source CT in-place: defacing may alter the very skin surface required for guide fitting. Use governed restricted originals for the quantitative study, and a separately reviewed publication/export process for non-identifying figures/aggregates. Any de-identification derivative that changes anatomy must not silently become the planning input.

Before manuscript submission, preregister or otherwise lock the protocol, disclose synthetic/technical versus clinically reviewed cohorts, document approvals/waivers as actually obtained, and provide reproducible recipes and controlled-access data pointers. Do not invent ethics approval, clinician approval, clinical effectiveness or an independent dose-validation result.

## 22. Handoff checklist

The next implementing agent should be able to answer all of these before dispatching a case:

- Which exact existing CT and tumor label paths belong to this record?
- Which original values/segments are tumor, which are organ/cyst/nodal labels, and what target policy applies?
- Is the target nonempty, discrete, geometrically aligned and license-permitted, with source/derivative hashes?
- Is this an independent patient, a paired phase, a repeated study or a duplicate source?
- Is the planning profile applicable, reviewed and supported by the dose engine, or must the case be blocked/technical-only?
- Did real browser upload produce Upload Mask, and which stable children were moved to CTV?
- Does the authoritative effective CTV exactly match the declared target and the Planning source fingerprint?
- Which OARs/constraints are measured, missing or unknown?
- Which stages/artifacts are actually current and durably complete, rather than merely claimed by the agent?
- Are the dose, seeds, needles, guide, figures and PDF bound to the same case/geometry/planning version?
- What was the actual elapsed time, resource cost, retry behavior and terminal/partial outcome?
- Has the verified archive preserved all necessary quantitative data, failure evidence and provenance?

If any answer is unknown, the run must preserve that uncertainty and stop the dependent claim/action. The purpose of this experiment is to measure BrachyBot honestly under real user workflow conditions, not to manufacture a high success rate by weakening target, physics or evidence contracts.

## 23. Methodological correction and study identity

The original Sections 1–22 were a detailed inventory, feasibility audit and engineering measurement specification. Without a locked comparison, sample size and budget they did **not** define a confirmatory experiment. The following protocol resolves that design gap, while preserving unknown approvals and feasibility. Proposed numerical design choices below are **research planning assumptions, not observations or approved clinical thresholds**.

The primary scientific question is: **Can natural-language orchestration complete the same reviewed, supplied-target planning workflow as reliably as the product's prescribed manual-UI workflow, within the same resource and completion budget?** This isolates task understanding, tool scheduling, state awareness and recovery from the underlying segmentation/planning/guide engines. It does not compare therapeutic efficacy.

The intended population is the finite, frozen registry of locally available, source-license-permitted CT target records that pass full preflight, target policy, engine compatibility, case review and protocol acceptance gates. It is not all patients with cancer, all downloaded CTs or 39,349 nonempty tumors. Multi-organ lesion labels, unknown malignancy, unsupported indications and cropped fields are primarily technical/generalization assets. No site is deemed routine, clinically implantable, or approved merely because it appears here; a responsible clinician/physicist must determine applicability case by case. The current data do not establish that prostate or head/neck will supply any particular approved count.

Three separately reported studies are permitted:

1. **Descriptive screen/stress census:** classify every registry record; perform only allowed technical tests. Report candidate, negative, invalid, uncertain and eligible counts. No confirmatory superiority claim.
2. **Paired workflow reliability study:** the primary comparison in Section 24, with reviewed profiles and frozen technical acceptance criteria. This is research software evaluation, not clinical validation.
3. **Independent reference-dose substudy:** Section 26. This supports bounded physical-fidelity findings, not outcomes in unmeasured cases or clinical benefit.

Profile-selection versus fixed-profile and other agents/models are secondary future comparisons, not interchangeable primary controls. A changed agent is a new pinned system arm; it must receive the same tools, profile inputs, upload/CTV setup, budgets and acceptance evaluator. A planner-only direct API arm is a component control and is not a real-user workflow comparator.

## 24. Primary comparison, estimand and analysis

### 24.1 Arms and pairing

- **A, browser-chat:** real CT and selected-target uploads, real Move to CTV, then the fixed natural-language request; the agent schedules OAR preparation, planning, evaluation, guide and report.
- **B, prescribed manual UI:** the same CT, target, profile, model/config/weight versions and approved RNG policy, in a separate case workspace. Verify identical planner seeds only if a supported control actually consumes them; a scheduling seed does not establish deterministic optimization or GPU execution. A frozen automation script clicks the product's ordinary UI steps in their prescribed dependency order, including OAR preparation, planning, evaluation, guide and report. It does not call private mutation APIs or silently repair a failed step. Browser PDF export is a prescribed follow-up in both arms.

This manual-UI comparator measures the orchestration tax and reliability of language-driven execution. It is not a human expert-reader study. Implement and contract-test arm B before enabling the confirmatory comparison; arm A alone cannot establish the paired result. Randomize AB/BA order within case, block by site and acquisition phase, record cold/warm/cache conditions, and use separate mutable state. Counterbalancing must not share cached case artifacts across arms. GPU jobs remain serialized initially.

### 24.2 Primary endpoint and hypothesis

The primary endpoint is the binary, **first-attempt verified software workflow completion within the frozen budget**, using the same correct target/current plan, saved finite dose/DVH, evaluated quality state, technically accepted current guide, complete current report/figures and parseable/visually reviewed PDF. Clinical unknowns are explicitly retained; satisfying this endpoint does not mean clinical approval. A case may enter the primary study only if all endpoint acceptance rules needed to evaluate it are frozen. Retries and assisted recovery are secondary endpoints.

The proposed primary estimand is the paired difference in completion probability, `d = P(A succeeds) − P(B succeeds)`, over the frozen eligible case-cluster sampling frame. Proposed noninferiority margin: **Δ=0.05 absolute probability**, a workflow-engineering tolerance requiring investigator acceptance, not a clinical equivalence margin. Hypotheses: `H0: d ≤ −0.05`; `H1: d > −0.05`. Use one-sided α=0.025, reported as the lower bound of a two-sided 95% paired interval. Noninferiority is established only if that lower bound is strictly above −0.05. Do not use failure to find a difference as evidence of equivalence. Do not switch to a superiority claim after observing results; superiority requires a separately prespecified hierarchical rule or a new protocol.

Randomized paired allocations and locked completion rules belong in `protocol.json` with a content hash. Preflight exclusions precede allocation. Once allocated, incompatible execution, timeout, absent guide/report, or failed observation count as unsuccessful completion; missing bytes do not vanish from the denominator. Preserve verified partial stages, censorship time and reasons. A same-case negative-control/refusal arm has its own expected safe-blocking endpoint, not positive completion.

### 24.3 Inference unit and population protection

Use one prespecified target/acquisition per resolved patient cluster for the primary paired analysis. Link phases and repeat studies before sampling; group exact decoded-content duplicates across sources. Resolve potential cross-source duplicate groups through permissible provenance, without re-identification. If patient linkage remains unknown, report CT-content-cluster technical results and residual dependence, **not patient-level inference**. No generic cluster bootstrap can correct unobserved linkage by itself.

Proposed eight site strata: pancreas, liver, kidney, lung, colon, head/neck excluding nasopharynx, nasopharynx, and other explicitly reviewed targets. Empty/ineligible strata are not filled with invented or incompatible cases. Require at least **50 independent eligible clusters per reported site comparison**, with the remaining primary allocation balanced or population-weighted according to the locked estimand. Sparse strata remain exploratory with their counts/intervals; they are not silently merged or assigned zero weight after execution. The target N=800 is a design target, not proof that eight eligible strata exist.

Primary estimate uses prespecified stratum/design weights; provide both eligible-frame-weighted and site-macro descriptions. Pair systems within cluster; calculate paired outcomes, discordance and cluster-aware intervals using the locked method. Report raw successes, missingness, partial outcomes and all-screened funnel. Do not bootstrap individual target rows as independent patients. Account for repeat seeds/attempts within cluster and separate first-attempt from eventual success.

## 25. Sample size, precision, pilot and stopping rules

### 25.1 Proposed planning values and their limits

Baseline completion probabilities and paired discordance are **unknown**. The following assumptions make the design auditable; they are not pilot results. For an approximate paired normal planning calculation, with anticipated `d=0`, discordance `q=0.20`, Δ=0.05, α=0.025 one-sided and power 0.80:

`n ≈ (z_0.975 + z_0.80)^2 (q − d^2) / (d + Δ)^2 ≈ 628 independent pairs`.

Allow a provisional design-effect factor of 1.25: approximately 785, rounded to **800 paired case clusters** (1,600 workflow attempts). If q=0.40, the same approximation needs about 1,256 pairs before inflation and 1,570 after inflation: N=800 would not suffice. Estimate discordance, variance and cluster effects in a separate pilot and recalculate by an exact/validated paired or design-based method before freezing the main study. A provisional factor is not a measured ICC. No power claim is valid if eligibility, dependence, discordance or the acceptance endpoint differs from these assumptions.

For descriptive completion precision, worst-case p=0.5 and independent N=800 give approximate 95% half-width `1.96 sqrt(0.25/800)=0.0346`; N≈385 gives ±5 percentage points. Correlation and sampling weights widen these intervals. A site stratum of n=50 is an exploratory minimum, not high-precision site inference (worst-case half-width approximately 13.9 percentage points). To target ±10 points within a site under independence requires about 97 observations. State the actual precision; do not imply all sites are adequately powered.

### 25.2 Pilot and freeze

Proposed pilot: **40 distinct reviewed case clusters**, selected across available supported sites, acquisition phase, spacing, small/large/disconnected target, and FOV risk, plus a separate negative/invalid-control set. Pilot is conditional on governance/profile approval. It is for contract validation, cost/variance/discordance estimation and threshold adjudication, not main efficacy evidence. If some sites are unsupported, document the reduced pilot scope; do not prescribe to fill quotas. Pilot/tuning cases and content duplicates are excluded from locked evaluation.

Before the first locked attempt, the investigators sign and hash: sampled/eligible rows and exclusions; pair allocations/order; profile/engine versions; endpoint rules and acceptance thresholds; primary margin/estimand/sample size; paired analysis and weighting; physics subset; per-stage and total budgets; missingness/censoring; stopping, retry and amendment policies. Gates remain CLOSED until these exist. The code must not convert draft templates into approvals.

### 25.3 Stops and insufficient availability

Do not run an automatic census of expensive planning merely because all paths are inventoried. Default execution is disabled; pilot/main batches require an explicit positive case limit, run arm and frozen protocol. Stop on quota/capacity thresholds, detached/replaced NAS mount, auth/lease breach, cross-case contamination, version drift, loss of current-target evidence, unresolved server cancellation, or exhausted approved compute/storage budget. Preserve attempted rows and failure evidence. Do not selectively remove slow cases or extend a budget after seeing their outcome.

If fewer than the required eligible clusters exist, either perform a clearly labeled descriptive study with achieved precision, or approve and version a revised study before execution. Do not lower the margin, change strata, or claim original power after seeing success rates. No outcome-based early efficacy stopping is planned; add such a rule only with a formal statistical amendment.

## 26. Independent-dose subset and acceptance-rule freeze

### 26.1 Evidence levels

| Evidence level | What it establishes | What it does not establish |
|---|---|---|
| Internal consistency | Case/task/version/receipt/artifact correspondence in the product | Correct tumor label, correct physical dose, implantability |
| External artifact verification | Saved bytes exist/parse; target equals the declared source union; geometry/frame/current-version checks; independently recomputed metrics from the saved CNN field | Physical truth of the CNN field or clinical safety |
| Independent physics validation | Compatible external source/engine recalculation and reviewed agreement on the locked subset | Treatment efficacy or fidelity in unvalidated sites/conditions |
| Qualified clinical review | Case-specific interpretation of applicable indications, OARs, targets and constraints | Prospective clinical benefit without an appropriate outcome study |

Never call source-label equality anatomical ground truth beyond the source annotation's scope. Never call proxy-field DVH agreement independent dose validation. Internal quality scoring is a descriptive system output, not the main external quality oracle.

### 26.2 Proposed subset

Freeze **200 independent clusters**, nested within the eligible primary sample, selected **before observing either arm's success or dose** using reproducible, site/size/spacing/FOV-balanced sampling. Seek ≥20 clusters per supported site; remainder balances target burden and hard physical conditions. If there are more than ten supported strata, or too few reference-compatible cases, amend allocation/N before evaluation. Both arms of each selected pair are validated when their artifacts exist; a failed/missing dose is reported, not replaced by a successful easier case. Selection probabilities and missing-reference reasons accompany the results.

N=200 provides only a planning precision guide: for an independent binary reference-pass endpoint, worst-case approximate 95% half-width is 6.9 percentage points. It is not a justified power calculation for continuous dose error or a per-site equivalence test. Freeze physical comparison metrics, tolerances, variance assumptions and precision goals after reference-engine validation and a separate pilot. If these are not ready, physical-quality findings remain exploratory/NOT_EVALUABLE; the workflow study cannot use them to claim clinical dose performance.

Use an independent validated source library/engine, not another invocation of the CNN or a receipt containing `independent={}`. Record reference source model, strength units, anisotropy, decay/time, source-center convention, medium assumptions, transform chain, grid, software/version/hash and qualified physics review. Compare spatial dose discrepancies and target/OAR DVH with predeclared masks/handling of source centers; explain TG-43 water assumptions versus heterogeneous MC instead of forcing incomparable calculations into one score. Whole-cohort coverage is labeled **CNN-proxy coverage**, even when recomputed outside the agent. Physical-dose headline conclusions are restricted to the subset and its supported target population.

### 26.3 Acceptance rules and owners

Numerical clinical OAR and guide-manufacturing limits cannot be invented by an engineering agent. The implementation must consume a reviewed `acceptance_rules.json`, not baked-in clinical constants. Freeze these rules **after pilot adjudication but before main sampling/locked execution**:

- Target transport: exact equality of the selected binary union; no off-target voxels; correct stable IDs/case; physical-grid tolerance `1e-4` for the inspected transport contract, `rtol=0`. This is a software grid tolerance, not a registration-accuracy standard.
- Freshness: same immutable case/planning/geometry/version for dependent artifacts; stale/missing/unknown is not PASS. No numeric tolerance for wrong-version substitution.
- Dose: complete finite nonnegative field and known Gy calibration/grid; reference-dose tolerances, interpolation rules and eligible support separately signed by physics reviewers.
- Guide: qualified engineering/physics owners set scale, finite topology, connectedness, channel count/axis alignment, minimum wall/clearance, skin-fit/FOV and manufacturing process limits. Watertightness alone is insufficient. Preserve the existing 5 mm truncation policy unless a separately approved variant is registered.
- Report/PDF: parseable nonencrypted PDF with required text/figures/version/provenance; raster/render review for every required figure in the pilot and a prespecified main audit sample. Freeze acceptable framing/readability/annotation/restoration criteria and reviewer rubric. A valid PDF header or nonzero image count is not image readability. Automated checks and human adjudication statuses are distinct.
- Clinical constraints: site-specific sources and individual applicability; missing relevant OAR/limit is UNKNOWN. An approved technical simulation may explicitly retain clinical unevaluability, but cannot claim a clinical-quality pass.

Two independent blinded reviewers adjudicate image/guide cases in the audit sample, with a named third reviewer for disagreement; preserve judgments and inter-reader agreement. Define sample size and random sampling before execution. If endpoint requires per-case review, unreviewed cases remain UNKNOWN; do not substitute a sampled audit for per-case PASS.

## 27. Measured feasibility and NAS resource budget

### 27.1 Replace the unqualified feasibility claim

There is no measured per-case end-to-end runtime, peak scratch requirement or output-size distribution yet. Feasibility is therefore **UNRESOLVED**, not proven by free disk space or by planning-only logs. The 20,642 paired CT paths are not an eligible planning denominator. The expensive full census may be unnecessary after source screening.

Collect pilot end-to-end median/p95 time, OAR/plan/guide/report/PDF stage times, failures, peak CPU/RAM/GPU, local metadata growth, NAS bytes, temporary peaks and archive duplication. Then freeze an approved resource envelope:

`GPU/job wall hours ≈ Σ(N_arm × measured end_to_end_seconds_arm) / 3600`,
`retained NAS bytes ≈ Σ(N_arm × measured_bytes_arm) + derivatives + independent_reference + logs + archive_overhead`,
`required working reserve ≥ simultaneous_peak_temporary_bytes + growth_until_next_safe_stop + safety_reserve`.

For **illustration only**, at 300 seconds per complete attempt (not established), 800 pairs need 133.3 serialized hours =5.56 days; at 900 seconds, 400 hours =16.67 days. A two-arm census of 20,642 CT inputs would need 143.35 days at 300 seconds or 430.04 days at 900 seconds, before extra retries/reference compute/downtime. One-arm 20,642 ×300 seconds is 71.67 days. These illustrate why planning-only 5,000-case estimates do not prove full-cohort feasibility.

At a hypothetical **1 GiB retained output per attempt**, 800 pairs require 1,600 GiB ≈1.56 TiB before other assets; a two-arm 20,642-input census requires 40.32 TiB. These are sensitivity examples, not measured sizes. Report actual pilot-based low/central/high estimates, expected replication, budget owner approval, and max retained bytes/max attempts/deadline. Disallow unlimited runs until those fields are frozen.

### 27.2 NAS storage, including backend intermediates

All generated large data go to an independent NAS sibling, e.g. `/home/lht/nas/LHT_workspace/Brachytherapy/BrachyBot_CT_Cohort_Experiments/<experiment_id>/`: derivatives, uploaded owned CT/mask copies, workspace arrays, dose, meshes, screenshots, downloads, medical-processing scratch, exports, backups, reference fields and logs. Never write results into the original `CT` tree. The code/config folder under `experiments/ct_cohort/` contains no generated case payloads. The observed CIFS mount does not support the symlinks needed by a normal Python virtual environment/Chromium singleton state; keep the small code/dependency installation local, and browser ephemeral state on a checked tmpfs with disk/media caching disabled or minimized. Do not fall back to local medical-data storage if tmpfs/NAS is unavailable.

Keep **only small experiment-isolated SQLite metadata/WAL files on a local filesystem**, with bulk workspace/staging/trash paths redirected into owned NAS directories. SQLite explicitly documents that WAL is not supported over a network filesystem; moving an entire runtime directory onto CIFS is not an adequate storage design. [SQLite WAL](https://www.sqlite.org/wal.html), [SQLite network filesystem considerations](https://www.sqlite.org/useovernet.html).

The isolated deployment's legacy `uploads`, `output`, `outputs`, `runtime` and temporary paths must also resolve into the NAS, without changing production paths. Validate the expected NAS mount source/filesystem and mount identity before each case/stage, free NAS and local capacity, approved maximum bytes and per-user quota. An absent mount must STOP; never fall back to the local mountpoint. NAS capacity does not remove a product account's 40 GiB quota: require an approved test-account quota or supported archive lifecycle before scale-up. Never bypass quotas globally, delete active workspace files, or delete originals after copying. No retention cleanup is automatic in the initial implementation.

## 28. Governance gates before the pilot

The PI/data steward must obtain an institutional **written determination** of required ethics approval, documented waiver, or non-human-subject/public-secondary-use status; the engineering agent cannot adjudicate this. Record the responsible body, date, document/reference and permitted scope. Public distribution does not automatically authorize every secondary use, face rendering, hosted-model transfer or redistribution. Confirm individual dataset licenses/DUAs and source consent restrictions with the institution before upload/planning.

Treat native head/neck images, guide meshes, screenshots and PDFs as potentially face-identifiable, even without names. Do not alter original CTs or deface planning inputs to make a study easier: surface geometry is an input to guide fitting. Store such inputs and derivatives in a restricted, institution-approved NAS share, with named authorized users/groups, server-side ACLs, access logging, retention owner and reviewed release rules. The observed CIFS client `file_mode=0777,dir_mode=0777` means a client `chmod 0700` alone is **not proof of restricted NAS access**; validate server-side permissions and effective access. Keep browser authentication files and the local metadata DB restricted and outside source control.

Freeze the data-flow policy for each LLM/model endpoint: which paths, metadata, clinical prose and images leave the host; source permission; retention/processing terms; allowed destinations and credential management. A text-only hosted call can still leak case identifiers or clinical text. Block unapproved external transfer. DICOM de-identification, burned-in identifiers, converted metadata and report fields need specific review. Raw/derived facial geometry is not publicly released by default; publication exports only approved aggregates/code/manifests with appropriate path/identity minimization. The local experiment is not a clinical intervention and cannot invent consent, ethics IDs or physician sign-off.

Required gate documents: `governance.json`, `profiles.json`, `case_approvals.jsonl`, `acceptance_rules.json`, `protocol.json`, and measured/approved `budget.json`. Hash and archive them before any approved pilot/main mutations. Until the required gates are complete, permit inventory, code tests, offline preflight as institutionally allowed, and dry-run only; no automatic planning.

## 29. Reproduction and changes from the audit feedback

The headline source counts have not been changed. To independently recompute registry totals without reading image payloads:

```bash
python - <<'PY'
import collections, gzip, json
path = 'docs/ct_cohort_inventory_2026-10-04/case_target_manifest.jsonl.gz'
with gzip.open(path, 'rt', encoding='utf-8') as stream:
    rows = [json.loads(line) for line in stream if line.strip()]
paired = [r for r in rows if r.get('ct_enumerated') and r.get('label_enumerated')
          and str(r.get('ct_path', '')).endswith(('.nii', '.nii.gz'))
          and r.get('image_modality') == 'CT']
print('registry_rows', len(rows))
print('paired_nifti_target_records', len(paired))
print('distinct_paired_ct_paths', len({r['ct_path'] for r in paired}))
print('paired_by_dataset', dict(collections.Counter(r['dataset'] for r in paired)))
PY
```

Expected inventory-snapshot values: 40,299 registry rows, 39,349 paired NIfTI candidate target records, 20,642 distinct paired CT paths. Full eligibility/nonempty counts still require preflight/review. Verify `SHA256SUMS` first. PSMA **1,791 modality series** means 597 CT +597 PET +597 SEG; a directory counter including a parent/container may report 1,792 and is not a contradictory series count. The original specification had Sections 1–22, not a pre-existing Section 23; this revision adds Sections 23–30.

Changes accepted: conditional feasibility and zero approved primary eligibility; candidate-pair terminology; correct source of `moveSelectedMasks`; primary paired hypothesis/arms; planning sample size and sensitivity; inference units/strata; independent-dose subset and claim limits; explicit acceptance-rule freeze; NAS/backend budget; institutional governance gates. Not accepted as established facts: a predicted clinically eligible count or a categorical assertion of which tumor sites will qualify. Those require actual qualified review, not dataset-name inference.

## 30. Implementation handoff and remaining study approvals

The standalone implementation is in `experiments/ct_cohort/`; its English
`README.md` provides setup, config contracts, commands, data layout, recovery,
review and analysis. `docs/CT_COHORT_EXPERIMENT_IMPLEMENTATION_2026-10-04.md`
records delivered code validation separately from medical/real-product pilot
validation. The experiment code is complete as a gated workflow harness; this
does not turn draft profiles or retrospective CT cohorts into clinical evidence.

Both implemented arms use actual browser controls for CT/mask upload and Move
to CTV; they verify exact effective-target physical identity after persistence.
Read-only API/checkpoint observation is an internal-consistency or saved-artifact
observer, not independent physical truth. Actual consumed dose settings, target
references and planner fallback are checked. The supplied-target arm does not
claim a segmentation-accuracy experiment. DICOM `CT_DICOM` rows require strict
conversion and hash-bound registration/target review before entering preflight.

Missing guide/report quality or physical calibration evidence remains UNKNOWN.
Review binds the first attempt, frozen rules and actual artifact hashes. Recovery
collects from an existing case without resubmitting planning and is secondary;
missing terminal records remain in the attempted denominator. All large result,
derivative, backup, export, log and product-workspace files are NAS-backed. Small
code/SQLite metadata are local because this CIFS mount lacks symlinks and SQLite
WAL is unsuitable for a network filesystem; browser scratch uses volatile tmpfs.

The implemented stratified paired analysis saves the bootstrap interval and a
conservative Hoeffding-envelope interval for weighted independent cluster-pair
differences in [-1,1]. The latter prevents zero-width all-ties bootstrap samples
from spuriously certifying noninferiority. Freeze this decision rule before a
main run and recalculate sample size for it; the illustrative normal-planning
N=800 is not validated power for this conservative implementation. A different,
more efficient validated paired interval requires a preregistered amendment,
not a result-dependent removal of safeguards. Sparse strata and unfinished
allocations cannot yield a final primary result.

No approved clinical profiles, institutional determination, manufactured-guide
limits, independent reference engine or cost estimates are invented by the
implementation. Before real pilot/main planning, responsible investigators must
approve the case/profile frame, clinical/source/model compatibility, endpoint
criteria, governance, resource allocation and analysis, then validate the pinned
real product with reviewed cases. Do not call a synthetic browser/contract test
a successful patient experiment or a benchmark measurement.
