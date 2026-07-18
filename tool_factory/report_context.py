"""Shared clinical report context helpers.

The functions in this module derive deterministic report text from the current
planning memory. They do not mutate planning state and they deliberately avoid
diagnosing tumor biology from CT geometry alone.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from plans.dose_pre.model_loader import DOSE_MODEL_SCALE_GY


# Keep report links human-readable while retaining the original verified URL.
# These titles correspond to the PubMed records used by the pancreatic KB.
_VERIFIED_SOURCE_TITLES = {
    "https://pubmed.ncbi.nlm.nih.gov/39206973": "Guidelines for permanent iodine-125 seed interstitial brachytherapy for pancreatic cancer (2023 edition): The Chinese expert consensus workshop report",
    "https://pubmed.ncbi.nlm.nih.gov/30589023": "Chinese expert consensus on radioactive 125I seeds interstitial implantation brachytherapy for pancreatic cancer",
    "https://pubmed.ncbi.nlm.nih.gov/30581276": "Preliminary application of 3D-printed coplanar template for iodine-125 seed implantation therapy in patients with advanced pancreatic cancer",
}


def _source_link_item(source: Any) -> Optional[Dict[str, str]]:
    if isinstance(source, dict):
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip()
    else:
        url = str(source or "").strip()
        title = ""
    if not url.startswith(("http://", "https://")):
        return None
    normalized = url.rstrip("/")
    title = title or _VERIFIED_SOURCE_TITLES.get(normalized) or "Clinical knowledge-base reference"
    return {"title": title, "url": url}


def _retrieve(memory: Any, key: str, default: Any = None) -> Any:
    if memory is None:
        return default
    if callable(memory):
        try:
            return memory(key, default)
        except TypeError:
            value = memory(key)
            return default if value is None else value
    if hasattr(memory, "retrieve"):
        value = memory.retrieve(key)
        return default if value is None else value
    if isinstance(memory, dict):
        return memory.get(key, default)
    return default


def _as_float_list(value: Any, length: int, default: Tuple[float, ...]) -> List[float]:
    try:
        items = [float(v) for v in value]
        if len(items) >= length:
            return items[:length]
    except Exception:
        pass
    return list(default)


def _site_from_tumor_type(tumor_type: str) -> str:
    text = str(tumor_type or "").lower()
    mapping = [
        ("pancre", "pancreatic"),
        ("prostate", "prostate"),
        ("cervix", "cervical"),
        ("cervical", "cervical"),
        ("lung", "lung"),
        ("liver", "liver"),
        ("colon", "colon"),
        ("rect", "rectal"),
        ("kidney", "kidney"),
        ("renal", "kidney"),
        ("head_neck", "head_neck"),
        ("brain", "brain"),
        ("brats", "brain"),
    ]
    for pattern, site in mapping:
        if pattern in text:
            return site
    return text.replace("_tumor", "").replace("nnunet_", "").replace("voco_", "") or "unknown"


def _load_kb() -> Dict[str, Any]:
    kb_path = Path(__file__).resolve().parent / "clinical_kb" / "data" / "knowledge_base.json"
    try:
        return json.loads(kb_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _standard_for_site(kb: Dict[str, Any], site: str) -> Tuple[str, Dict[str, Any]]:
    standards = kb.get("dose_standards", {}) if isinstance(kb, dict) else {}
    if site in standards:
        return site, standards[site]
    for key, value in standards.items():
        if site and (site in key or key in site):
            return key, value
    # Composite defaults span incompatible diseases and modalities. They are
    # retained in the KB for search/explanation, but a patient report must not
    # apply them when the treatment site is unknown.
    return "unknown", {}


def _protocol_for_site(kb: Dict[str, Any], site: str) -> Dict[str, Any]:
    protocols = kb.get("treatment_protocols", {}) if isinstance(kb, dict) else {}
    for key, value in protocols.items():
        blob = f"{key} {value.get('description', '')}".lower() if isinstance(value, dict) else str(key).lower()
        if site and site.lower() in blob:
            return value if isinstance(value, dict) else {}
    return {}


def _collect_source_urls(block: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(block, dict):
        for url in block.get("source_urls", []) or []:
            if isinstance(url, str) and url.startswith("http") and url not in urls:
                urls.append(url)
        for value in block.values():
            for url in _collect_source_urls(value):
                if url not in urls:
                    urls.append(url)
    elif isinstance(block, list):
        for item in block:
            for url in _collect_source_urls(item):
                if url not in urls:
                    urls.append(url)
    return urls


def _boundary_voxel_count(mask: np.ndarray) -> int:
    padded = np.pad(mask.astype(bool), 1, mode="constant", constant_values=False)
    center = padded[1:-1, 1:-1, 1:-1]
    neighbors = (
        padded[:-2, 1:-1, 1:-1]
        & padded[2:, 1:-1, 1:-1]
        & padded[1:-1, :-2, 1:-1]
        & padded[1:-1, 2:, 1:-1]
        & padded[1:-1, 1:-1, :-2]
        & padded[1:-1, 1:-1, 2:]
    )
    return int(np.count_nonzero(center & ~neighbors))


def _world_from_index(
    index_xyz: np.ndarray,
    spacing_xyz: List[float],
    origin_xyz: List[float],
    direction_flat: List[float],
) -> np.ndarray:
    try:
        direction = np.asarray(direction_flat, dtype=float).reshape(3, 3)
    except Exception:
        direction = np.eye(3)
    return np.asarray(origin_xyz, dtype=float) + direction.dot(index_xyz * np.asarray(spacing_xyz, dtype=float))


def build_tumor_imaging_assessment(memory: Any) -> Dict[str, Any]:
    ctv_array = _retrieve(memory, "ctv_array")
    if ctv_array is None:
        ctv_array = _retrieve(memory, "ctv_label_data")
    if ctv_array is None:
        return {"available": False, "reason": "CTV mask is not available"}

    arr = np.asarray(ctv_array)
    mask = arr > 0
    coords = np.argwhere(mask)
    if coords.size == 0:
        return {"available": False, "reason": "CTV mask is empty"}

    spacing_xyz = _as_float_list(_retrieve(memory, "ct_spacing"), 3, (1.0, 1.0, 1.0))
    origin_xyz = _as_float_list(_retrieve(memory, "ct_origin"), 3, (0.0, 0.0, 0.0))
    direction = _as_float_list(_retrieve(memory, "ct_direction"), 9, tuple(np.eye(3).reshape(-1)))
    shape_zyx = _retrieve(memory, "ct_shape", arr.shape)
    if not shape_zyx:
        shape_zyx = arr.shape
    try:
        shape_zyx = [int(v) for v in list(shape_zyx)[:3]]
    except (TypeError, ValueError):
        shape_zyx = [int(v) for v in arr.shape[:3]]

    min_zyx = coords.min(axis=0)
    max_zyx = coords.max(axis=0)
    dims_vox_zyx = max_zyx - min_zyx + 1
    dims_mm_xyz = np.array([
        dims_vox_zyx[2] * spacing_xyz[0],
        dims_vox_zyx[1] * spacing_xyz[1],
        dims_vox_zyx[0] * spacing_xyz[2],
    ], dtype=float)
    centroid_zyx = coords.mean(axis=0)
    centroid_xyz = np.array([centroid_zyx[2], centroid_zyx[1], centroid_zyx[0]], dtype=float)
    centroid_world_mm = _world_from_index(centroid_xyz, spacing_xyz, origin_xyz, direction)

    center_xyz = np.array([
        (shape_zyx[2] - 1) / 2.0,
        (shape_zyx[1] - 1) / 2.0,
        (shape_zyx[0] - 1) / 2.0,
    ])
    offset_from_ct_center_mm = _world_from_index(centroid_xyz, spacing_xyz, (0, 0, 0), direction) - _world_from_index(center_xyz, spacing_xyz, (0, 0, 0), direction)

    voxel_count = int(coords.shape[0])
    voxel_volume_mm3 = float(spacing_xyz[0] * spacing_xyz[1] * spacing_xyz[2])
    volume_mm3 = float(_retrieve(memory, "ctv_volume_mm3", voxel_count * voxel_volume_mm3))
    volume_cm3 = volume_mm3 / 1000.0
    bbox_volume_mm3 = float(max(np.prod(dims_mm_xyz), 1.0))
    bbox_fill_ratio = max(0.0, min(1.0, volume_mm3 / bbox_volume_mm3))
    boundary_voxels = _boundary_voxel_count(mask)
    surface_to_volume = boundary_voxels / max(voxel_count, 1)

    if bbox_fill_ratio >= 0.55 and surface_to_volume <= 0.55:
        regularity = "relatively regular"
    elif bbox_fill_ratio >= 0.30:
        regularity = "moderately irregular"
    else:
        regularity = "irregular or lobulated"

    max_diameter_cm = float(np.max(dims_mm_xyz) / 10.0)
    equivalent_sphere_diameter_cm = float(((6.0 * volume_cm3 / math.pi) ** (1.0 / 3.0)) if volume_cm3 > 0 else 0.0)

    return {
        "available": True,
        "volume_cm3": volume_cm3,
        "voxel_count": voxel_count,
        "bbox_dimensions_cm_xyz": [float(v / 10.0) for v in dims_mm_xyz],
        "max_diameter_cm": max_diameter_cm,
        "equivalent_sphere_diameter_cm": equivalent_sphere_diameter_cm,
        "centroid_index_zyx": [float(v) for v in centroid_zyx],
        "centroid_world_cm_xyz": [float(v / 10.0) for v in centroid_world_mm],
        "offset_from_ct_center_cm_xyz": [float(v / 10.0) for v in offset_from_ct_center_mm],
        "bbox_fill_ratio": bbox_fill_ratio,
        "surface_to_volume_voxel_ratio": surface_to_volume,
        "edge_regularity": regularity,
        "interpretation_boundary": (
            "Shape descriptors are segmentation-derived planning descriptors, not a radiology diagnosis."
        ),
    }


def _prescription_gy(memory: Any) -> Tuple[float, str]:
    plan_config = _retrieve(memory, "plan_config", {}) or {}
    dose_metrics = _retrieve(memory, "dose_metrics", {}) or _retrieve(memory, "metrics", {}) or {}

    for key in ("prescription_dose_gy", "rx_gy", "prescribed_dose_gy"):
        value = plan_config.get(key)
        if value is not None:
            return float(value), f"plan_config.{key}"

    source = "plan_config.in_lowest_energy"
    raw = plan_config.get("in_lowest_energy")
    for key in ("prescription_dose", "prescribed_dose"):
        if raw is None and plan_config.get(key) is not None:
            raw = plan_config.get(key)
            source = f"plan_config.{key}"
    if raw is None:
        raw = dose_metrics.get("prescribed_dose", 1.0)
        source = "dose_metrics.prescribed_dose"
    raw = float(raw)
    if raw <= 10.0:
        return raw * DOSE_MODEL_SCALE_GY, f"{source} normalized to {DOSE_MODEL_SCALE_GY:.0f} Gy"
    return raw, source


def build_prescription_rationale(memory: Any) -> Dict[str, Any]:
    tumor_type = str(
        _retrieve(memory, "tumor_type_used", "")
        or _retrieve(memory, "tumor_type", "")
        or _retrieve(memory, "cancer_type", "")
        or _retrieve(memory, "organ", "")
        or ""
    )
    site = _site_from_tumor_type(tumor_type)
    plan_config = _retrieve(memory, "plan_config", {}) or {}
    rx_gy, rx_source = _prescription_gy(memory)

    explicit_reason = (
        plan_config.get("prescription_rationale")
        or plan_config.get("dose_rationale")
        or plan_config.get("rx_reason")
    )
    explicit_sources = plan_config.get("prescription_source_urls") or plan_config.get("source_urls") or []
    if isinstance(explicit_sources, str):
        explicit_sources = [explicit_sources]

    kb = _load_kb()
    standard_site, standard = _standard_for_site(kb, site)
    protocol = _protocol_for_site(kb, site)
    sources = []
    for block in (protocol, standard):
        for url in _collect_source_urls(block):
            if url not in sources:
                sources.append(url)
    for url in explicit_sources:
        if isinstance(url, str) and url.startswith("http") and url not in sources:
            sources.insert(0, url)

    target = {}
    oar = {}
    selected_standard = standard
    if isinstance(standard, dict):
        if "ldr" in standard and isinstance(standard["ldr"], dict):
            selected_standard = standard["ldr"]
        elif "hdr" in standard and isinstance(standard["hdr"], dict):
            selected_standard = standard["hdr"]
        elif "apbi" in standard and isinstance(standard["apbi"], dict):
            selected_standard = standard["apbi"]
        else:
            selected_standard = standard
    if isinstance(selected_standard, dict):
        target = selected_standard.get("target", {}) or {}
        oar = selected_standard.get("oar", {}) or {}

    rationale = explicit_reason
    if not rationale:
        if standard:
            rationale = (
                f"Prescription is reported as {rx_gy:.1f} Gy from {rx_source}. "
                f"When no case-specific prescription rationale is provided, BrachyBot uses the current "
                f"planning convention and evaluates target coverage relative to applicable site-specific "
                f"clinical guidance for {standard_site}."
            )
        else:
            rationale = (
                f"Prescription is reported as {rx_gy:.1f} Gy from {rx_source}. "
                "The treatment site is unknown, so no cross-site clinical threshold or dose-selection "
                "rationale has been applied. A clinician must confirm the site and prescription."
            )

    source_records = [item for item in (_source_link_item(url) for url in sources) if item]
    return {
        "prescription_gy": rx_gy,
        "prescription_source": rx_source,
        "site": standard_site,
        "rationale": rationale,
        "target_criteria": target,
        "oar_criteria": oar,
        # Keep ``sources`` as URL strings for legacy callers and expose the
        # verified human-readable title beside them for new report renderers.
        "sources": [item["url"] for item in source_records],
        "source_records": source_records,
        "clinical_boundary": (
            "A clinician-confirmed prescription dose or rationale overrides this generated text."
        ),
    }


def build_report_context(memory: Any) -> Dict[str, Any]:
    return {
        "tumor_imaging": build_tumor_imaging_assessment(memory),
        "prescription_rationale": build_prescription_rationale(memory),
    }


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "N/A"


def format_tumor_assessment_markdown(context: Dict[str, Any], lang: str = "zh") -> str:
    tumor = context.get("tumor_imaging", {})
    zh = str(lang or "").lower().startswith("zh")
    if not tumor.get("available"):
        return "### 肿瘤影像学摘要\n\n- 当前无可用 CTV mask，无法计算肿瘤几何摘要。" if zh else "### Tumor Imaging Summary\n\n- No CTV mask is available for geometric tumor summary."

    dims = tumor.get("bbox_dimensions_cm_xyz", [0, 0, 0])
    center = tumor.get("centroid_world_cm_xyz", [0, 0, 0])
    offset = tumor.get("offset_from_ct_center_cm_xyz", [0, 0, 0])
    if zh:
        lines = [
            "### 肿瘤影像学摘要",
            "",
            f"- **肿瘤体积**: {_fmt(tumor.get('volume_cm3'))} cm³；最大外接径约 {_fmt(tumor.get('max_diameter_cm'))} cm，等效球径约 {_fmt(tumor.get('equivalent_sphere_diameter_cm'))} cm。",
            f"- **三向范围**: X/Y/Z 约 {_fmt(dims[0])} / {_fmt(dims[1])} / {_fmt(dims[2])} cm。",
            f"- **位置**: CTV 中心世界坐标约 ({_fmt(center[0])}, {_fmt(center[1])}, {_fmt(center[2])}) cm；相对 CT 体数据中心偏移约 ({_fmt(offset[0])}, {_fmt(offset[1])}, {_fmt(offset[2])}) cm。",
            f"- **边缘/形态规则程度**: {tumor.get('edge_regularity')}；bbox 填充率 {_fmt(tumor.get('bbox_fill_ratio'), 3)}，表面/体素比 {_fmt(tumor.get('surface_to_volume_voxel_ratio'), 3)}。",
            f"- **判读边界**: {tumor.get('interpretation_boundary')}",
        ]
    else:
        lines = [
            "### Tumor Imaging Summary",
            "",
            f"- **Tumor volume**: {_fmt(tumor.get('volume_cm3'))} cm³; maximum bounding diameter about {_fmt(tumor.get('max_diameter_cm'))} cm; equivalent spherical diameter about {_fmt(tumor.get('equivalent_sphere_diameter_cm'))} cm.",
            f"- **Bounding dimensions**: X/Y/Z about {_fmt(dims[0])} / {_fmt(dims[1])} / {_fmt(dims[2])} cm.",
            f"- **Location**: CTV centroid world coordinates about ({_fmt(center[0])}, {_fmt(center[1])}, {_fmt(center[2])}) cm; offset from CT volume center about ({_fmt(offset[0])}, {_fmt(offset[1])}, {_fmt(offset[2])}) cm.",
            f"- **Shape regularity**: {tumor.get('edge_regularity')}; bbox fill ratio {_fmt(tumor.get('bbox_fill_ratio'), 3)}, surface/voxel ratio {_fmt(tumor.get('surface_to_volume_voxel_ratio'), 3)}.",
            f"- **Interpretation boundary**: {tumor.get('interpretation_boundary')}",
        ]
    return "\n".join(lines)


def format_prescription_rationale_markdown(context: Dict[str, Any], lang: str = "zh") -> str:
    rx = context.get("prescription_rationale", {})
    target = rx.get("target_criteria", {}) or {}
    criteria_parts = []
    for key, value in target.items():
        if key.endswith("_min") or key.endswith("_max") or key.endswith("_target"):
            criteria_parts.append(f"{key}={value}")
    sources = rx.get("sources", []) or []
    source_links = [item for item in (_source_link_item(source) for source in sources[:5]) if item]
    source_text = ", ".join(f"[{item['title']}]({item['url']})" for item in source_links)
    if str(lang or "").lower().startswith("zh"):
        lines = [
            "### 处方剂量选择依据",
            "",
            f"- **当前处方剂量**: {_fmt(rx.get('prescription_gy'), 1)} Gy。",
            f"- **选择原因**: {rx.get('rationale')}",
        ]
        if criteria_parts:
            lines.append(f"- **部位特异性目标覆盖参考**: {', '.join(criteria_parts)}。")
        if source_text:
            lines.append(f"- **来源**: {source_text}。")
        lines.append(f"- **边界**: {rx.get('clinical_boundary')}")
    else:
        lines = [
            "### Prescription Dose Rationale",
            "",
            f"- **Current prescription dose**: {_fmt(rx.get('prescription_gy'), 1)} Gy.",
            f"- **Rationale**: {rx.get('rationale')}",
        ]
        if criteria_parts:
            lines.append(f"- **Site-specific target reference**: {', '.join(criteria_parts)}.")
        if source_text:
            lines.append(f"- **Sources**: {source_text}.")
        lines.append(f"- **Boundary**: {rx.get('clinical_boundary')}")
    return "\n".join(lines)
