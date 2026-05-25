---
name: prostate_segmentation
description: Prostate tumor and OAR segmentation
category: segmentation
triggers:
  - 前列腺
  - prostate
  - 前列腺癌
tool_sequence:
  - ctv_segmentation
  - oar_segmentation
parameters:
  tumor_type: prostate
  organ_type: general
  fast_mode: false
success_threshold: 0.8
version: "1.0.0"
---

# Prostate Segmentation

Segment prostate tumor and surrounding organs at risk.

## Tools Used

- **CTV Segmentation**: Prostate tumor segmentation
- **OAR Segmentation**: General OAR segmentation (rectum, bladder, urethra)

## Output

- CTV mask (prostate contour)
- OAR masks (rectum, bladder, urethra)
- Volume statistics

## Clinical Notes

- Critical OARs: rectum, bladder, urethra
- Typical prescription: 14-16 Gy in single fraction
- Urethra dose constraint: D10 < 150% of prescription
