# BrachyBot Product and CTV Model Expansion Audit

Date: 2026-07-05  
Base revision: `39a2d97`  
Scope: latest GitHub `main`, local working copy, public CT-based CTV segmentation resources, UI/manual/training/product-readiness expectations.

## Executive Summary

This pass confirmed that BrachyBot already implements the core product surface expected for an agentic brachytherapy workstation:

- LLM-driven planning and question answering.
- UI state inspection and UI control through structured backend tools.
- Manual planning without a valid LLM API key.
- Training/monitoring mode for manual or automatic workflows.
- Screenshot-to-LLM visual analysis with provider-adaptive payload handling.
- Clinical knowledge retrieval with source-backed citations.
- Report generation and visualization workflows.

The main verified gap was CTV model governance for non-pancreatic tumors. The repository contained legacy TotalSegmentator-based "tumor" wrappers that could be misread as tumor CTV segmenters even though TotalSegmentator primarily returns organ/anatomy masks. These wrappers have now been fail-closed or clarified, and a CTV model catalog has been added so the assistant, API, and UI can distinguish:

- production-installed CTV models,
- external research checkpoints,
- public training datasets,
- resources that are useful but not valid CTV masks.

## Expected Product Capabilities

| Capability | Current Status | Notes |
|---|---:|---|
| Automatic BrachyBot planning | Implemented | CTV -> OAR -> trajectory -> seed planning -> dose -> report remains the primary workflow. |
| General question answering | Implemented | Prompt routing forbids planning tools for conceptual/non-planning questions. |
| UI state awareness | Implemented | `/api/ui/capabilities`, UI registry, screenshot targets, and UI state bridge expose the interaction surface. |
| UI control by chat | Implemented | `ui_controller`, screenshot, annotation, panel switching, overlays, manual workflow actions. |
| Manual planning if LLM API is unavailable | Implemented | Manual endpoints and web controls support segmentation, trajectory, seeds, dose, DVH, reports, and export. |
| Training/monitoring mode | Implemented | Supports live feedback during manual/automatic planning and final monitoring summary. |
| Manual seed/needle editing | Implemented | UI includes manual needle/seed interaction and dose recomputation path. |
| Manual dose feedback | Implemented with model boundary | Uses trained myDoseNet path; analytical/Gaussian active-dose fallback should remain disabled. |
| Clinical KB use | Implemented | Knowledge-base prompt alignment was previously audited; claims should cite KB/web sources. |
| Screenshot-to-LLM visual analysis | Implemented | Provider-adaptive image payload logic was added before this pass. |
| Multi-site CT CTV segmentation | Partially implemented | Pancreas has the production path when weights are installed. Other sites now have cataloged research/dataset paths, not falsely activated models. |

## Verified Problems and Fixes

| ID | Problem | Verification | Fix |
|---|---|---|---|
| CTV-01 | Legacy liver/kidney/lung/head-neck wrappers used TotalSegmentator anatomy as if it were tumor CTV. | Source review showed tasks such as `liver_vessels`, `kidney`, `lung_vessels`, and `total` being converted into CTV masks. | These entrypoints now fail closed with explicit guidance to use `ctv_segmentation`, `label_path`, or `ctv_model_catalog`. |
| CTV-02 | Legacy pancreatic wrapper could return an empty fallback mask with `success=True`. | Source review showed an outdated nnU-Net path and threshold fallback that generated an all-zero mask. | Legacy wrapper now fails closed and points to `ctv_segmentation` with `tumor_type='nnunet_pancreatic'`. |
| CTV-03 | Prostate wrapper wording implied lesion-level tumor segmentation. | Source review showed TotalSegmentator prostate gland mask being described as tumor tissue. | Wording now states whole-prostate target/gland CTV semantics and records `target_semantics`. |
| CTV-04 | Manual segmentation API always dispatched to pancreatic nnU-Net. | `/api/segmentation` code review showed hard-coded `NNUNetPancreaticTumorTool`. | It now uses unified `CTVSegmentationTool` and accepts optional `tumor_type`. |
| CTV-05 | Empty CTV could continue downstream if a model returned an empty mask. | Unified CTV path did not reject zero-voxel masks. | `CTVSegmentationTool` now fails unless `allow_empty=True`, which is documented as test-only. |
| CTV-06 | LLM prompts lacked a safe model-selection boundary. | Prompt review showed generic `ctv_segmentation` model list but no warning against organ masks as CTV. | System/planning prompts now require `ctv_model_catalog` or `label_path` when no verified model exists. |
| CTV-07 | There was no structured way to tell the UI/agent which CTV resources are local, external, or training-only. | No model catalog endpoint/tool existed. | Added `ctv_model_catalog`, `/api/ctv/models`, and UI capabilities exposure. |

## Public Model and Dataset Review

| Resource | Site | Type | Decision | Source |
|---|---|---|---|---|
| BrachyBot `nnunet_pancreatic` | Pancreas | nnU-Net v2 local model path | Production route when local weights exist. | [MSD](https://medicaldecathlon.com/), [MONAI pancreas DiNTS](https://catalog.ngc.nvidia.com/orgs/nvidia/monaitoolkit/models/monai_pancreas_ct_dints_segmentation) |
| MONAI/NVIDIA pancreas DiNTS | Pancreas | MONAI bundle | Credible future integration target, not wired into current nnU-Net v2 predictor. | [NGC model card](https://catalog.ngc.nvidia.com/orgs/nvidia/monaitoolkit/models/monai_pancreas_ct_dints_segmentation) |
| DIAG Nijmegen PDAC nnU-Net | Pancreas | PDAC likelihood heatmap + anatomy | Useful research source, not activated as binary CTV without threshold validation. | [GitHub](https://github.com/DIAGNijmegen/CE-CT_PDAC_AutomaticDetection_nnUnet/) |
| DiffTumor nnU-Net checkpoints | Liver, pancreas, kidney | Research checkpoints | Downloaded locally for review, not activated because format is not BrachyBot native nnU-Net v2 folder layout. | [GitHub](https://github.com/MrGiovanni/DiffTumor) |
| TextoMorph segmentation checkpoints | Liver, pancreas, kidney | Research checkpoints | Catalog/report candidate only; same activation boundary as DiffTumor until inference format is validated. | [GitHub](https://github.com/MrGiovanni/TextoMorph) |
| Medical Segmentation Decathlon | Liver, lung, pancreas, colon | Public CT training datasets | Recommended baseline datasets for new nnU-Net CTV tools. | [MSD](https://medicaldecathlon.com/) |
| KiTS | Kidney | Public kidney tumor CT dataset family | Recommended kidney tumor CTV training source. | [KiTS](https://kits-challenge.org/) |
| PanTS | Pancreas | Large pancreatic CT dataset | High-value training dataset; license/access must be reviewed before redistribution or training. | [arXiv](https://arxiv.org/html/2507.01291v1) |
| TotalSegmentator | OAR/anatomy | Organ segmentation | Valid for OAR/anatomy, not tumor CTV. | [GitHub](https://github.com/wasserth/TotalSegmentator) |

## Local Checkpoints Downloaded for Review

These files are intentionally ignored by Git via `*.pt`:

| File | Size |
|---|---:|
| `models/ctv/difftumor/nnunet_synt_liver_tumors.pt` | 66,176,221 bytes |
| `models/ctv/difftumor/nnunet_synt_pancreas_tumors.pt` | 66,176,157 bytes |
| `models/ctv/difftumor/nnunet_synt_kidney_tumors.pt` | 66,176,221 bytes |

Download/list helper:

```bash
python scripts/download_ctv_models.py --list
python scripts/download_ctv_models.py --model difftumor_nnunet_liver
```

## Code Changes

- Added `tool_factory/CTV_seg/model_catalog.py`.
- Added `scripts/download_ctv_models.py`.
- Registered `CTVModelCatalogTool` in `AgenticSys.py`.
- Updated CTV tumor-type aliases so pancreas defaults to `nnunet_pancreatic`.
- Changed `/api/segmentation` to use the unified CTV tool instead of hard-coded pancreatic inference.
- Added `/api/ctv/models` with local availability metadata and source links.
- Added CTV model metadata to `/api/ui/capabilities`.
- Updated system and planning prompts to avoid organ-as-CTV substitution.
- Deprecated unsafe legacy TotalSegmentator tumor wrappers.
- Updated README model-weight and product-governance notes.

## Validation

Commands run successfully:

```bash
python -m py_compile AgenticSys.py web/server.py tool_factory/CTV_seg/__init__.py \
  tool_factory/CTV_seg/model_catalog.py scripts/download_ctv_models.py \
  tool_factory/CTV_seg/liver_tumor.py tool_factory/CTV_seg/kidney_tumor.py \
  tool_factory/CTV_seg/lung_tumor.py tool_factory/CTV_seg/head_neck_tumor.py \
  tool_factory/CTV_seg/pancreatic_tumor.py tool_factory/CTV_seg/prostate_tumor.py

python scripts/download_ctv_models.py --list
git diff --check
```

Additional static checks confirmed that deprecated liver, kidney, lung, head-neck, and legacy pancreatic wrappers no longer contain unreachable threshold or TotalSegmentator execution paths. Prostate whole-gland target segmentation now fails if TotalSegmentator fails or returns an empty mask.

## Contributor Note

Local and GitHub contributor checks found no current `claude` author in repository history or GitHub contributor API output at the time of this pass. To add Codex to contributor accounting without rewriting history, the final commit for this pass should use:

```bash
git commit --author "Codex <codex@brachybot.ai>" ...
```

GitHub will show a linked `@codex` contributor only if that GitHub account owns the commit email. Otherwise it may appear as an anonymous contributor named Codex.

## Residual Boundaries

1. Non-pancreatic CTV segmentation is not production-ready until a site-specific model is trained or a downloaded research checkpoint is adapted and validated in BrachyBot's inference stack.
2. DiffTumor/TextoMorph checkpoints should not be used clinically until license, checkpoint format, preprocessing, postprocessing, and coordinate fidelity are validated.
3. TotalSegmentator remains appropriate for OAR/anatomy and should not be used as tumor CTV.
4. Prostate whole-gland target segmentation can be clinically meaningful for prostate brachytherapy, but it is not lesion segmentation.

## Recommended Next Product Step

The most scientifically defensible next feature is a dedicated CTV training/import wizard:

1. Choose site and dataset source from `ctv_model_catalog`.
2. Validate dataset license and label semantics.
3. Convert labels into nnU-Net v2 format.
4. Train/fine-tune model.
5. Run geometry and empty-mask regression tests.
6. Register the model only after successful validation.

This keeps BrachyBot extensible across tumor sites without compromising the current pancreatic workflow.
