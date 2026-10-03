# CTV Tumor Segmentation Unified Category Design (tumor_segmentation)

Date: 2026-09-17
Scope: internal testing tree `<workspace>/BrachyBot` (release tree sync is a separate round)
Status: Approved, awaiting user review of the spec before entering the implementation plan

## 1. Background

The current six-site tumor segmentation is implemented by three mutually distinct mechanisms (engine, scheduling, label semantics, directory conventions, and frontend presentation are all inconsistent):

| Site | Route id | Model | Weight location | Engine | Output labels | GPU scheduling |
|---|---|---|---|---|---|---|
| Pancreas | `nnunet_pancreatic` | nnUNet v2 Dataset005_Pancreas (3d_fullres, 7 classes) | `BrachyBot/VoCo/pancreatic_tumor/Dataset005_Pancreas/...` | in-process nnUNet | 1 tumor / 2 artery / 3 vein / 4 pancreas / 5-6 unknown | DeviceManager, **no cross-process lock** |
| Liver | `nnunet_liver_tumor` | two-stage cascade stage1_liver→stage2_tumor (5 folds) | `prostate_lesion_seg/trained_models/liver_cancer_seg` | subprocess `cascade_infer_v2.py` | 1 tumor | lease + gpu_lock |
| Kidney | `nnunet_kidney_tumor` | two-stage cascade stage1_kidney→stage2_tumor (5 folds) | `kidney_tumor_seg/trained_models/kidney_cancer_seg` | subprocess `cascade_infer_kidney.py` | 1 tumor | lease + gpu_lock |
| Head and neck | `nnunet_head_neck_gtv` | HECKTOR Dataset510_CT (nnUNetTrainerMax500, best fold1) | `headneck_tumor_seg/data/nnUNet_results/Dataset510_HECKTOR_CT/.../best_model` | subprocess `infer_headneck.py` | 1 GTVp / 2 GTVn | lease + gpu_lock |
| Nasopharynx non-contrast | `nnunet_nasopharynx_ncct` | Dataset508_SegRapGTVnc (best fold3) | `nasopharynx_tumor_seg/trained_models/nasopharynx_cancer_seg_ncct` | subprocess `infer_nasopharynx.py` | 1 GTVnx / 2 GTVnd | lease + gpu_lock |
| Nasopharynx contrast-enhanced | `nnunet_nasopharynx_cect` | Dataset511_SegRapGTVce (best fold3) | `nasopharynx_tumor_seg/trained_models/nasopharynx_cancer_seg_cect` | subprocess `infer_nasopharynx.py` | 1 GTVnx / 2 GTVnd | lease + gpu_lock |
| Lung | `vista3d_lung_tumor` | VISTA-3D foundation model (MONAI/VISTA3D-HF, class 23, not fine-tuned) | `lung_tumor_seg/trained_models/vista3d_lung/vista3d_pretrained_model/model.safetensors` | subprocess `infer_lung_vista.py` | 1 lung tumor (binary) | lease + gpu_lock |

The same category also includes colon `biomedparse_colon_primary` and prostate `biomedparse_prostate_lesion` (BiomedParse v2 text prompts), plus the SAT3D research route that is only reachable through explicit interaction.

Confirmed problems:

1. Inconsistent directory conventions: liver weights live under `prostate_lesion_seg/`; head and neck live in `data/nnUNet_results/` rather than `trained_models/`.
2. Inconsistent scheduling: only pancreas is in-process nnUNet and does not participate in the cross-process `gpu_lock`; the rest go through subprocess + lease + gpu_lock, creating card contention/OOM risks on the same card.
3. Inconsistent label semantics: pancreas has the full 1-4 set + `label_stats`; liver/kidney are binary; head and neck/nasopharynx are dual-target 1/2; lung is binary. Downstream `web/structure_service.py` and `web/routes/viewer_routes.py` guess semantics from string prefixes, and `vista3d_lung_tumor` is not even recognized as a model source (it is treated as an uploaded mask).
4. Inconsistent frontend availability: `capability_state` determines green/red; the three newly integrated sites have long shown "pending validation", so the color/text of the options users see differs from verified sites.
5. Route/alias gaps: `头颈部肿瘤` and `肺部肿瘤` fail hard (`Unsupported CTV tumor_type`); the `鼻咽癌` sentinel is not in the route whitelist, so the automatic path is lost; `请分割<部位> CTV` direct execution regresses to `semantic_action` (`tests/test_image_metadata_query.py:48`).

## 2. Goals and Non-Goals

### Goals
- The six sites are **peer** entries in the same category `tumor_segmentation`, declared and managed uniformly by **a single registry**.
- Frontend: any supported tumor category is **interaction-consistent**, and **anything supported and available is always green**.
- Backend: **unified execution boundary** (one GPU queue/lock + DeviceManager lease, with pancreas included), unified cancellation/timeout/OOM policy, unified output contract, unified downstream semantics.
- Downstream (Structure Set / 2D / 3D / Data Tree / planning / reporting) is **essentially indifferent** to the CTV mask of any site (planning always takes the target union; display may carry per-label detail).
- Fix the three defects in Section 1 item 5.

### Non-Goals
- Do not rewrite the user-provided inference scripts (`infer_lung_vista.py`, `cascade_infer*.py`, `infer_headneck.py`, `infer_nasopharynx.py` are kept as-is).
- Do not unify internal engine implementations (VISTA-3D remains the foundation model for lung).
- Do not improve model accuracy; do not do release-tree `BrachyBot-release` sync (separate round).
- Do not change the planning/dose/guide algorithms themselves.

## 3. Architecture

### 3.1 Single Model Registry `tool_factory/CTV_seg/model_registry.py`

Each `CTVRRoute` declares (dataclass/frozen mapping):

- `id`: canonical route name, also used as `tumor_type`, `ctv_source`, and catalog `id` (**kept unchanged to avoid data migration**).
- `site`, `display_zh`, `display_en`, `modality`, `ct_phase` (nullable).
- `engine`: `inproc_nnunet` | `subprocess` | `text_guided` (BiomedParse v2 for colon/prostate; SAT3D remains an explicit-interaction research route, also registered as a source but with `ui_visible=False`).
- `script`, `model_root`, `checkpoint`, `runtime_python`, `args`, `precision`.
- `labels` (id→name) and `target_semantics`: `single_target` | `target_plus_anatomy` | `multi_target_gtv`.
- `availability_probe` (currently `site_model_availability` / `cascade_availability` / pancreas directory check).
- `catalog_status` (`verified`/`experimental`, purely explanatory text), `validation` metrics, `requires_review`.

All six sites are registered as **peer entries**; colon/prostate are likewise registered (`engine=text_guided`, BiomedParse), and SAT3D remains a research route but registers its source.

Derived relationships (changed to derive from the registry, with external behavior unchanged):
- `tool_factory/CTV_seg/__init__.py`: `TOOL_REGISTRY`, the `normalize_tumor_type` alias table, `list_tools()`, `_PREFERRED_TUMOR_TYPES`.
- `model_catalog.py`: `CTV_MODEL_CATALOG` entries, `catalog_with_local_status`, `filter_catalog`.
- Compatibility layer: `site_models.SITE_MODELS` and `nnunet_cascade_tumor.CASCADE_SITE_SPECS` are kept as registry-derived views to avoid breaking existing importers and tests.

### 3.2 Unified Execution Boundary

Add `tool_factory/CTV_seg/executor.py`: `run_ctv_model(route_id, image, *, fast_mode=None) -> ModelOutput`.

- **Engine adapters**: `InProcNNUNetEngine` (pancreas; extracted from `pancreatic_tumor_nnunet.py`, adding only locking and not changing inference parameters) and `SubprocessScriptEngine` (liver/kidney/head and neck/nasopharynx/lung, calling the existing scripts as-is).
- **Unified scheduling**: all engines first acquire a `DeviceManager` lease, then the **same cross-process per-card lock** (reusing `site_model_runtime.gpu_lock`, path `$TMPDIR/brachybot-ctv-gpu-<uid>/gpu-N.lock`); the lock directory does not drift with the caller's `TMPDIR` (explicitly pinned to a user directory under the system temp directory).
- **Unified policies**: queue timeout `BRACHYBOT_CASCADE_QUEUE_TIMEOUT_SEC` (default 900s), inference timeout `BRACHYBOT_CTV_TIMEOUT_SEC`, cancellation polling `raise_if_cancelled`, CUDA OOM retried once on another card only when `device_count>=2` and **without lowering precision or reducing folds**.
- **Geometry**: the input is written to a temporary NIfTI on the original CT grid; the output must match the input `size/spacing/origin/direction` (tolerance 1e-4), otherwise it fails; uniformly convert to LPI; never silently resample a failed output into something that "looks usable".

### 3.3 Unified Output Contract

`ModelOutput` is normalized by `CTVSegmentationTool` into unified metadata:

`ctv_array` (binary target union, uint8), `ctv_mask` (LPI reference grid), `full_label_array` (when >1 label), `label_map`, `label_counts`, `label_stats` (uniformly compute voxels/volume/centroid for each label), `ctv_voxel_count`, `ctv_volume_mm3`, `tumor_type_used`, `ctv_source`=route id, `target_semantics`, `ct_phase`, `inference_script`, `checkpoint`, `model_validation`.

Current gaps to fill: pancreas lacks `ctv_source`/`tumor_type_used` (the outer layer falls back to `"model"`); cascade and site models lack `label_stats`; `ctv_source` naming is inconsistent (`model` / `nnunet_cascade_*` / route id). After unification **every site's `ctv_source` equals the registry id**.

### 3.4 Unified Downstream Semantics

Delete the prefix guessing `_is_model_ctv_source`/`is_multitarget_gtv_source` in `web/structure_service.py` and the parallel `is_model_ctv` branch in `web/routes/viewer_routes.py`, replacing them with a **lookup of the registry's `target_semantics` by `ctv_source`**:

- `single_target` → binary target (liver/kidney/lung/colon/prostate).
- `target_plus_anatomy` → label 1 is the target, 2..N are anatomy (routed to the OAR source, e.g. pancreas 2/3/4).
- `multi_target_gtv` → labels 1/2 are both targets; planning takes the union, and the Data Tree displays per-label (head and neck/nasopharynx).

Simultaneously review the CTV/OAR storage and provenance keys in `web/routes/planning_routes.py` to ensure the write paths are consistent across all six sites.

### 3.5 Unified Frontend

- The selector options are uniformly sourced from the registry (server-side rendering + `/ctv/models?include_experimental=1` capability status), so **adding a site only requires changing the registry**.
- **Unified color: any supported and `callable` tumor category is always green**; unavailable is red with a reason. Validation maturity (`verified`/`experimental`) affects only the help text, not the color.
- Unified empty-result/failure/queued/inferring prompts; nasopharynx ncct/cect are peer entries, and guessing the phase from image intensity is forbidden.
- Complete the alias/phase passthrough: `updateTumorTypeSelector` in `brachybot-ui-api.js` and the call chain in `brachybot-manual-annotation.js`, adding `鼻咽`/`头颈部肿瘤`/`肺部肿瘤` and the like.

### 3.6 Route and Alias Fixes

- Add to `normalize_tumor_type`: `头颈部肿瘤`/`头颈部`, `肺部肿瘤`/`肺部`/`肺`, etc. (aligned with the existing `头颈肿瘤`/`肺癌`).
- `agent_runtime/response_tools.py`: `_map_tumor_type` handles the `nasopharynx` sentinel — when `ct_phase` is known it maps directly to ncct/cect, and when unknown it preserves "needs user to select phase", no longer logging "Unknown tumor_type" and clearing it; adjust `_SUPPORTED_AUTOMATIC_CTV_TYPES` accordingly.
- `agent_runtime/turn_policy.py`: fix the direct-execution regression where `请分割<部位> CTV` is judged as `semantic_action` (`whole_request_contract_not_satisfied`), keeping review=False.
- `ct_phase` remains `enum: [ncct, cect]`; when there is no phase, the tool returns `code=ct_phase_required, requires_user_input=True`.

## 4. Error Handling

- Availability is validated once each at catalog probe time and at call time; missing resources fail closed and return a unified `code` (reusing `site_model_inference_failed` / `cascade_*` with unified naming).
- Empty masks use unified diagnostic wording ("the model ran but detected no target" vs "the model is unavailable"), with no per-site special casing.
- Cancellation: `OperationCancelled` propagates upward, the subprocess group is terminated, and the request directory is cleaned up.
- Timeout: terminate the process group, clean up the temporary directory, and return a retryable error; no card-holding processes may be left behind.

## 5. Testing

- `tests/test_model_registry.py`: registry completeness; every `ui_visible` entry's id/`tumor_type` resolves to a registered tool; alias matrix; phase dispatch.
- `tests/test_executor_boundary.py`: consistent output keys under mocked engines for all six sites; gpu_lock participants cover the six sites + pancreas; consistent cancellation/timeout/OOM behavior.
- `tests/test_downstream_equivalence.py`: synthesize results by `target_semantics` and feed them to `structure_service`/`viewer_routes`/`planning_routes`, asserting consistent behavior and that **no per-site prefix special casing remains in the source**; lung is recognized as a model source.
- Frontend contract: selector options == registry; all available items green; nasopharynx phases; aliases; `/ctv/models` fields.
- Update existing: `test_site_model_deployment.py`, `test_nnunet_cascade_tumor.py`, `test_review_round6_regressions.py`, `test_runtime_contracts.py`, `test_uploaded_mask_staging.py`, `test_image_metadata_query.py`.
- Optional real-GPU smoke: 1 case per site (requires user consent to occupy the GPU), recording duration/voxels/geometry.

## 6. Migration and Compatibility

- All route ids are unchanged → session snapshots, `ui_bridge`, and historical aliases need no migration.
- Pancreas only adds a GPU lock; inference parameters/precision/folds are unchanged.
- Weight files are not moved (the inconsistent directory-convention problem is solved by converging the declaration in the registry, avoiding path regressions caused by large-scale moves).
- The compatibility layer ensures existing imports of `from ...site_models import SITE_MODELS` / `CASCADE_SITE_SPECS` do not break.

## 7. Phases

1. Backend: registry + execution boundary + output contract + downstream semantics + unit/equivalence tests.
2. Frontend + route/alias defect fixes + frontend contract tests.
3. Optional GPU smoke and finalizing the catalog maturity wording.

## 8. Risks

- Another session's uncommitted changes exist in the same repo (`index.html`, `response_tools.py`, `turn_policy.py`, `structure_service.py`, `viewer_routes.py`, `web/routes/planning_routes.py`, etc.) → changes must be committed in small steps and checked item by item to avoid conflicts.
- The GPU lock only covers adapters that participate in the protocol; it does not constrain unrelated training jobs.
- VISTA-3D may produce false positives on non-chest CT (its README already notes this).
- After pancreas is included in the lock, it may be queued behind long tasks; mitigate with queue timeout + frontend status.

## 9. Open Items

- Release tree `BrachyBot-release` sync: separate round.
- Final wording for catalog maturity text (`verified`/`experimental` are explanatory text only).

## 10. Addendum: BiomedParse v2 as a Peer Open-Vocabulary Pathway (added 2026-09-17)

It is confirmed that BiomedParse v2 is an open-vocabulary pathway, placed as a peer alongside the six dedicated models in the same category `tumor_segmentation`, with unified management and scheduling:

- **Peer registration**: the registry adds `biomedparse_segmentation` (`engine=text_guided`, open vocabulary, `target`/`prompt` arbitrary text) together with the already-registered `biomedparse_colon_primary`/`biomedparse_prostate_lesion` (closed-set prompts). All three share the same category grouping, availability probing, and frontend presentation as the dedicated models.
- **Downstream semantics**: add `target_semantics='candidate_mask'` — open vocabulary produces a **reviewable candidate mask** (reusing `generic_mask`, `source=biomedparse_v2`) that does not automatically become CTV/OAR; the user may explicitly promote it to CTV in the Data Tree before it enters the planning chain.
- **Fallback for tumors with no dedicated model**: when `ctv_segmentation` receives an unregistered `tumor_type`, the failure metadata returns `open_vocabulary_available=True` and a suggested prompt; the route is allowed to switch to `biomedparse_segmentation`, and the frontend explicitly labels it "research candidate, review required".
- **Unified scheduling**: BiomedParse external inference (`scripts/biomedparse_v2_worker.py`) must share the DeviceManager lease + cross-process `gpu_lock` with the other engines, and must explicitly specify the card selected by DeviceManager via `CUDA_VISIBLE_DEVICES` (the worker currently hardcodes the default `cuda`, which would contend for GPU0).
- **Frontend consistency**: green when available; tumor categories and the open-vocabulary pathway are grouped together; label it as a research candidate.
