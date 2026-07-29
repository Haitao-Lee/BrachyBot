# BiomedParse v2 Optional CTV Adapter

## Suitability decision

BiomedParse v2 is a reasonable **research candidate** for non-pancreatic CT
lesion candidates because the official project documents 3D, text-guided
inference and CT prompts for liver tumors, lung lesions, kidney lesions,
colon primaries, and head-and-neck cancer. It is not a site-specific,
clinically validated CTV contouring model. The adapter therefore never replaces
the existing pancreatic nnU-Net path, never downloads weights automatically,
and never turns an empty or unavailable result into a plan.

Official sources:

- [Microsoft BiomedParse v2 repository](https://github.com/microsoft/BiomedParse/tree/v2)
- [BiomedParse model card and checkpoint](https://huggingface.co/microsoft/BiomedParse)
- [BiomedParse, Nature Methods (2025)](https://doi.org/10.1038/s41592-024-02499-w)

The official repository is research/development software and requires its own
isolated dependency environment. The Hugging Face checkpoint is gated and
requires accepting the model terms and sharing contact information before
download.

## Installation boundary

Do not install the official pinned CUDA/PyTorch stack into BrachyBot's core
environment. Create the isolated environment recommended by the upstream
repository, install its requirements there, and clone/checkout the exact
revision that was validated locally. Then configure the BrachyBot process:

```bash
export BIOMEDPARSE_ROOT=/opt/biomedparse/BiomedParse
export BIOMEDPARSE_V2_CHECKPOINT=/opt/biomedparse/BiomedParse/biomedparse_v2.ckpt
export BIOMEDPARSE_V2_TEXT_ASSETS=/opt/biomedparse/clip-vit-base-patch32
```

`BIOMEDPARSE_V2_CHECKPOINT` may point outside the checkout. The adapter checks
that the checkout contains `configs/model`, that the checkpoint exists, and
that the local CLIP tokenizer directory contains the required tokenizer files
before it imports `torch`, `hydra`, or any upstream module. Keeping the
tokenizer local prevents first inference from silently blocking on a network
request to Hugging Face. No checkpoint or tokenizer artifact is committed to
this repository. For a repository-local deployment, authenticate with Hugging
Face and run:

```bash
export HF_TOKEN="<your Hugging Face access token>"
python scripts/download_biomedparse_v2.py
```

This stores the ignored binary at
`models/ctv/biomedparse_v2/biomedparse_v2.ckpt` and the official
`openai/clip-vit-base-patch32` tokenizer files under
`models/ctv/biomedparse_v2/clip-vit-base-patch32`. The adapter discovers both
paths when their environment variables are not set. The upstream checkout must
still be supplied through `BIOMEDPARSE_ROOT`.

The official model is loaded lazily on the first selected request and cached by
checkout/checkpoint path. The model may use CUDA when available; this optional
runtime is serialized during initialization and inference because Hydra is
process-global.

## Supported candidate keys

| Tumor/site selector | Official text prompt | CT window |
|---|---|---|
| `biomedparse_liver_tumor` | `liver tumors` | soft tissue, W400/L40 |
| `biomedparse_kidney_lesion` | `kidney lesion` | soft tissue, W400/L40 |
| `biomedparse_lung_lesion` | `lung lesion` | lung, W1500/L-160 |
| `biomedparse_colon_primary` | `colon cancer primary` | soft tissue, W400/L40 |
| `biomedparse_head_neck_cancer` | `head and neck cancer` | soft tissue, W400/L40 |

The normal UI continues to show tumor types rather than model brands. For
existing liver/kidney/lung/colon selections, the CTV tool prefers the local
VoCo checkpoint and uses the matching BiomedParse key only when that checkpoint
is absent and the optional runtime is available. Pancreas is intentionally
excluded from this fallback.

## Coordinate and clinical contract

The input is reoriented to the project's LPI physical-grid contract. The
returned binary mask is copied onto that CT's physical metadata, and the
metadata records `ctv_source=biomedparse_v2_research_candidate`,
`research_only=true`, the prompt, model URL, checkpoint path, and existence
confidence. The unified CTV tool then applies the normal physical-grid
alignment used by the 2D/3D viewers.

The result is a candidate for contour review, not a signed CTV. A clinician
must inspect and edit the contour, confirm the tumor site and dose parameters,
and independently verify the plan before any treatment decision. If the model
is missing, inference fails, or the mask is empty, planning must stop until a
matching user-provided CTV mask is supplied.

## Verified remote deployment (2026-07-29)

The current RTX 3090 deployment was verified with:

- upstream BiomedParse v2 checkout at commit
  `e02096c03af0d79c6994ffc2d60a49eeb0361e1f`;
- the official 4.2 GB `biomedparse_v2.ckpt`;
- an isolated Python 3.10 environment;
- Detectron2 built against the installed Torch/CUDA stack for compute
  capability 8.6;
- local `openai/clip-vit-base-patch32` tokenizer assets, with no runtime
  network dependency;
- successful Hydra compose, model construction, checkpoint load, CUDA transfer,
  and isolated-worker inference on a synthetic 3D input.

The synthetic smoke test returned a correctly shaped binary volume and
confidence metadata. It verifies the technical invocation and serialization
path only. It does not establish clinical segmentation quality for any tumor
site, so these non-pancreatic routes remain research/experimental capabilities
until representative cases receive expert review.
