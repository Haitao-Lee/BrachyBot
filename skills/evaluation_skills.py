"""
Evaluation Skills
================
Predefined skill templates for various evaluation workflows.
"""

from .skill_base import Skill


class StandardEvaluationSkill(Skill):
    """Standard dose evaluation with comprehensive metrics."""

    def __init__(self):
        super().__init__(
            name="standard_evaluation",
            description="Standard dose evaluation: Vx/Dx metrics + OAR constraint check",
            category="evaluation",
            triggers=["评估", "evaluate", "剂量评估", "dose eval", "metrics"],
            tool_sequence=[
                "dose_evaluation",
                "oar_constraint_checker",
                "plan_quality_scorer",
            ],
            parameters={
                "dose_evaluation": {"prescribed_dose": 1.0},
            },
        )


class DetailedEvaluationSkill(Skill):
    """Detailed evaluation including DVH curves and full OAR analysis."""

    def __init__(self):
        super().__init__(
            name="detailed_evaluation",
            description="Detailed dose evaluation with DVH curves and comprehensive OAR analysis",
            category="evaluation",
            triggers=["详细评估", "详细", "detailed", "DVH", "comprehensive"],
            tool_sequence=[
                "dose_evaluation",
                "dvh_calculation",
                "oar_constraint_checker",
                "plan_quality_scorer",
                "report_generator",
            ],
            parameters={
                "dose_evaluation": {"prescribed_dose": 1.0},
                "report_generator": {"output_format": "html"},
            },
        )