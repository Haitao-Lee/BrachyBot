"""
Advanced Skills — Self-Evolving BrachyBot Skills
=================================================
Comprehensive skills covering all planning scenarios,
with auto-learning and adaptation capabilities.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .skill_base import Skill


class FullAutoPlanningSkill(Skill):
    """
    Fully automated planning: CTV + OAR segmentation → trajectory → seed → dose → eval.
    Triggered by "full plan", "complete planning", "full pipeline".
    """
    def __init__(self):
        super().__init__(
            name="full_auto_planning",
            description="Fully automated treatment planning with auto-segmentation",
            category="planning",
            triggers=["full plan", "complete planning", "generate full plan", "full pipeline"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation"],
            parameters={
                "ctv_segmentation": {"mode": "auto"},
                "oar_segmentation": {"mode": "totalsegmentator"},
                "seed_planning": {"mode": "rule_based"},
                "dose_engine": {"method": "cnn"},
            },
        )


class QuickPlanSkill(Skill):
    """
    Quick planning with pre-segmented data: trajectory → seed → dose → eval.
    Triggered by "quick plan", "fast plan", "simple plan".
    """
    def __init__(self):
        super().__init__(
            name="quick_plan",
            description="Quick planning using existing segmentations",
            category="planning",
            triggers=["quick plan", "fast plan", "simple plan", "rapid plan"],
            tool_sequence=["trajectory_planning", "seed_planning", "dose_engine", "dose_evaluation"],
            parameters={
                "seed_planning": {"mode": "rule_based"},
                "dose_engine": {"method": "cnn"},
            },
        )


class RLPlanSkill(Skill):
    """
    RL-optimized planning: uses REINFORCE for seed placement.
    Triggered by "rl plan", "RL optimization", "reinforcement learning".
    """
    def __init__(self):
        super().__init__(
            name="rl_optimized_plan",
            description="RL-optimized seed placement using REINFORCE algorithm",
            category="planning",
            triggers=["rl plan", "RL optimization", "reinforcement learning plan"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation", "plan_quality_scorer"],
            parameters={
                "seed_planning": {"mode": "rl"},
                "dose_engine": {"method": "cnn"},
            },
        )


class PancreasCTVSkill(Skill):
    """Pancreatic tumor CTV segmentation."""
    def __init__(self):
        super().__init__(
            name="pancreas_ctv_seg",
            description="Pancreatic tumor CTV segmentation using VoCo or nnU-Net",
            category="segmentation",
            triggers=["pancreas segment", "pancreatic tumor", "pancreas segmentation"],
            tool_sequence=["ctv_segmentation"],
            parameters={
                "ctv_segmentation": {"anatomy": "pancreas", "method": "voco"},
            },
        )


class PancreasOARSkill(Skill):
    """Pancreatic OAR segmentation."""
    def __init__(self):
        super().__init__(
            name="pancreas_oar_seg",
            description="Pancreatic OAR segmentation (duodenum, stomach, kidneys, spinal cord)",
            category="segmentation",
            triggers=["pancreas oar", "pancreatic organs", "pancreas OAR"],
            tool_sequence=["oar_segmentation"],
            parameters={
                "oar_segmentation": {"method": "totalsegmentator"},
            },
        )


class PancreasFullSkill(Skill):
    """Full pancreatic planning workflow."""
    def __init__(self):
        super().__init__(
            name="pancreas_full_workflow",
            description="Complete pancreatic brachytherapy workflow: seg → plan → eval",
            category="workflow",
            triggers=["pancreas workflow", "pancreatic brachytherapy", "pancreas full"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation",
                          "oar_constraint_checker", "plan_quality_scorer"],
            parameters={
                "ctv_segmentation": {"anatomy": "pancreas"},
                "oar_segmentation": {"method": "totalsegmentator"},
                "seed_planning": {"mode": "rule_based"},
            },
        )


class ProstateFullSkill(Skill):
    """Full prostate planning workflow."""
    def __init__(self):
        super().__init__(
            name="prostate_full_workflow",
            description="Complete prostate brachytherapy workflow",
            category="workflow",
            triggers=["prostate workflow", "prostate brachytherapy", "prostate full"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation",
                          "oar_constraint_checker", "plan_quality_scorer"],
            parameters={
                "ctv_segmentation": {"anatomy": "prostate"},
                "oar_segmentation": {"method": "totalsegmentator"},
            },
        )


class LiverFullSkill(Skill):
    """Full liver brachytherapy planning workflow.

    Liver tumors typically use a right-lateral or right-posterior oblique
    trajectory to avoid major vessels, gallbladder, and stomach. The
    planning_pipeline tool will pick the corresponding RAS default
    direction automatically when this skill runs.
    """
    def __init__(self):
        super().__init__(
            name="liver_full_workflow",
            description="Complete liver brachytherapy workflow: seg → lateral/posterior trajectory → seed → dose → eval",
            category="workflow",
            triggers=["liver workflow", "liver brachytherapy", "liver tumor", "hepatic", "liver full"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation",
                          "oar_constraint_checker", "plan_quality_scorer"],
            parameters={
                "ctv_segmentation": {"anatomy": "liver"},
                "oar_segmentation": {"method": "totalsegmentator"},
                "seed_planning": {"mode": "rule_based"},
                # Right-lateral approach — avoids central vessels/stomach
                "planning_pipeline": {"ref_direc": [1.0, 0.0, 0.0]},
            },
        )


class LungFullSkill(Skill):
    """Full lung brachytherapy planning workflow.

    Lung lesions are typically reached via an anterior transthoracic
    approach; avoid the scapula and posterior rib heads.
    """
    def __init__(self):
        super().__init__(
            name="lung_full_workflow",
            description="Complete lung brachytherapy workflow: seg → anterior trajectory → seed → dose → eval",
            category="workflow",
            triggers=["lung workflow", "lung brachytherapy", "lung tumor", "pulmonary", "lung full"],
            tool_sequence=["ctv_segmentation", "oar_segmentation", "trajectory_planning",
                          "seed_planning", "dose_engine", "dose_evaluation",
                          "oar_constraint_checker", "plan_quality_scorer"],
            parameters={
                "ctv_segmentation": {"anatomy": "lung"},
                "oar_segmentation": {"method": "totalsegmentator"},
                # Anterior approach (+Y)
                "planning_pipeline": {"ref_direc": [0.0, 1.0, 0.0]},
            },
        )


class DoseEvalSkill(Skill):
    """Comprehensive dose evaluation."""
    def __init__(self):
        super().__init__(
            name="comprehensive_dose_eval",
            description="Comprehensive dose evaluation with OAR constraints and quality scoring",
            category="evaluation",
            triggers=["dose eval", "evaluate dose", "check dose", "dose assessment"],
            tool_sequence=["dose_evaluation", "oar_constraint_checker", "plan_quality_scorer"],
            parameters={},
        )


class PlanOptimizationSkill(Skill):
    """Iterative plan optimization."""
    def __init__(self):
        super().__init__(
            name="plan_optimization",
            description="Iterative plan optimization to improve V100 and reduce OAR dose",
            category="optimization",
            triggers=["optimize", "improve plan", "refine plan", "plan refinement"],
            tool_sequence=["dose_evaluation", "oar_constraint_checker", "plan_refinement",
                          "dose_engine", "dose_evaluation", "plan_quality_scorer"],
            parameters={},
        )


class IntraOpReplanSkill(Skill):
    """Intra-operative replanning workflow."""
    def __init__(self):
        super().__init__(
            name="intraop_replan",
            description="Intra-operative seed detection and replanning",
            category="intraoperative",
            triggers=["intraop", "replan", "replanning", "seed check", "intra-operative"],
            tool_sequence=["seed_segmentation", "dose_evaluation", "seed_planning",
                          "dose_engine", "dose_evaluation"],
            parameters={
                "seed_planning": {"mode": "rule_based"},
            },
        )


class DICOMExportSkill(Skill):
    """DICOM RT export workflow."""
    def __init__(self):
        super().__init__(
            name="dicom_export",
            description="Export plan to DICOM RT Structure Set and RT Dose",
            category="export",
            triggers=["export dicom", "DICOM RT", "export plan"],
            tool_sequence=["dicom_rt_exporter"],
            parameters={},
        )


class ReportGenerationSkill(Skill):
    """Report generation workflow."""
    def __init__(self):
        super().__init__(
            name="report_generation",
            description="Generate planning report in JSON/HTML/Markdown format",
            category="export",
            triggers=["generate report", "create report", "report", "summary"],
            tool_sequence=["report_generator"],
            parameters={},
        )


class MultiOrganSegSkill(Skill):
    """Multi-organ segmentation using TotalSegmentator."""
    def __init__(self):
        super().__init__(
            name="multi_organ_seg",
            description="Segment all organs using TotalSegmentator (104 structures)",
            category="segmentation",
            triggers=["segment all", "multi-organ", "totalsegmentator", "all organs"],
            tool_sequence=["oar_segmentation"],
            parameters={
                "oar_segmentation": {"method": "totalsegmentator"},
            },
        )


class VoCoSegSkill(Skill):
    """VoCo-based segmentation for specific tumors."""
    def __init__(self):
        super().__init__(
            name="voco_segmentation",
            description="Tumor segmentation using VoCo pre-trained models",
            category="segmentation",
            triggers=["voco", "voco seg", "VoCo segmentation", "pretrained seg"],
            tool_sequence=["ctv_segmentation", "oar_segmentation"],
            parameters={
                "ctv_segmentation": {"method": "voco"},
                "oar_segmentation": {"method": "voco"},
            },
        )


class QualityCheckSkill(Skill):
    """Plan quality check and constraint verification."""
    def __init__(self):
        super().__init__(
            name="quality_check",
            description="Comprehensive plan quality check with clinical constraints",
            category="evaluation",
            triggers=["quality check", "check plan", "verify plan", "plan review"],
            tool_sequence=["dose_evaluation", "oar_constraint_checker", "plan_quality_scorer"],
            parameters={},
        )


class DVHAnalysisSkill(Skill):
    """DVH analysis and visualization."""
    def __init__(self):
        super().__init__(
            name="dvh_analysis",
            description="Dose-volume histogram analysis for all structures",
            category="evaluation",
            triggers=["dvh", "DVH analysis", "dose volume", "volume histogram"],
            tool_sequence=["dose_evaluation"],
            parameters={},
        )


class SelfEvolveSkill(Skill):
    """Trigger self-evolution cycle."""
    def __init__(self):
        super().__init__(
            name="self_evolve",
            description="Run self-evolution: analyze experiences, learn new skills, optimize parameters",
            category="meta",
            triggers=["evolve", "self-improve", "learn", "self-evolve", "summarize experience"],
            tool_sequence=[],
            parameters={},
        )


class CodeWriterSkill(Skill):
    """Write and register new tools via LLM."""
    def __init__(self):
        super().__init__(
            name="code_writer",
            description="Write new tool code and register it into the tool registry",
            category="meta",
            triggers=["write tool", "create tool", "new tool", "add tool", "write code"],
            tool_sequence=[],
            parameters={},
        )
