"""
Clinical Standards Mirror for Brachytherapy Plan Quality
=======================================================

This module mirrors selected target-coverage and OAR constraint values from the
curated clinical knowledge base for deterministic scoring and safety checks.
Use ``clinical_kb`` for source-level citations, source freshness, and guideline
interpretation. Do not add PMID/DOI claims here without verifying and adding the
same source to the knowledge base.

All dose values are in Gy unless a key explicitly uses ``_pct``. D90 percentage
values are fractions of prescription dose.
"""

from typing import Dict, Any


# Per-organ target coverage standards.
# ``d90_min_pct`` is the minimum D90 as a fraction of prescribed dose
# (i.e. 1.0 == 100% of prescription). ``v100_min`` is the minimum
# fraction of CTV receiving >= 100% of prescription.
#
# Source citations are stored in tool_factory/clinical_kb/data/knowledge_base.json and the raw source index.
TARGET_STANDARDS: Dict[str, Dict[str, float]] = {
    "prostate":  {"d90_min_pct": 1.00, "v100_min": 0.95, "v150_max": 0.50, "v200_max": 0.35},
    "pancreas":  {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "pancreatic": {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "liver":     {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "lung":      {"d90_min_pct": 1.00, "v100_min": 0.95, "v150_max": 0.50, "v200_max": 0.30},
    "kidney":    {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "colon":     {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "head_neck": {"d90_min_pct": 1.00, "v100_min": 0.95, "v150_max": 0.50, "v200_max": 0.25},
    "cervical":  {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.60, "v200_max": 0.35},
    "breast":    {"d90_min_pct": 0.90, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "esophageal": {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "btcv":      {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.30},
    "default":   {"d90_min_pct": 1.00, "v100_min": 0.90, "v150_max": 0.50, "v200_max": 0.35},
}


# Per-organ OAR constraints (Gy). Values drawn from GEC-ESTRO / ABS
# consensus statements. Keys are normalized lowercase organ names.
#
# Source citations are stored in tool_factory/clinical_kb/data/knowledge_base.json and the raw source index.
OAR_STANDARDS: Dict[str, Dict[str, Any]] = {
    "prostate": {
        "urethra":  {"max_dose_pct": 120, "d10_pct_max": 120},
        "rectum":   {"d2cc": 75.0, "max_dose": 100.0},
        "bladder":  {"d2cc": 90.0, "max_dose": 120.0},
    },
    "cervical": {
        "bladder":     {"d2cc": 90.0},
        "rectum":      {"d2cc": 75.0},
        "sigmoid":     {"d2cc": 70.0},
        "small_bowel": {"d2cc": 75.0},
    },
    "pancreas": {
        "duodenum": {"d2cc": 55.0, "max_dose": 75.0},
        "stomach":  {"d2cc": 55.0, "max_dose": 75.0},
        "bowel":    {"d2cc": 55.0, "max_dose": 75.0},
        "artery":   {"d2cc": 80.0, "max_dose": 100.0},
        "vein":     {"d2cc": 80.0, "max_dose": 100.0},
    },
    "pancreatic": {
        "duodenum": {"d2cc": 55.0, "max_dose": 75.0},
        "stomach":  {"d2cc": 55.0, "max_dose": 75.0},
        "bowel":    {"d2cc": 55.0, "max_dose": 75.0},
        "artery":   {"d2cc": 80.0, "max_dose": 100.0},
        "vein":     {"d2cc": 80.0, "max_dose": 100.0},
    },
    "liver": {
        "stomach":      {"d2cc": 50.0, "max_dose": 65.0},
        "duodenum":     {"d2cc": 50.0, "max_dose": 65.0},
        "colon":        {"d2cc": 50.0, "max_dose": 65.0},
        "kidney":       {"d2cc": 18.0, "max_dose": 25.0},
        "normal_liver": {"dmean_max": 30.0},
    },
    "lung": {
        "spinal_cord": {"max_dose": 45.0},
        "heart":       {"d2cc": 40.0, "max_dose": 60.0},
        "esophagus":   {"d2cc": 55.0, "max_dose": 60.0},
        "trachea":     {"d2cc": 70.0, "max_dose": 75.0},
    },
    "head_neck": {
        "spinal_cord": {"max_dose": 45.0},
        "brainstem":   {"max_dose": 54.0},
        "parotid":     {"dmean_max": 26.0},
        "mandible":    {"max_dose": 70.0},
    },
    "breast": {
        "skin":  {"max_dose_pct": 70},
        "ribs":  {"max_dose_pct": 80},
        "heart": {"dmean_max": 3.0},
    },
    "esophageal": {
        "spinal_cord": {"max_dose": 45.0},
        "heart":       {"max_dose": 40.0},
        "lung":        {"dmean_max": 20.0},
    },
    "kidney": {
        "kidney":      {"d2cc": 18.0, "max_dose": 25.0},
        "bowel":       {"d2cc": 50.0, "max_dose": 65.0},
        "spinal_cord": {"max_dose": 45.0},
    },
    "default": {
        "rectum":      {"d2cc": 75.0, "max_dose": 100.0},
        "bladder":     {"d2cc": 90.0, "max_dose": 120.0},
        "urethra":     {"max_dose_pct": 120},
        "bowel":       {"d2cc": 55.0, "max_dose": 75.0},
        "kidney":      {"d2cc": 18.0, "max_dose": 25.0},
        "liver":       {"d2cc": 25.0, "max_dose": 35.0},
        "stomach":     {"d2cc": 50.0, "max_dose": 65.0},
        "duodenum":    {"d2cc": 55.0, "max_dose": 75.0},
        "spinal_cord": {"max_dose": 45.0},
        "heart":       {"max_dose": 60.0},
        "esophagus":   {"max_dose": 60.0},
        "artery":      {"d2cc": 80.0, "max_dose": 100.0},
        "vein":        {"d2cc": 80.0, "max_dose": 100.0},
    },
}


# Quality-score weights for the composite score (must sum to 1.0).
WEIGHTS = {
    "coverage":    0.40,
    "homogeneity": 0.20,
    "oar_sparing": 0.30,
    "conformance": 0.10,   # V150 / V200 hot-spot control
}

# Thresholds for "needs replan" auto-trigger.
REPLAN_TRIGGER_SCORE = 60.0   # composite below this ⇒ suggest replan
REPLAN_TRIGGER_VIOLATIONS = 1  # > 1 hard OAR violation ⇒ suggest replan


def get_target_standard(organ: str = "default") -> Dict[str, float]:
    """Return the target-coverage standard for a given organ (falls back to default)."""
    key = (organ or "default").lower()
    return dict(TARGET_STANDARDS.get(key, TARGET_STANDARDS["default"]))


def get_oar_standard(organ: str = "default") -> Dict[str, Dict[str, float]]:
    """Return the OAR dose standard for a given organ (falls back to default)."""
    key = (organ or "default").lower()
    return {k: dict(v) for k, v in OAR_STANDARDS.get(key, OAR_STANDARDS["default"]).items()}


def composite_score(
    coverage: float,
    homogeneity: float,
    oar: float,
    conformance: float,
) -> float:
    """Compute the weighted composite quality score (0–100)."""
    return (
        WEIGHTS["coverage"]    * coverage
        + WEIGHTS["homogeneity"] * homogeneity
        + WEIGHTS["oar_sparing"]  * oar
        + WEIGHTS["conformance"]  * conformance
    )


def should_replan(score: float, num_violations: int) -> bool:
    """Decide whether a plan should be auto-triggered for replanning."""
    return score < REPLAN_TRIGGER_SCORE or num_violations > REPLAN_TRIGGER_VIOLATIONS
