---
name: generic_segmentation
description: Generic segmentation for any tumor type
category: segmentation
triggers:
  - segmentation
  - auto segmentation
  - auto-segmentation
tool_sequence:
  - ctv_segmentation
  - oar_segmentation
parameters:
  fast_mode: false
  organ_type: general
success_threshold: 0.7
version: "1.0.0"
---

# Generic Segmentation

Perform automatic segmentation of tumor and organs at risk.

## Behavior

- Automatically detects tumor type from CT image
- Uses appropriate segmentation model (VoCo or nnU-Net)
- Segments both CTV and OARs

## Output

- CTV mask
- OAR masks
- Volume statistics for each structure

## Notes

- For specific tumor types, use dedicated skills (pancreas_segmentation, prostate_segmentation)
- Fast mode available for quick preview
