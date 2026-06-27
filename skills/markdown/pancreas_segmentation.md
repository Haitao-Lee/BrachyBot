---
name: pancreas_segmentation
description: Pancreas tumor and OAR segmentation
category: segmentation
triggers:
  - pancreas
  - pancreatic cancer
tool_sequence:
  - ctv_segmentation
  - oar_segmentation
parameters:
  tumor_type: pancreatic
  organ_type: pancreatic
  fast_mode: false
success_threshold: 0.8
version: "1.0.0"
---

# Pancreas Segmentation

Segment pancreatic tumor and surrounding organs at risk.

## Tools Used

- **CTV Segmentation**: VoCo or nnU-Net based pancreatic tumor segmentation
- **OAR Segmentation**: Pancreatic OAR segmentation (duodenum, stomach, etc.)

## Output

- CTV mask (tumor contour)
- OAR masks (duodenum, stomach, small bowel, etc.)
- Volume statistics for each structure

## Clinical Notes

- Pancreatic tumors often abut duodenum
- Critical OARs: duodenum, stomach, small bowel
- Typical prescription: 15-20 Gy in single fraction
