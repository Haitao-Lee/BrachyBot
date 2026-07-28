"""
CTV model catalog.

This module records which CT-based CTV segmentation resources are actually
usable from BrachyBot, which ones are external experimental candidates, and
which public datasets should be used for new nnU-Net training.
"""

from __future__ import annotations

import os
import shutil
from typing import Dict, Iterable, List, Optional

from tool_factory import BaseTool, ToolResult


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
        "status": "external_research_runtime_requires_opt_in",
        "tool": "ctv_segmentation",
        "tumor_type": "biomedparse_liver_tumor",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 text-guided candidate; requires the isolated official runtime and clinician contour review.",
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
        "status": "external_research_runtime_requires_opt_in",
        "tool": "ctv_segmentation",
        "tumor_type": "biomedparse_kidney_lesion",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 lesion candidate; requires the isolated official runtime and clinician contour review.",
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
        "status": "external_research_runtime_requires_opt_in",
        "tool": "ctv_segmentation",
        "tumor_type": "biomedparse_lung_lesion",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 lesion candidate; requires the isolated official runtime and clinician contour review.",
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
        "status": "external_research_runtime_requires_opt_in",
        "tool": "ctv_segmentation",
        "tumor_type": "biomedparse_colon_primary",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 text-guided candidate; requires the isolated official runtime and clinician contour review.",
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
        "status": "external_research_runtime_requires_opt_in",
        "tool": "ctv_segmentation",
        "tumor_type": "biomedparse_head_neck_cancer",
        "runtime_root_env": "BIOMEDPARSE_ROOT",
        "checkpoint_env": "BIOMEDPARSE_V2_CHECKPOINT",
        "notes": "Official BiomedParse v2 text-guided candidate; requires the isolated official runtime and clinician contour review.",
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
        "tool": "ctv_segmentation",
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
    # This import is lightweight because the BiomedParse adapter imports its
    # official torch/Hydra stack only inside the first inference call.
    try:
        from .biomedparse_v2 import (
            _availability as _biomedparse_availability,
            _validation_records as _biomedparse_validation_records,
        )
        biomedparse_probe = _biomedparse_availability()
        biomedparse_available = bool(biomedparse_probe.get("available"))
        biomedparse_validation = _biomedparse_validation_records()
    except Exception:
        biomedparse_probe = {"available": False, "missing": ["BiomedParse runtime probe failed"]}
        biomedparse_available = False
        biomedparse_validation = {}
    fallback_for = {
        "voco_liver": "biomedparse_liver_tumor",
        "voco_kidney": "biomedparse_kidney_lesion",
        "voco_lung": "biomedparse_lung_lesion",
        "voco_colon": "biomedparse_colon_primary",
    }
    for item in CTV_MODEL_CATALOG:
        entry = dict(item)
        rel = entry.get("local_expected_path")
        if isinstance(rel, str) and rel:
            entry["local_path"] = os.path.join(repo_root, rel)
            entry["local_present"] = os.path.exists(entry["local_path"])
        else:
            entry["local_present"] = False
        if str(entry.get("tumor_type", "")) in fallback_for:
            entry["fallback_tumor_type"] = fallback_for[str(entry["tumor_type"])]
            entry["fallback_available"] = biomedparse_available
        if entry.get("runtime_root_env") == "BIOMEDPARSE_ROOT":
            entry["runtime_available"] = biomedparse_available
        tumor_type = str(entry.get("tumor_type", ""))
        entry["technical_call_chain_passed"] = False
        entry["space_alignment_passed"] = False
        entry["result_save_path_passed"] = False
        entry["data_tree_viewer_passed"] = False
        entry["clinical_case_validation"] = False

        if tumor_type == "nnunet_pancreatic":
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
        elif tumor_type.startswith("biomedparse_"):
            validation = biomedparse_validation.get(tumor_type, {})
            entry.update({
                "technical_call_chain_passed": bool(validation.get("technical_call_chain_passed")),
                "space_alignment_passed": bool(validation.get("space_alignment_passed")),
                "result_save_path_passed": bool(validation.get("result_save_path_passed")),
                "data_tree_viewer_passed": bool(validation.get("data_tree_viewer_passed")),
                "clinical_case_validation": False,
                "last_validation": validation.get("checked_at"),
            })
            if biomedparse_available:
                entry.update({
                    "capability_state": "experimental",
                    "capability_color": "orange",
                    "capability_reason": (
                        "BiomedParse v2 is installed and wired for research use; "
                        "clinical contour quality is not validated."
                    ),
                    "callable": True,
                })
            else:
                missing = ", ".join(str(value) for value in biomedparse_probe.get("missing", []))
                entry.update({
                    "capability_state": "unavailable",
                    "capability_color": "red",
                    "capability_reason": f"BiomedParse v2 runtime is unavailable: {missing}.",
                    "callable": False,
                })
        elif tumor_type == "prostate_tumor":
            runtime_present = bool(shutil.which("TotalSegmentator"))
            entry.update({
                "capability_state": "experimental" if runtime_present else "unavailable",
                "capability_color": "orange" if runtime_present else "red",
                "capability_reason": (
                    "Whole-prostate target segmentation is available; this is not lesion-level tumor CTV."
                    if runtime_present
                    else "TotalSegmentator is missing; only an uploaded clinician-approved target is available."
                ),
                "callable": runtime_present,
                "target_semantics": "whole_prostate_target_not_lesion",
            })
        else:
            entry.update({
                "capability_state": "experimental" if entry["local_present"] else "disabled",
                "capability_color": "orange" if entry["local_present"] else "gray",
                "capability_reason": (
                    "Optional local research model is installed but not clinically validated."
                    if entry["local_present"]
                    else "Research entry is not installed or not exposed in the clinical selector."
                ),
                "callable": bool(entry["local_present"]),
            })
        items.append(entry)
    return items


def filter_catalog(
    site: Optional[str] = None,
    include_experimental: bool = True,
    *,
    for_ui: bool = False,
) -> List[Dict[str, object]]:
    """Filter catalog entries by site, visibility, and research status.

    ``ctv_model_catalog`` intentionally exposes the complete audit catalog so
    an operator can inspect research resources.  The web selector uses
    ``for_ui=True`` and must not expose the unvalidated pancreatic VoCo
    alternative as a second production choice.
    """
    site_norm = (site or "").strip().lower()
    items = catalog_with_local_status()
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
