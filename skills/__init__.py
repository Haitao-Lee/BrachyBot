"""
BrachyBot Skills System
======================
Predefined skill templates that can be refined based on user interactions.
Skills are reusable, composable units of agent behavior.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .skill_base import Skill, SkillRegistry
from .planning_skills import (
    StandardPlanningSkill,
    RLPlanningSkill,
    QuickPlanningSkill,
)
from .segmentation_skills import (
    PancreasSegmentationSkill,
    ProstateSegmentationSkill,
    GenericSegmentationSkill,
)
from .evaluation_skills import (
    StandardEvaluationSkill,
    DetailedEvaluationSkill,
)
from .advanced_skills import (
    FullAutoPlanningSkill,
    QuickPlanSkill,
    RLPlanSkill,
    PancreasCTVSkill,
    PancreasOARSkill,
    PancreasFullSkill,
    ProstateFullSkill,
    DoseEvalSkill,
    PlanOptimizationSkill,
    IntraOpReplanSkill,
    DICOMExportSkill,
    ReportGenerationSkill,
    MultiOrganSegSkill,
    VoCoSegSkill,
    QualityCheckSkill,
    DVHAnalysisSkill,
    SelfEvolveSkill,
    CodeWriterSkill,
)

__all__ = [
    "Skill",
    "SkillRegistry",
    "StandardPlanningSkill",
    "RLPlanningSkill",
    "QuickPlanningSkill",
    "PancreasSegmentationSkill",
    "ProstateSegmentationSkill",
    "GenericSegmentationSkill",
    "StandardEvaluationSkill",
    "DetailedEvaluationSkill",
    "FullAutoPlanningSkill",
    "QuickPlanSkill",
    "RLPlanSkill",
    "PancreasCTVSkill",
    "PancreasOARSkill",
    "PancreasFullSkill",
    "ProstateFullSkill",
    "DoseEvalSkill",
    "PlanOptimizationSkill",
    "IntraOpReplanSkill",
    "DICOMExportSkill",
    "ReportGenerationSkill",
    "MultiOrganSegSkill",
    "VoCoSegSkill",
    "QualityCheckSkill",
    "DVHAnalysisSkill",
    "SelfEvolveSkill",
    "CodeWriterSkill",
]
