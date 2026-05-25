---
name: intraop_replan
description: Intraoperative replanning when seed deviation detected
category: intraoperative
triggers:
  - intraop
  - 术中
  - replan
  - 重新计划
  - deviation
  - 偏差
tool_sequence:
  - seed_segmentation
  - dose_engine
  - dose_evaluation
parameters:
  deviation_threshold: 2.0
  auto_replan: true
success_threshold: 0.8
version: "1.0.0"
---

# Intraoperative Replanning

Trigger replanning when seed deviation exceeds threshold.

## Workflow

1. **Seed Detection**: Detect implanted seeds from intra-op CT
2. **Deviation Check**: Compare with planned positions
3. **Replan Trigger**: If deviation > threshold, trigger replanning
4. **Dose Recalculation**: Recalculate dose with actual seed positions
5. **Evaluation**: Evaluate if plan still meets objectives

## Parameters

- `deviation_threshold`: Maximum allowed deviation in mm (default: 2.0)
- `auto_replan`: Automatically replan if deviation exceeds threshold

## Clinical Notes

- Critical for ensuring adequate dose coverage
- Seeds may migrate during implantation
- Replanning ensures treatment objectives are met
