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
isolated dependency environment. The Hugging Face checkpoint may require
accepting the model terms and sharing contact information before download.

## Installation boundary

Do not install the official pinned CUDA/PyTorch stack into BrachyBot's core
environment. Create the isolated environment recommended by the upstream
repository, install its requirements there, and clone/checkout the exact
revision that was validated locally. Then configure the BrachyBot process:

```bash
export BIOMEDPARSE_ROOT=/opt/biomedparse/BiomedParse
export BIOMEDPARSE_V2_CHECKPOINT=/opt/biomedparse/BiomedParse/biomedparse_v2.ckpt
```

`BIOMEDPARSE_V2_CHECKPOINT` may point outside the checkout. The adapter checks
that the checkout contains `configs/model` and that the checkpoint exists
before it imports `torch`, `hydra`, or any upstream module. No checkpoint is
committed to this repository.

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
