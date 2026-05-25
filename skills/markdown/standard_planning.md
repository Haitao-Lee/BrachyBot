---
name: standard_planning
description: Standard brachytherapy treatment planning workflow
category: planning
triggers:
  - 规划
  - 标准计划
  - treatment plan
  - 计划
  - plan
tool_sequence:
  - ctv_segmentation
  - oar_segmentation
  - trajectory_planning
  - seed_planning
  - dose_engine
  - dose_evaluation
parameters:
  tumor_type: null
  organ_type: general
  fast_mode: false
success_threshold: 0.7
version: "1.0.0"
---

# Standard Brachytherapy Planning

Execute the complete brachytherapy treatment planning workflow.

## Steps

1. **CTV Segmentation**: Segment the clinical target volume from CT
2. **OAR Segmentation**: Segment organs at risk
3. **Trajectory Planning**: Generate needle trajectory candidates
4. **Seed Planning**: Optimize seed placement along trajectories
5. **Dose Engine**: Calculate dose distribution
6. **Dose Evaluation**: Evaluate plan quality metrics

## Parameters

- `tumor_type`: Type of tumor (pancreatic, prostate, liver, etc.)
- `organ_type`: Type of OAR segmentation (general, pancreatic, etc.)
- `fast_mode`: Use fast inference mode for segmentation

## Output

Complete treatment plan with:
- CTV and OAR contours
- Needle trajectories
- Seed positions
- Dose distribution
- Quality metrics (V100, D90, etc.)
