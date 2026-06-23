"""
Clinical Standards for Brachytherapy Plan Quality
=================================================

Per-organ target coverage and OAR dose constraints compiled from:
  - ABS (American Brachytherapy Society) consensus statements
  - GEC-ESTRO (Groupe Européen de Curiethérapie) recommendations
  - AAPM TG-229 / ESTRO guidelines for brachytherapy
  - NCCN brachytherapy guidelines

This module is the single source of truth for clinical pass criteria
used by both ``PlanQualityScorerTool`` and ``QualityDecider``.

All dose values are in **Gy** (absolute, not normalized). Each entry
gives the standard target-coverage threshold (D90, V100) and the
OAR constraints (max_dose, D2cc) in Gy. Organ names match the
``tumor_type`` strings used elsewhere in BrachyBot.
"""

from typing import Dict, Any


# Per-organ target coverage standards.
# ``d90_min_pct`` is the minimum D90 as a fraction of prescribed dose
# (i.e. 1.0 == 100% of prescription). ``v100_min`` is the minimum
# fraction of CTV receiving >= 100% of prescription.
#
# Sources:
#   prostate: ABS/AUA/ASTRO 2012 (PMID 22265436) — V100≥95%, D90≥100%Rx
#   prostate HDR: ABS 2022 — V100≥95%, D90 103-108%Rx, V200≤25%
#   cervical: EMBRACE II (PMID 42211610) — V100≥90%, D90≥85-90 Gy EQD2
#   breast: GEC-ESTRO APBI 2016 — D90≥90%Rx
#   lung: ABS lung consensus — V100≥95%
#   pancreatic: Chinese I-125 guideline 2023 — V100≥90%
#   liver: ABS liver consensus — V100≥90%
#   head_neck: ABS H&N consensus — V100≥95%
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
# Sources:
#   prostate: ABS/AUA/ASTRO 2012 — urethra Dmax≤120%Rx, rectum D2cc≤75 Gy EQD2
#   cervical: EMBRACE II — bladder D2cc<90, rectum D2cc<75, sigmoid D2cc<70
#   lung: ABS lung — spinal cord≤45, heart D2cc≤40
#   liver: ABS liver — stomach/duodenum D2cc≤50
#   pancreatic: Chinese I-125 2023 — duodenum D2cc≤55
#   head_neck: ABS H&N — spinal cord≤45, brainstem≤54, parotid mean≤26
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
