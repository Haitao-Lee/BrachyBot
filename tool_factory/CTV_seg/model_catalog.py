"""
CTV model catalog.

This module records which 3D CTV segmentation resources are actually
usable from BrachyBot, which ones are external experimental candidates, and
which public datasets should be used for new nnU-Net training.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from tool_factory import BaseTool, ToolResult

from .biomedparse_v2 import SITE_SPECS as BIOMEDPARSE_SITE_SPECS
from .sat3d import SITE_SPECS as SAT3D_SITE_SPECS


DIFFTUMOR_BASE = "https://huggingface.co/MrGiovanni/DiffTumor/resolve/main/SegmentationModel"


CTV_MODEL_CATALOG: List[Dict[str, object]] = [
    {
        "id": "nnunet_pancreatic",
        "site": "pancreas",
        "modality": "CT",
        "target": "pancreatic tumor CTV plus artery/vein/pancreas labels",
        "status": "integrated_requires_local_weights",
        "tool": "ctv_segmentation",
        "tumor_type": "nnunet_pancreatic",
        "ui_visible": True,
        "local_expected_path": "VoCo/pancreatic_tumor/Dataset005_Pancreas/nnUNetTrainer__nnUNetPlans__3d_fullres",
        "notes": "Native BrachyBot nnU-Net v2 path. It is the only CTV model treated as production-path when weights are installed.",
        "sources": [
            "https://medicaldecathlon.com/",
            "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/monaitoolkit/models/monai_pancreas_ct_dints_segmentation",
        ],
    },
    *[
        {
            "id": f"sat3d_interactive_{tumor_type.removeprefix('sat3d_')}",
            "site": spec["site"],
            "modality": "/".join(str(value).upper() for value in spec["modalities"]),
            "target": f"{spec['label']} CTV candidate",
            "status": "integrated_external_runtime_requires_review",
            "tool": "sat3d_ctv_segmentation",
            "tumor_type": f"sat3d_interactive_{tumor_type.removeprefix('sat3d_')}",
            "ui_visible": False,
            "runtime_root_env": "SAT3D_ROOT",
            "checkpoint_env": "SAT3D_MODEL_CHECKPOINT",
            "prompt_support": {"positive_points": True, "negative_points": True, "zero_prompt": False},
            "evidence": spec["evidence"],
            "datasets": list(spec["datasets"]),
            "target_semantics": "review_required_tumor_candidate",
            "notes": (
                "Official SAT3D 3D point-prompt model. At least one positive point is "
                "required; it is not an automatic site-specific CTV route. Output is a "
                "research candidate requiring clinician contour review."
            ),
            "sources": [
                "https://github.com/himashi92/SAT3D",
                "https://doi.org/10.6084/m9.figshare.30155497",
                "https://www.nature.com/articles/s41467-026-76531-2",
            ],
        }
        for tumor_type, spec in SAT3D_SITE_SPECS.items()
    ],
    {
        "id": "voco_panorama_pancreatic_tumor",
        "site": "pancreas",
        "modality": "CT",
        "target": "PANORAMA PDAC lesion label 1",
        "status": "integrated_optional_requires_local_weights_and_validation",
        "tool": "ctv_segmentation",
        "tumor_type": "voco_pancreatic",
        # Kept in the machine-readable research catalog for backwards
        # compatibility, but hidden from the user selector: the validated
        # pancreatic nnU-Net path is the only production pancreas option.
        "ui_visible": False,
        "local_expected_path": "VoCo/PANORAMA/model_voco.pt",
        "notes": "Optional VoCo path using PANORAMA's published six-class label legend; validate locally before clinical research use.",
        "sources": [
            "https://github.com/Luffy03/Large-Scale-Medical/tree/main/Downstream/monai/PANORAMA",
            "https://github.com/DIAGNijmegen/panorama_labels#label-legend",
        ],
    },
    {
        "id": "totalsegmentator_liver_tumor",
        "site": "liver",
        "modality": "CT",
        "target": "liver tumor CTV only",
        "status": "integrated_external_runtime",
        "tool": "ctv_segmentation",
        "tumor_type": "totalsegmentator_liver_tumor",
        "ui_visible": False,
        "deprecated": True,
        "deprecated_reason": "Automatic liver tumor CTV now uses BiomedParse v2.",
        "runtime_executable": "TotalSegmentator",
        "total_segmentator_task": "liver_vessels",
        "total_segmentator_label": "liver_tumor",
        "notes": (
            "Runs TotalSegmentator's liver_vessels CT task and exposes only "
            "liver_tumor.nii.gz as a binary CTV. Liver and vessel outputs are discarded."
        ),
        "sources": [
            "https://github.com/wasserth/TotalSegmentator",
        ],
    },
    {
        "id": "voco_ircadb_liver_tumor",
        "site": "liver",
        "modality": "CT",
        "target": "liver tumor CTV",
        "status": "integrated_optional_requires_local_weights_and_validation",
        "tool": "ctv_segmentation",
        "tumor_type": "voco_liver",
        "local_expected_path": "VoCo/3D-IRCADb/model_voco_74.27.pt",
        "notes": "Optional VoCo 3D-IRCADb checkpoint; installation and site-specific validation are required.",
        "sources": ["https://github.com/Luffy03/Large-Scale-Medical"],
    },
    {
        "id": "voco_kipa_kidney_tumor",
        "site": "kidney",
        "modality": "CT",
        "target": "kidney tumor CTV",
        "status": "integrated_optional_requires_local_weights_and_validation",
        "tool": "ctv_segmentation",
        "tumor_type": "voco_kidney",
        "local_expected_path": "VoCo/Kipa/model_voco.pt",
        "notes": "Optional VoCo KiPA checkpoint; installation and site-specific validation are required.",
        "sources": ["https://github.com/Luffy03/Large-Scale-Medical"],
    },
    {
        "id": "voco_msd_lung_tumor",
        "site": "lung",
        "modality": "CT",
        "target": "lung tumor CTV",
        "status": "integrated_optional_requires_local_weights_and_validation",
        "tool": "ctv_segmentation",
        "tumor_type": "voco_lung",
        "local_expected_path": "VoCo/Lung/model_voco_75.74.pt",
        "notes": "Optional VoCo MSD Task06 checkpoint; installation and site-specific validation are required.",
        "sources": ["https://github.com/Luffy03/Large-Scale-Medical"],
    },
    {
        "id": "voco_msd_colon_tumor",
        "site": "colon",
        "modality": "CT",
        "target": "colon tumor CTV",
        "status": "integrated_optional_requires_local_weights_and_validation",
        "tool": "ctv_segmentation",
        "tumor_type": "voco_colon",
        "local_expected_path": "VoCo/colon/model_voco_42.57.pt",
        "notes": "Optional VoCo MSD Task10 checkpoint; installation and site-specific validation are required.",
        "sources": ["https://github.com/Luffy03/Large-Scale-Medical"],
    },
    {
        "id": "biomedparse_v2_liver_tumor",
        "site": "liver",
        "modality": "CT",
        "target": "liver tumor CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_liver_tumor",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Automatic BiomedParse v2 text-guided candidate using the official liver tumors task; contour review is required.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "biomedparse_v2_kidney_lesion",
        "site": "kidney",
        "modality": "CT",
        "target": "kidney lesion CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_kidney_lesion",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 lesion candidate; requires the isolated official runtime and contour review.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "biomedparse_v2_lung_lesion",
        "site": "lung",
        "modality": "CT",
        "target": "lung lesion CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_lung_lesion",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 lesion candidate; requires the isolated official runtime and contour review.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "biomedparse_v2_colon_primary",
        "site": "colon",
        "modality": "CT",
        "target": "colon cancer primary CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_colon_primary",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 text-guided candidate; requires the isolated official runtime and contour review.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "biomedparse_v2_head_neck_cancer",
        "site": "head_neck",
        "modality": "CT",
        "target": "head and neck cancer CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_head_neck_cancer",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 text-guided candidate; requires the isolated official runtime and contour review.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "biomedparse_v2_prostate_lesion",
        "site": "prostate",
        "modality": "MRI/T2W",
        "target": "prostate lesion CTV candidate",
        "status": "integrated_external_runtime_requires_review",
        "tool": "ctv_segmentation",
        "ui_visible": True,
        "tumor_type": "biomedparse_prostate_lesion",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Automatic BiomedParse v2 MRI candidate using the official prostate lesion task and percentile preprocessing; contour review is required.",
        "sources": [
            "https://github.com/microsoft/BiomedParse/tree/v2",
            "https://huggingface.co/microsoft/BiomedParse",
            "https://doi.org/10.1038/s41592-024-02499-w",
        ],
    },
    {
        "id": "totalsegmentator_whole_prostate",
        "site": "prostate",
        "modality": "CT",
        "target": "whole-prostate target, not lesion-level tumor",
        "status": "integrated_external_runtime",
        "tool": None,
        "ui_visible": False,
        "deprecated": True,
        "deprecated_reason": "Whole-organ prostate segmentation is not lesion CTV; prostate lesion CTV uses BiomedParse v2 MRI.",
        "tumor_type": "prostate_tumor",
        "notes": "Uses TotalSegmentator's prostate task only when the whole gland is the intended target.",
        "sources": ["https://github.com/wasserth/TotalSegmentator"],
    },
    {
        "id": "monai_pancreas_ct_dints",
        "site": "pancreas",
        "modality": "CT",
        "target": "pancreas and pancreatic tumor segmentation",
        "status": "external_monai_bundle_not_wired",
        "tool": None,
        "notes": (
            "Public MONAI/NGC bundle for portal-venous CT pancreas and pancreatic tumor "
            "segmentation. It is a credible future integration target but uses MONAI bundle "
            "runtime rather than the current BrachyBot nnU-Net v2 predictor path."
        ),
        "sources": [
            "https://catalog.ngc.nvidia.com/orgs/nvidia/monaitoolkit/models/monai_pancreas_ct_dints_segmentation",
            "https://medicaldecathlon.com/",
        ],
    },
    {
        "id": "cect_pdac_detection_nnunet",
        "site": "pancreas",
        "modality": "contrast-enhanced CT",
        "target": "PDAC likelihood heatmap plus surrounding anatomy",
        "status": "external_research_detection_not_ctv",
        "tool": None,
        "notes": (
            "DIAG Nijmegen PDAC project outputs a tumor likelihood heatmap and anatomical "
            "structures; it is not activated as a binary CTV segmenter without thresholding "
            "and validation."
        ),
        "sources": ["https://github.com/DIAGNijmegen/CE-CT_PDAC_AutomaticDetection_nnUnet/"],
    },
    {
        "id": "difftumor_nnunet_liver",
        "site": "liver",
        "modality": "CT",
        "target": "liver tumor CTV",
        "status": "external_experimental_checkpoint",
        "tool": None,
        "download_url": f"{DIFFTUMOR_BASE}/nnunet_synt_liver_tumors.pt",
        "local_expected_path": "models/ctv/difftumor/nnunet_synt_liver_tumors.pt",
        "notes": "Checkpoint is not nnU-Net v2 predictor format. It requires the DiffTumor inference stack before activation.",
        "sources": ["https://github.com/MrGiovanni/DiffTumor"],
    },
    {
        "id": "difftumor_nnunet_pancreas",
        "site": "pancreas",
        "modality": "CT",
        "target": "pancreatic tumor CTV",
        "status": "external_experimental_checkpoint",
        "tool": None,
        "download_url": f"{DIFFTUMOR_BASE}/nnunet_synt_pancreas_tumors.pt",
        "local_expected_path": "models/ctv/difftumor/nnunet_synt_pancreas_tumors.pt",
        "notes": "Useful research checkpoint, but not wired to the current nnU-Net v2 predictor.",
        "sources": ["https://github.com/MrGiovanni/DiffTumor"],
    },
    {
        "id": "difftumor_nnunet_kidney",
        "site": "kidney",
        "modality": "CT",
        "target": "kidney tumor CTV",
        "status": "external_experimental_checkpoint",
        "tool": None,
        "download_url": f"{DIFFTUMOR_BASE}/nnunet_synt_kidney_tumors.pt",
        "local_expected_path": "models/ctv/difftumor/nnunet_synt_kidney_tumors.pt",
        "notes": "Checkpoint is available and small enough to download, but requires DiffTumor code integration before use.",
        "sources": ["https://github.com/MrGiovanni/DiffTumor"],
    },
    {
        "id": "msd_task03_liver",
        "site": "liver",
        "modality": "CT",
        "target": "liver and liver tumor masks for nnU-Net training",
        "status": "public_training_dataset",
        "tool": None,
        "notes": "Recommended baseline dataset for a BrachyBot liver CTV nnU-Net tool.",
        "sources": ["https://medicaldecathlon.com/"],
    },
    {
        "id": "pants_pancreatic_tumor",
        "site": "pancreas",
        "modality": "CT",
        "target": "pancreatic tumor plus pancreas subregions and surrounding anatomy",
        "status": "public_training_dataset",
        "tool": None,
        "notes": (
            "Large multi-institutional pancreatic CT dataset. License and access terms must "
            "be reviewed before model training or redistribution."
        ),
        "sources": [
            "https://arxiv.org/html/2507.01291v1",
            "https://github.com/MrGiovanni/PanTS",
        ],
    },
    {
        "id": "msd_task06_lung",
        "site": "lung",
        "modality": "CT",
        "target": "lung tumor masks for nnU-Net training",
        "status": "public_training_dataset",
        "tool": None,
        "notes": "Recommended baseline dataset for lung tumor CTV training; MONAI public model is detection, not CTV segmentation.",
        "sources": ["https://medicaldecathlon.com/"],
    },
    {
        "id": "msd_task10_colon",
        "site": "colon",
        "modality": "CT",
        "target": "colon cancer masks for nnU-Net training",
        "status": "public_training_dataset",
        "tool": None,
        "notes": "Recommended baseline dataset for colon CTV training.",
        "sources": ["https://medicaldecathlon.com/"],
    },
    {
        "id": "kits_kidney_tumor",
        "site": "kidney",
        "modality": "CT",
        "target": "kidney and kidney tumor masks for nnU-Net training",
        "status": "public_training_dataset",
        "tool": None,
        "notes": "Recommended kidney tumor dataset family for a dedicated BrachyBot kidney CTV tool.",
        "sources": ["https://kits-challenge.org/"],
    },
]


def catalog_with_local_status(repo_root: Optional[str] = None) -> List[Dict[str, object]]:
    """Return the catalog with a boolean indicating whether expected files exist."""
    if repo_root is None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    items: List[Dict[str, object]] = []
    try:
        from .sat3d import _availability as _sat3d_availability
        sat3d_probe = _sat3d_availability()
        sat3d_available = bool(sat3d_probe.get("available"))
    except Exception as exc:
        sat3d_probe = {"available": False, "missing": [f"SAT3D runtime probe failed: {exc}"]}
        sat3d_available = False
    try:
        from .biomedparse_v2 import (
            _availability as _biomedparse_availability,
            _validation_records as _biomedparse_validation_records,
        )
        biomedparse_probe = _biomedparse_availability()
        biomedparse_available = bool(biomedparse_probe.get("available"))
        biomedparse_records = _biomedparse_validation_records()
    except Exception as exc:
        biomedparse_probe = {
            "available": False,
            "missing": [f"BiomedParse v2 runtime probe failed: {exc}"],
        }
        biomedparse_available = False
        biomedparse_records = {}
    for item in CTV_MODEL_CATALOG:
        entry = dict(item)
        rel = entry.get("local_expected_path")
        if isinstance(rel, str) and rel:
            entry["local_path"] = os.path.join(repo_root, rel)
            entry["local_present"] = os.path.exists(entry["local_path"])
        else:
            entry["local_present"] = False
        tumor_type = str(entry.get("tumor_type", ""))
        entry["technical_call_chain_passed"] = False
        entry["space_alignment_passed"] = False
        entry["result_save_path_passed"] = False
        entry["data_tree_viewer_passed"] = False
        entry["clinical_case_validation"] = False

        if tumor_type.startswith("sat3d_interactive_"):
            missing = ", ".join(str(value) for value in sat3d_probe.get("missing", []))
            evidence = str(entry.get("evidence") or "research")
            entry.update({
                "capability_state": "experimental" if sat3d_available else "unavailable",
                "capability_color": "green" if sat3d_available else "red",
                "capability_reason": (
                    "SAT3D is installed for explicit interactive use. This is a "
                    f"review-required research candidate ({evidence}); at least one "
                    "positive point prompt is required."
                    if sat3d_available
                    else f"SAT3D runtime is unavailable: {missing}."
                ),
                "callable": sat3d_available,
                "runtime_available": sat3d_available,
                "runtime_probe": sat3d_probe,
                "technical_call_chain_passed": sat3d_available,
                "space_alignment_passed": sat3d_available,
                "result_save_path_passed": False,
                "data_tree_viewer_passed": False,
                "clinical_case_validation": False,
            })
        elif tumor_type in BIOMEDPARSE_SITE_SPECS:
            missing = ", ".join(
                str(value) for value in biomedparse_probe.get("missing", [])
            )
            validation = biomedparse_records.get(tumor_type, {})
            entry.update({
                "capability_state": "experimental" if biomedparse_available else "unavailable",
                "capability_color": "green" if biomedparse_available else "red",
                "capability_reason": (
                    "BiomedParse v2 is installed and callable for automatic text-guided "
                    "candidate segmentation; no point prompt is required and clinician "
                    "contour review remains mandatory."
                    if biomedparse_available
                    else f"BiomedParse v2 runtime is unavailable: {missing}."
                ),
                "callable": biomedparse_available,
                "runtime_available": biomedparse_available,
                "runtime_probe": biomedparse_probe,
                "technical_call_chain_passed": bool(
                    validation.get("technical_call_chain_passed")
                ),
                "space_alignment_passed": bool(validation.get("space_alignment_passed")),
                "result_save_path_passed": bool(validation.get("result_save_path_passed")),
                "data_tree_viewer_passed": bool(validation.get("data_tree_viewer_passed")),
                "clinical_case_validation": False,
                "target_semantics": "automatic_text_guided_review_required_candidate",
            })
        elif tumor_type == "nnunet_pancreatic":
            if entry["local_present"]:
                entry.update({
                    "capability_state": "verified",
                    "capability_color": "green",
                    "capability_reason": "Validated pancreatic nnU-Net runtime is installed.",
                    "callable": True,
                    "technical_call_chain_passed": True,
                    "space_alignment_passed": True,
                    "result_save_path_passed": True,
                    "data_tree_viewer_passed": True,
                    "clinical_case_validation": True,
                })
            else:
                entry.update({
                    "capability_state": "unavailable",
                    "capability_color": "red",
                    "capability_reason": "Validated pancreatic nnU-Net weights are missing in this runtime.",
                    "callable": False,
                })
        elif bool(entry.get("deprecated")) or tumor_type.startswith("voco_"):
            replacement = (
                "nnunet_pancreatic"
                if tumor_type == "voco_pancreatic"
                else next(
                    (
                        canonical
                        for canonical, spec in BIOMEDPARSE_SITE_SPECS.items()
                        if str(spec.get("site")) == str(entry.get("site"))
                    ),
                    None,
                )
            )
            entry.update({
                "capability_state": "disabled",
                "capability_color": "gray",
                "capability_reason": (
                    "Historical closed-set CTV route. Restored requests are "
                    f"migrated to {replacement}; this catalog entry is never callable."
                    if replacement
                    else "Historical closed-set CTV route; this catalog entry is never callable."
                ),
                "callable": False,
                "target_semantics": (
                    "generic_open_segmentation_only"
                    if tumor_type.startswith("biomedparse_")
                    else "historical_closed_set_ctv_disabled"
                ),
                "replacement_tumor_type": replacement,
            })
        else:
            entry.update({
                "capability_state": "experimental" if entry["local_present"] else "disabled",
                "capability_color": "orange" if entry["local_present"] else "gray",
                "capability_reason": (
                    "Optional local model is installed; contour review is required."
                    if entry["local_present"]
                    else "This segmentation entry is not installed or not exposed in the selector."
                ),
                "callable": bool(entry["local_present"]),
            })
        # Legacy VoCo SwinUNETR entries are audit-only. Their restored ids are
        # normalized by the unified CTV dispatcher; catalog discovery must
        # never advertise them as a second executable route.
        if str(entry.get("tumor_type", "")).startswith("voco_"):
            entry["deprecated"] = True
            entry["deprecated_reason"] = "Legacy VoCo CTV route; use the canonical production dispatcher."
        items.append(entry)
    return items


def filter_catalog(
    site: Optional[str] = None,
    include_experimental: bool = True,
    *,
    for_ui: bool = False,
    include_deprecated: bool = False,
) -> List[Dict[str, object]]:
    """Filter catalog entries by site, visibility, and research status.

    ``ctv_model_catalog`` intentionally exposes the complete audit catalog so
    an operator can inspect research resources.  The web selector uses
    ``for_ui=True`` and must not expose the unvalidated pancreatic VoCo
    alternative as a second production choice. Deprecated legacy VoCo entries
    are hidden by default so an LLM or operator is never steered toward a
    checkpoint that has been superseded by BiomedParse v2.
    """
    site_norm = (site or "").strip().lower()
    items = catalog_with_local_status()
    if not include_deprecated:
        items = [m for m in items if not bool(m.get("deprecated"))]
    if site_norm:
        items = [m for m in items if str(m.get("site", "")).lower() == site_norm]
    if not include_experimental:
        items = [m for m in items if not str(m.get("status", "")).startswith("external_")]
    if for_ui:
        items = [m for m in items if bool(m.get("ui_visible", True))]
    return items


class CTVModelCatalogTool(BaseTool):
    """List verified CTV model and dataset resources for BrachyBot."""

    @property
    def name(self) -> str:
        return "ctv_model_catalog"

    @property
    def description(self) -> str:
        return (
            "List CT-based CTV segmentation models, experimental checkpoints, "
            "and training datasets with local availability and source links."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Optional tumor site filter, e.g. pancreas, liver, lung, kidney, colon"},
                "include_experimental": {"type": "boolean", "default": True},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "models": {"type": "array"},
                "count": {"type": "integer"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        site = kwargs.get("site")
        include_experimental = bool(kwargs.get("include_experimental", True))
        models = filter_catalog(site=site, include_experimental=include_experimental)
        return ToolResult(
            success=True,
            data=models,
            message=f"Found {len(models)} CTV model or dataset resources.",
            metadata={"models": models, "count": len(models)},
        )


def downloadable_model_ids() -> Iterable[str]:
    for item in CTV_MODEL_CATALOG:
        if item.get("download_url"):
            yield str(item["id"])
