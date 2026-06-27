---
name: dose_evaluation
description: Standard dose evaluation with metrics
category: evaluation
triggers:
  - evaluation
  - dose eval
  - metrics
  - dose evaluation
tool_sequence:
  - dose_evaluation
  - oar_constraint_checker
  - plan_quality_scorer
parameters:
  prescribed_dose: 1.0
  eval_type: standard
success_threshold: 0.7
version: "1.0.0"
---

# Dose Evaluation

Evaluate treatment plan quality with standard metrics.

## Metrics Calculated

- **V100**: Volume receiving 100% of prescription dose
- **V150**: Volume receiving 150% of prescription dose
- **V200**: Volume receiving 200% of prescription dose
- **D90**: Dose covering 90% of CTV volume
- **D95**: Dose covering 95% of CTV volume

## OAR Constraints

Check dose constraints for each organ at risk:
- Rectum: D2cc < 75% of prescription
- Bladder: D2cc < 80% of prescription
- Urethra: D10 < 150% of prescription

## Output

- Metric values with pass/fail status
- Overall plan quality score (0-100)
- Recommendations for improvement
