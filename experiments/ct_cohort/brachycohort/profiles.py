"""Fail-closed applicable, approved parameter recipes; never prescribe by name."""
from .core import Blocked, digest, finite


def validate_profile(p):
    required = ("id", "version", "status", "clinical_reviewer", "physics_reviewer", "approved_at",
                "applicability", "evidence", "source", "engine", "target_policy", "oar_policy", "guide_policy", "settings")
    if any(not p.get(k) for k in required) or p["status"] != "APPROVED_RESEARCH":
        raise Blocked("PROFILE_UNRESOLVED", p.get("id", "unknown"))
    a, s = p["applicability"], p["settings"]
    if not a.get("datasets") or not a.get("target_semantics") or not a.get("site") or not a.get("purpose"):
        raise Blocked("PROFILE_APPLICABILITY_INCOMPLETE")
    if not p["evidence"] or any(not e.get("reference") or not e.get("section") or not e.get("applicability") for e in p["evidence"]):
        raise Blocked("PROFILE_EVIDENCE_INCOMPLETE")
    if not all(p["source"].get(k) for k in ("isotope", "model", "strength", "strength_unit", "time_assumptions")):
        raise Blocked("SOURCE_RECIPE_INCOMPLETE")
    if not finite(p["source"]["strength"], True):
        raise Blocked("INVALID_SOURCE_STRENGTH")
    if not all(p["engine"].get(k) for k in ("name", "weights_sha256", "calibration", "compatibility_review")):
        raise Blocked("ENGINE_RECIPE_INCOMPLETE")
    import re
    if not isinstance(p["engine"]["weights_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", p["engine"]["weights_sha256"]):
        raise Blocked("INVALID_ENGINE_WEIGHT_HASH")
    if p["target_policy"].get("kind") != "supplied_union_no_margin":
        raise Blocked("UNSUPPORTED_TARGET_POLICY", "Margins/resampling require a separate validated arm")
    if p["oar_policy"].get("kind") != "product_inference":
        raise Blocked("UNSUPPORTED_OAR_ARM")
    if not finite(s.get("prescription_gy"), True) or not finite(s.get("upper_dose_gy"), True):
        raise Blocked("INVALID_DOSE_RECIPE")
    if not finite(s.get("coverage_fraction")) or not 0 < s["coverage_fraction"] <= 1:
        raise Blocked("INVALID_COVERAGE_FRACTION")
    if type(s.get("max_iterations")) is not int or s["max_iterations"] <= 0 or s.get("mode") not in {"rl", "rule_based"}:
        raise Blocked("INVALID_OPTIMIZATION_RECIPE")
    if s.get("upper_dose_gy") < s["prescription_gy"]:
        raise Blocked("INVALID_DOSE_RANGE")
    if p["guide_policy"].get("truncation_margin_mm") != 5.0:
        raise Blocked("UNREVIEWED_GUIDE_TRUNCATION_VARIANT")
    return digest(p)


def applicable(row, p):
    profile_hash = validate_profile(p)
    a = p["applicability"]
    if row["dataset"] not in a["datasets"] or row.get("target_semantics") not in a["target_semantics"]:
        raise Blocked("PROFILE_CASE_MISMATCH")
    if a.get("phases") and row.get("phase") not in a["phases"]:
        raise Blocked("PROFILE_PHASE_MISMATCH")
    if row.get("clinical_eligibility") != "APPROVED_RESEARCH" or row.get("planning_profile_id") != p["id"]:
        raise Blocked("CASE_APPROVAL_UNRESOLVED")
    return profile_hash


def prompt(row, p, language="en"):
    applicable(row, p)
    if language != "en":
        raise Blocked("UNREGISTERED_PROMPT_LANGUAGE")
    s = p["settings"]
    # Only case facts and approved recipe values: never send oracle expectations.
    return (f"This is a retrospective research case, not clinical treatment approval. "
            f"Use the CT and effective CTV already loaded; preserve the uploaded target and do not "
            f"run replacement tumor segmentation. Site: {p['applicability']['site']}. "
            f"Approved profile: {p['id']}@{p['version']}; target policy: supplied union without margin. "
            f"Use prescription {s['prescription_gy']} Gy, upper dose setting {s['upper_dose_gy']} Gy, "
            f"target coverage {s['coverage_fraction'] * 100:g}%, maximum {s['max_iterations']} iterations, "
            f"and {s['mode']} planning. Approved source and engine recipe: {p['source']}; {p['engine']}. "
            f"Prepare OARs with the standard product inference workflow; complete seed implantation "
            f"planning, dose/DVH and quality evaluation, generate and validate the guide with the "
            f"standard 5 mm truncation policy, and save the report with its standard figures. "
            f"Applicable constraints: {p['oar_policy'].get('constraints', [])}. "
            f"If a required input, source calibration or recipe is unsupported, stop that dependent "
            f"operation and explain it. Report actual completed, failed and unknown stages; do not "
            f"invent scores, limits, clinical approval or substitute a different target.")
