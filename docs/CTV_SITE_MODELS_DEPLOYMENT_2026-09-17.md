# Supplied CT segmentation model deployment

Base checkout: `09151749c`, internal `<workspace>/BrachyBot`.
The unrelated pre-existing `utils/user_errors.py` and `tests/test_user_error_contract.py` edits are preserved.

## Routes and inference contracts

| Selector / canonical route | Executor | Quality settings |
|---|---|---|
| Liver / `nnunet_liver_tumor` | Existing supplied `cascade_infer_v2.py` | Default five-fold cascade, existing 0.5 tile step |
| Kidney / `nnunet_kidney_tumor` | Existing supplied `cascade_infer_kidney.py` | Default five-fold cascade; tumor only, no cyst output |
| Lung / `vista3d_lung_tumor` | Supplied `infer_lung_vista.py` | Class 23; foundation model, not a site-fine-tuned model |
| Head-neck / `nnunet_head_neck_gtv` | Supplied `infer_headneck.py` | Packaged best fold 1, checkpoint_final, default FP32/TTA |
| Nasopharynx non-contrast / `nnunet_nasopharynx_ncct` | Supplied `infer_nasopharynx.py` | NCCT package, checkpoint_best, default FP16/TTA |
| Nasopharynx contrast-enhanced / `nnunet_nasopharynx_cect` | Same supplied script | CECT package, checkpoint_best, default FP16/TTA |

All external inference runs as `brachybot` with `/opt/miniconda3/bin/python`. No package installation, environment replacement, weight copying, or inference-script rewriting is involved. `transformers==4.46.3` is checked for VISTA-3D. Existing pancreatic, colon, prostate MRI, generic BiomedParse and explicitly interactive SAT3D functionality remains available. HECKTOR CT+PET is not exposed.

Generic nasopharynx requests require an explicit `ct_phase=ncct/cect` or the phase-specific model ID. Image intensity is not used to guess contrast phase. Restored lung/head-neck aliases normalize to the new canonical routes. The selector exposes two separate nasopharynx entries and migrates saved lung/head-neck model choices.

## Geometry and label handling

Each request writes one temporary NIfTI retaining the original CT geometry and invokes the supplied script unchanged. Output must exist even if the script exits 0 (VISTA may catch its internal errors). Output shape, spacing, origin, direction, and allowed label values are validated. A failed output is not silently resampled into apparent validity.

The unified CTV boundary converts to the existing LPI viewer grid. GTV primary/nodal labels stay separate in `full_label_array` and the Structure Set, while planning receives their binary union. The adapter supplies a spatially tagged image for the full labels to prevent double orientation at the wrapper boundary.

Existing Structure Set and viewer code treated all `nnunet_*` label-2 outputs as pancreatic artery. Both sites now use a shared GTV provenance predicate so GTVn/GTVnd remains target, including after a restored source becomes `classified`. Pancreatic artery/vein/pancreas handling is preserved and regression-tested. No automatic GTV-to-CTV margin is introduced.

## Scheduling and failure handling

The six supplied-script routes share per-GPU filesystem locks under a user-scoped temporary directory, coordinating across BrachyBot processes using these adapters. DeviceManager chooses a card. OOM retries once on the other card with the same model settings; it never reduces folds/precision. These locks do not control unrelated external training jobs or adapters that do not participate in this lock protocol.

Cancellation is polled during GPU waiting and subprocess communication. Cancellation/timeout terminates the subprocess group and cleans its request directory. Runtime children inherit the brachybot user site, but not parent PYTHONPATH/PYTHONHOME or CUDA remapping. Model packages, CT source files and Session records are not modified by the smoke tests.

## Verification

Relevant regression: **171 passed, 3 warnings** (site-model contracts, existing cascades, segmentation override, uploaded-mask provenance, BiomedParse, SAT3D, OAR alignment, runtime contracts, device leases and semantic authorization). Tests cover rotated/anisotropic geometry, primary/nodal union through the planner, no spurious hard obstacles, viewer label-volume transport for fresh/restored sources, missing phase, empty/invalid output, cancellation checks, GPU exclusivity and OOM retry. JavaScript syntax is checked with Node on the development workstation (Node is absent on the server).

Real inference smoke tests through `CTVSegmentationTool`, using dataset CT inputs and no live patient Session mutations:

| Route | Seconds, including script startup | Foreground voxels | Label counts | Geometry |
|---|---:|---:|---|---|
| Head-neck CT | 65.583 | 5,246 | GTVp 1,662; GTVn 3,584 | Input/LPI reference matched |
| Nasopharynx NCCT | 83.738 | 218,867 | GTVnx 190,064; GTVnd 28,803 | Input/LPI reference matched |
| Nasopharynx CECT | 84.585 | 222,915 | GTVnx 191,938; GTVnd 30,977 | Input/LPI reference matched |
| Lung VISTA | 26.019 | 2,820 | Tumor 2,820 | Input/LPI reference matched |

Raw records: `/tmp/brachybot-{headneck,ncct,cect,lung}-smoke.json`; full-label NIfTI outputs beside them. These timings are single-case integration measurements, not general latency guarantees. This deployment does not rerun whole-dataset Dice evaluation; catalog metrics are explicitly attributed to the user-supplied model evaluations. The existing liver/kidney resource, default-ensemble and geometry contracts were regression-tested; these two routes were already installed before this change.

Public release checkout and its service are outside this deployment. The internal 8080 service was gracefully reloaded after recent saved tasks were checked as completed/idle. PID 647203 runs the original brachytherapy interpreter from the intended checkout, using the former process environment. Listener ownership, startup tool registration, HTTP 200 and the served JavaScript SHA-256 were verified. Startup log: `.runtime/server-site-models-20260917.log`. Browser refresh is needed for the new selector JavaScript.
