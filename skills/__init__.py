"""
BrachyBot Skills System
======================
Predefined skill templates that can be refined based on user interactions.
Skills are reusable, composable units of agent behavior.

Supports two formats:
1. Python class-based skills (legacy)
2. Markdown files with YAML frontmatter (recommended, Claude Code style)
"""

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
    LiverFullSkill,
    LungFullSkill,
)

# Markdown skill loader (Claude Code style)
from .markdown_loader import (
    MarkdownSkill,
    MarkdownSkillLoader,
    get_skill_loader,
    find_skill_for_request,
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
    "LiverFullSkill",
    "LungFullSkill",
    # Markdown skills
    "MarkdownSkill",
    "MarkdownSkillLoader",
    "get_skill_loader",
    "find_skill_for_request",
]
