"""
Planning Skills
===============
Predefined skill templates for various planning workflows.
"""

from .skill_base import Skill


class StandardPlanningSkill(Skill):
    """Standard pre-operative planning workflow."""

    def __init__(self):
        super().__init__(
            name="standard_planning",
            description="Standard pre-operative planning: CTV + OAR seg -> trajectories -> seeds -> dose eval (CNN dose)",
            category="planning",
            triggers=["规划", "标准计划", "standard plan", "治疗计划", "treatment plan"],
            tool_sequence=[
                "ctv_segmentation",
                "oar_segmentation",
                "trajectory_planning",
                "seed_planning",
                "dose_engine",
                "dose_evaluation",
            ],
            parameters={
                "ctv_segmentation": {"tumor_type": None},
                "oar_segmentation": {"organ_type": "general"},
                "seed_planning": {"mode": "rule_based"},
                "dose_engine": {"engine": "cnn"},
            },
        )


class RLPlanningSkill(Skill):
    """Reinforcement learning based planning for complex cases."""

    def __init__(self):
        super().__init__(
            name="rl_planning",
            description="RL-optimized planning for complex cases requiring advanced optimization",
            category="planning",
            triggers=["RL", "强化学习", "rl plan", "强化", "complex", "复杂"],
            tool_sequence=[
                "ctv_segmentation",
                "oar_segmentation",
                "trajectory_planning",
                "seed_planning_rl",
                "dose_engine",
                "dose_evaluation",
                "plan_quality_scorer",
            ],
            parameters={
                "ctv_segmentation": {"tumor_type": None},
                "oar_segmentation": {"organ_type": "general"},
                "seed_planning_rl": {"mode": "rl"},
                "dose_engine": {"engine": "cnn"},
            },
        )


class QuickPlanningSkill(Skill):
    """Quick planning using the spacing-normalized DoseUNet for fast iteration."""

    def __init__(self):
        super().__init__(
            name="quick_planning",
            description="Quick planning mode using the spacing-normalized DoseUNet",
            category="planning",
            triggers=["快速", "quick", "预览", "preview", "速览"],
            tool_sequence=[
                "ctv_segmentation",
                "trajectory_planning",
                "seed_planning",
                "dose_engine",
            ],
            parameters={
                "ctv_segmentation": {"fast_mode": True},
                "seed_planning": {"mode": "rule_based"},
                "dose_engine": {"engine": "cnn"},
            },
        )
