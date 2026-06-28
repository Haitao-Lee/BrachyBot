---
name: rl_planning
description: Reinforcement learning based planning for complex cases
category: planning
triggers:
  - RL
  - reinforcement learning
  - reinforcement
  - rl planning
tool_sequence:
  - ctv_segmentation
  - oar_segmentation
  - trajectory_planning
  - seed_planning_rl
  - dose_engine
  - dose_evaluation
  - plan_quality_scorer
parameters:
  num_candidates: 5
  reward_type: dose_volume
success_threshold: 0.8
version: "1.0.0"
---

# RL-Based Brachytherapy Planning

Use reinforcement learning for complex treatment planning cases.

## Steps

1. **CTV Segmentation**: Segment clinical target volume
2. **OAR Segmentation**: Segment organs at risk
3. **Trajectory Planning**: Generate trajectory candidates
4. **RL Seed Planning**: Use REINFORCE algorithm for optimal seed placement
5. **Dose Engine**: Calculate dose distribution
6. **Dose Evaluation**: Evaluate plan quality
7. **Quality Scorer**: Score plan quality (0-100)

## When to Use

- Complex anatomies
- Multiple OARs nearby
- Need optimal dose conformity
- Standard planning insufficient

## Parameters

- `num_candidates`: Number of trajectory candidates to evaluate
- `reward_type`: Reward function type (dose_volume, conformity, etc.)
