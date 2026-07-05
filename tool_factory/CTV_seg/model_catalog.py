"""
CTV model catalog.

This module records which CT-based CTV segmentation resources are actually
usable from BrachyBot, which ones are external experimental candidates, and
which public datasets should be used for new nnU-Net training.
"""

from __future__ import annotations

import os
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
        "local_expected_path": "VoCo/pancreatic_tumor/Dataset005_Pancreas/nnUNetTrainer__nnUNetPlans__3d_fullres",
        "notes": "Native BrachyBot nnU-Net v2 path. It is the only CTV model treated as production-path when weights are installed.",
        "sources": [
            "https://medicaldecathlon.com/",
            "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/monaitoolkit/models/monai_pancreas_ct_dints_segmentation",
        ],
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
            "https://huggingface.co/",
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
    for item in CTV_MODEL_CATALOG:
        entry = dict(item)
        rel = entry.get("local_expected_path")
        if isinstance(rel, str) and rel:
            entry["local_path"] = os.path.join(repo_root, rel)
            entry["local_present"] = os.path.exists(entry["local_path"])
        else:
            entry["local_present"] = False
        items.append(entry)
    return items


def filter_catalog(site: Optional[str] = None, include_experimental: bool = True) -> List[Dict[str, object]]:
    """Filter catalog entries by tumor site and experimental visibility."""
    site_norm = (site or "").strip().lower()
    items = catalog_with_local_status()
    if site_norm:
        items = [m for m in items if str(m.get("site", "")).lower() == site_norm]
    if not include_experimental:
        items = [m for m in items if not str(m.get("status", "")).startswith("external_")]
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
