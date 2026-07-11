"""Read source-backed clinical standards from the authoritative KB JSON.

Only retrieval lives here. Composite-score weights are product-ranking
parameters and are deliberately kept separate from clinical limits.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

_KB_PATH = Path(__file__).resolve().parents[1] / "clinical_kb" / "data" / "knowledge_base.json"
_SITE_ALIASES = {"pancreas": "pancreatic", "cervix": "cervical"}
_MODALITY_ORDER = ("ldr", "hdr", "apbi")


def _load_standard_maps() -> Tuple[Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    if not _KB_PATH.exists():
        logger.error("Authoritative clinical KB is missing: %s", _KB_PATH)
        return {}, {}
    try:
        standards = json.loads(_KB_PATH.read_text(encoding="utf-8")).get("dose_standards", {})
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Cannot load authoritative clinical standards: %s", exc)
        return {}, {}

    targets: Dict[str, Dict[str, float]] = {}
    oars: Dict[str, Dict[str, Any]] = {}
    for site, site_entry in standards.items():
        if not isinstance(site_entry, dict):
            continue
        selected = site_entry
        if "target" not in selected and "oar" not in selected:
            selected = next(
                (site_entry[name] for name in _MODALITY_ORDER if isinstance(site_entry.get(name), dict)),
                {},
            )
        target = selected.get("target", {}) if isinstance(selected, dict) else {}
        organ_limits = selected.get("oar", {}) if isinstance(selected, dict) else {}
        if isinstance(target, dict):
            targets[site] = dict(target)
        if isinstance(organ_limits, dict):
            normalized_limits: Dict[str, Dict[str, float]] = {}
            for organ, limits in organ_limits.items():
                if not isinstance(limits, dict):
                    continue
                converted: Dict[str, float] = {}
                for key, value in limits.items():
                    normalized_key = {
                        "d2cc_gy": "d2cc",
                        "dmax_gy": "max_dose",
                        "dmean_gy": "dmean_max",
                        "dmax_pct": "max_dose_pct",
                    }.get(key, key)
                    if isinstance(value, (int, float)):
                        converted[normalized_key] = float(value)
                if converted:
                    normalized_limits[str(organ).lower()] = converted
            oars[site] = normalized_limits

    if "pancreatic" in targets:
        targets["pancreas"] = dict(targets["pancreatic"])
        oars["pancreas"] = {k: dict(v) for k, v in oars.get("pancreatic", {}).items()}
    return targets, oars


TARGET_STANDARDS, OAR_STANDARDS = _load_standard_maps()

# Product-level comparison weights. These do not claim clinical validity and
# never modify source-backed target/OAR limits.
WEIGHTS = {
    "coverage": 0.40,
    "homogeneity": 0.20,
    "oar_sparing": 0.30,
    "conformance": 0.10,
}
REPLAN_TRIGGER_SCORE = 60.0
REPLAN_TRIGGER_VIOLATIONS = 1


def _site_key(organ: str) -> str:
    key = (organ or "").lower().replace("-", "_").replace(" ", "_")
    return _SITE_ALIASES.get(key, key)


def get_target_standard(organ: str = "") -> Dict[str, float]:
    """Return standards only for an explicitly known site."""
    return dict(TARGET_STANDARDS.get(_site_key(organ), {}))


def get_oar_standard(organ: str = "") -> Dict[str, Dict[str, float]]:
    """Return OAR limits only for an explicitly known site."""
    return {k: dict(v) for k, v in OAR_STANDARDS.get(_site_key(organ), {}).items()}


def composite_score(coverage: float, homogeneity: float,
                    oar: float, conformance: float) -> float:
    return (
        WEIGHTS["coverage"] * coverage
        + WEIGHTS["homogeneity"] * homogeneity
        + WEIGHTS["oar_sparing"] * oar
        + WEIGHTS["conformance"] * conformance
    )


def should_replan(score: float, num_violations: int) -> bool:
    """Product workflow flag; never a substitute for clinical approval."""
    return score < REPLAN_TRIGGER_SCORE or num_violations > REPLAN_TRIGGER_VIOLATIONS
