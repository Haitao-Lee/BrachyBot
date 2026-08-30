# SAT3D CTV Segmentation Integration

## Purpose and scope

BrachyBot uses the official SAT3D implementation for supported non-pancreatic, closed-set tumor CTV candidate segmentation. This is a system-level routing replacement, not a fallback layered on top of the former models.

The production routing rules are:

- Pancreatic tumor CTV remains on the existing BrachyBot nnU-Net route (`nnunet_pancreatic`).
- Liver, kidney, lung, colon, prostate, and head-and-neck tumor candidates use SAT3D.
- BiomedParse remains available through the separate `biomedparse_segmentation` tool for open-vocabulary masks. A generic BiomedParse mask is an independent Data Tree object; it is not automatically promoted to CTV.
- Historical VoCo, TotalSegmentator liver-tumor, whole-prostate, and closed-set BiomedParse CTV identifiers are accepted only for Session compatibility. The dispatcher normalizes them to the canonical SAT3D route. There is no silent model fallback after an SAT3D failure.

SAT3D output is a research candidate. It must be reviewed and, if necessary, corrected by a qualified clinician before clinical acceptance or treatment delivery. BrachyBot stores this review requirement in result provenance and never describes SAT3D as a clinically validated automatic contour.

## Authoritative upstream resources

- Official repository: <https://github.com/himashi92/SAT3D>
- Pinned source commit: `e85cbf4b2e17c09b34b36369c4eca29e98321b4b`
- Published article: <https://www.nature.com/articles/s41467-026-76531-2>
- Figshare project and model artifacts: <https://doi.org/10.6084/m9.figshare.30155497>
- Repository license: Apache License 2.0 in the pinned official checkout. Deployment and redistribution must also respect the terms attached to the paper, datasets, and model artifacts.

The runtime records both the source commit and checkpoint MD5 values so a restored Session can identify exactly which implementation generated the candidate.

## Supported site and modality contract

| Canonical tumor type | Site | Accepted input modality | Published evidence represented by the route | Product status |
|---|---|---|---|---|
| `sat3d_liver_tumor` | Liver | CT, CTA | MSD Hepatic and LiTS; in-distribution | Research candidate; review required |
| `sat3d_kidney_tumor` | Kidney | CT, CTA | KiTS 2023 and KiPA 2022; in-distribution | Research candidate; review required |
| `sat3d_lung_tumor` | Lung | CT | MSD Lung; in-distribution | Research candidate; review required |
| `sat3d_colon_tumor` | Colon | CT | MSD Colon; in-distribution | Research candidate; review required |
| `sat3d_head_neck_tumor` | Head and neck | MRI, T1, contrast-enhanced T1, T2, or CT | HNTS-MRG MRI plus HECKTOR CT evaluation; CT is marked out-of-distribution | Research candidate; review required |
| `sat3d_prostate_tumor` | Prostate | MRI or T2-weighted MRI | Prostate158 zero-shot/out-of-distribution evaluation | Research candidate; OOD warning and review required |

An incompatible modality is a hard, actionable error (`sat3d_modality_mismatch`). The system does not reinterpret a prostate CT as T2 MRI and does not fall back to whole-prostate TotalSegmentator or BiomedParse.

SAT3D accepts one 3D single-modality volume per inference. If the uploaded NIfTI is four-dimensional, `volume_index` selects one 3D volume; the default is index `0`. The original 3D spacing, origin, and direction are preserved after extraction and LPI orientation. Multi-sequence fusion is not performed by this adapter.

## User workflow

1. Load the patient volume into the active Session.
2. Select the tumor site in the Input panel.
3. Select the true image modality. Choosing prostate while the selector is still set to CT changes the default to T2-weighted MRI; the user may still explicitly choose another supported MRI token.
4. For a four-dimensional file, choose the required zero-based volume index.
5. Optionally run a zero-prompt candidate, or use `SAT3D +` to place positive points inside the target and `SAT3D -` to exclude false-positive anatomy.
6. Run the CTV segmentation step.
7. Review the candidate in all three 2D planes, the Data Tree, and the 3D viewer before planning.

Prompt points are stored as Session annotations and therefore survive browser reload, Session switching, and server restart. The API sends points as integer voxel coordinates in `z, y, x` order. Positive and negative coordinates must be inside the selected 3D image and may not overlap.

The official SAT3D Slicer implementation supports an initial zero-prompt pass followed by positive/negative refinement. BrachyBot follows that interaction contract. It does not use ground-truth masks to synthesize clicks at inference time.

## Architecture

### Unified dispatcher

`tool_factory/CTV_seg/__init__.py` is the authoritative CTV routing boundary. It normalizes friendly site names and legacy identifiers before selecting a tool. Every current non-pancreatic closed-set route constructs `SAT3DCTVTool`; pancreatic CTV constructs `NNUNetPancreaticTumorTool`.

The same normalization is used by direct chat actions, dependency-enforced planning, restored Sessions, the Brain integration bridge, and the manual `/api/segmentation` endpoint. This prevents different entry points from selecting different models for the same tumor site.

### Isolated adapter and worker

`tool_factory/CTV_seg/sat3d.py` validates the site, modality, volume index, prompt coordinates, runtime, and artifacts. It writes a temporary LPI-oriented NIfTI plus prompt JSON and invokes `scripts/sat3d_worker.py` in the SAT3D virtual environment.

The worker imports model components and the custom sliding-window implementation from the pinned official checkout. BrachyBot does not copy or edit the upstream model source. The pinned repository's root builder references a missing symbol, so the worker constructs the exact published checkpoint topology from the official model components and loads the official state dictionaries.

The web server does not import PyTorch/SAT3D into its long-lived process. Isolation avoids Python dependency contamination and releases GPU memory when inference exits. A process lock serializes SAT3D inference in one server process to prevent two large model instances from exhausting the same GPU.

### Image preprocessing and spatial correctness

The worker mirrors the official Slicer inference path:

- Read one 3D volume.
- Clip intensities to the 0.5th and 99.5th percentiles of positive foreground voxels.
- Apply TorchIO Z-normalization with a positive-voxel mask.
- Run the official custom sliding-window path with a `128 x 128 x 128` ROI and `0.625` overlap.
- Apply sigmoid and a `0.5` threshold.

The official custom sliding-window helper pads dimensions smaller than 128 but does not shift global point prompts by that padding. This is significant for the thin-z CT/MRI series common in BrachyBot. The worker therefore pads explicitly, shifts only the model-facing prompt coordinates, performs official sliding-window inference, and crops the logits back to the original image grid. The stored user prompts remain on the original grid. Output NIfTI geometry is copied from the adapter's LPI input.

When positive points are supplied, disconnected predicted components are filtered to components containing a positive point. If a point lies just outside thresholded foreground, the nearest predicted component is used. This avoids returning an unrelated disconnected object while retaining the model's segmentation boundary.

### Persistence and provenance

A successful result stores:

- canonical tumor type and site;
- model name and source repository;
- pinned SAT3D commit;
- model and critic checkpoint paths and MD5 values;
- image modality and selected 4D volume index;
- published dataset/evidence classification;
- zero-prompt or point-guided mode;
- positive and negative `z, y, x` points;
- out-of-distribution flag;
- `requires_clinician_review = true`;
- the binary CTV array, SimpleITK image, voxel count, volume, label map, and LPI geometry.

The browser workspace snapshot stores the model selector, modality selector, volume index, and SAT3D point annotations. The server workspace stores the result arrays and provenance. Session restore therefore reconstructs both the clinical result and the interaction state without rerunning SAT3D.

## API contract

The manual endpoint is `POST /api/segmentation` with `kind: "ctv"`.

Example request:

```json
{
  "kind": "ctv",
  "image_path": "/case/inputs/volume.nii.gz",
  "tumor_type": "sat3d_liver_tumor",
  "image_modality": "CT",
  "volume_index": 0,
  "point_coordinate_system": "voxel_zyx",
  "positive_points": [[24, 181, 267]],
  "negative_points": [[24, 170, 240]]
}
```

The unified `ctv_segmentation` tool accepts `voxel_zyx`, `voxel_xyz`, and physical LPS point coordinates. The browser uses `voxel_zyx`.

Failure responses preserve a stable `code` plus relevant diagnostic fields. Important codes include:

- `unsupported_sat3d_tumor_type`
- `sat3d_image_required`
- `sat3d_requires_3d_volume`
- `invalid_sat3d_volume_index`
- `sat3d_modality_mismatch` with `supported_modalities`
- `sat3d_unavailable` with `sat3d_availability`
- `invalid_sat3d_prompt`
- `conflicting_sat3d_prompt`
- `sat3d_worker_missing`
- `sat3d_timeout`
- `sat3d_inference_failed`
- `sat3d_empty_mask`

No failure replaces an existing CTV. An empty candidate explicitly asks for a positive point or reviewed manual mask.

## Installation and deployment

SAT3D lives beside BrachyBot rather than inside its Git checkout. This keeps the large upstream repository, virtual environment, and model artifacts out of application source control.

Run:

```bash
python scripts/install_sat3d.py \
  --root /home/lht/snap/brachyplan/SAT3D \
  --base-python /home/lht/.conda/envs/brachytherapy/bin/python
```

The installer:

1. clones the official repository if necessary;
2. checks out the pinned commit in detached mode;
3. creates `.venv` with access to the base environment's CUDA PyTorch;
4. installs the inference dependencies;
5. downloads the official model and critic from Figshare;
6. verifies both MD5 values before replacing the destination files; and
7. writes `.brachybot-sat3d-runtime.json` as a deployment record.

Recommended server environment:

```bash
export SAT3D_ROOT=/home/lht/snap/brachyplan/SAT3D
export SAT3D_RUNTIME_PYTHON=/home/lht/snap/brachyplan/SAT3D/.venv/bin/python
export SAT3D_MODEL_CHECKPOINT=/home/lht/snap/brachyplan/SAT3D/weights/sam_model_dice_best.pth
export SAT3D_CRITIC_CHECKPOINT=/home/lht/snap/brachyplan/SAT3D/weights/critic_dice_best.pth
export SAT3D_DEVICE=cuda:0
export SAT3D_INFERENCE_TIMEOUT=1800
```

Do not resolve the `.venv/bin/python` symbolic link before launching it. The adjacent `pyvenv.cfg` is required for Python to activate the isolated SAT3D environment.

`GET /api/ctv/models` probes the checkout, exact Git commit, source files, runtime interpreter, checkpoints, and required Python modules. Missing resources render the SAT3D site unavailable in the selector. The availability probe does not download or mutate the host. Immediately before inference, the adapter additionally hashes both checkpoint files and fails closed on any mismatch.

## Legacy identifier migration

The following examples normalize without running their former implementation:

- `liver`, `liver_tumor`, `voco_liver`, `totalsegmentator_liver_tumor`, and `biomedparse_liver_tumor` -> `sat3d_liver_tumor`
- `kidney`, `voco_kidney`, and `biomedparse_kidney_lesion` -> `sat3d_kidney_tumor`
- `lung`, `voco_lung`, and `biomedparse_lung_lesion` -> `sat3d_lung_tumor`
- `colon`, `voco_colon`, and `biomedparse_colon_primary` -> `sat3d_colon_tumor`
- `biomedparse_head_neck_cancer` -> `sat3d_head_neck_tumor`
- `prostate` and the former whole-prostate route -> `sat3d_prostate_tumor`

Legacy entries remain visible only in the machine-readable audit catalog when deprecated items are explicitly requested. Their `callable` state is always false and their replacement is recorded. This is intentionally different from a runtime fallback.

## BiomedParse boundary

BiomedParse is still registered as `biomedparse_segmentation` for requests such as “segment the shoulder joint” or another open anatomy/lesion prompt. Its result is persisted as a generic segmentation Data Tree node. It does not write `ctv_array`, `ctv_mask`, or `tumor_type_used` and cannot silently become the planning target.

If an operator wants to use a generic mask as CTV, that must be an explicit Data Tree promotion/review action under the same clinical validation rules as an uploaded mask.

## Verification

The integration test suite covers:

- canonical and historical route normalization;
- pancreatic nnU-Net preservation;
- modality mismatch behavior;
- 4D volume selection and LPI geometry;
- positive/negative prompt serialization;
- thin-volume padding and prompt shifting;
- empty-mask non-replacement behavior;
- runtime interpreter isolation;
- model catalog availability and deprecation state;
- UI model, modality, volume-index, and point-tool controls;
- absence of ground-truth click generation in the inference worker.

Deployment acceptance additionally requires:

1. artifact checksum verification;
2. import/runtime probe in the SAT3D virtual environment;
3. one real CUDA worker invocation;
4. API model-catalog verification after server restart;
5. one point-guided candidate on a representative volume;
6. Data Tree, 2D, and 3D display verification; and
7. Session switch and server-restart restore verification without rerunning inference.

## Troubleshooting

### Runtime reports missing modules although they were installed

Confirm `SAT3D_RUNTIME_PYTHON` points to `.venv/bin/python` and has not been resolved to the base interpreter. Run that exact path with `-c "import torchio, monai, torch"`.

### Prostate request reports a modality mismatch

Use a T2-weighted MRI volume and select `T2w`. A prostate CT is not automatically converted or routed to whole-prostate segmentation.

### A 4D image produces the wrong anatomy

Select the correct zero-based `4D Volume Index`. SAT3D receives only that extracted 3D volume; it does not fuse sequences.

### Candidate is empty

Place at least one positive point clearly inside the tumor. Confirm the site, modality, volume index, and image orientation. The adapter preserves the existing CTV after an empty result.

### Positive click appears to have no effect on a thin scan

Inspect worker metadata fields `explicit_padding_before_zyx`, `explicit_padding_after_zyx`, and `model_points_after_padding`. They should show the prompt shifted onto the explicitly padded model grid and the final mask cropped back to the original shape.

### CUDA out of memory

Confirm no unrelated model occupies the selected GPU and set `SAT3D_DEVICE` to the intended device. SAT3D calls are serialized inside one BrachyBot server process; multiple independent server processes require deployment-level GPU coordination.
