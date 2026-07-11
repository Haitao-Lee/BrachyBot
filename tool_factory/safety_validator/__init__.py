"""
Safety Validator Tool
=====================
Validates treatment plans against clinical safety rules.
Prevents dangerous plans from being exported or executed.

Runtime thresholds are generated from the curated clinical standards mirror. Legacy fallback tables below are retained only for compatibility and should not be used as citation sources.
"""

import logging
import importlib.util
from pathlib import Path
from typing import Dict, Any, Optional, List
from tool_factory import BaseTool, ToolResult
from agents.clinical_metrics import match_constraint_name, normalized_fraction

logger = logging.getLogger(__name__)

_CLINICAL_STANDARDS_MODULE = None


def _load_clinical_standards_module():
    """Load clinical_standards.py without importing the heavy plan_quality package."""
    global _CLINICAL_STANDARDS_MODULE
    if _CLINICAL_STANDARDS_MODULE is not None:
        return _CLINICAL_STANDARDS_MODULE
    path = Path(__file__).resolve().parents[1] / "plan_quality" / "clinical_standards.py"
    spec = importlib.util.spec_from_file_location("_brachybot_clinical_standards", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    _CLINICAL_STANDARDS_MODULE = module
    return module


def _target_standard(site: str) -> Dict[str, Any]:
    return _load_clinical_standards_module().get_target_standard(site)


def _oar_standard(site: str) -> Dict[str, Any]:
    return _load_clinical_standards_module().get_oar_standard(site)


# Per-site safety rules: (metric, operator, threshold, severity, message)
# D90 values are % of prescription dose (1.0 = 100% of Rx), NOT absolute Gy.
# V100/V150/V200 are fractions (0.90 = 90%).
# Historical migration reference only. Runtime validation never reads these
# uncited values; authoritative limits come from clinical_kb through
# clinical_standards.py. Keeping the name explicit prevents accidental reuse.
_LEGACY_UNUSED_SITE_SAFETY_RULES = {
    "prostate": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose (curated KB benchmark)"),
        ("v100", ">=", 0.95, "WARNING",  "CTV V100 below 95% — suboptimal coverage (curated KB benchmark)"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.35, "WARNING",  "V200 above 35% — elevated hot spots (curated KB benchmark)"),
        ("v150", "<=", 0.60, "WARNING",  "V150 above 60% — moderate hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
        ("d90",  ">=", 1.00, "WARNING",  "D90 below 100% of Rx — marginal dose (curated KB benchmark)"),
    ],
    "cervical": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal (curated KB benchmark)"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.35, "WARNING",  "V200 above 35% — elevated hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "breast": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal (curated KB benchmark)"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("d90",  ">=", 0.80, "CRITICAL", "D90 below 80% of Rx — target underdosed"),
        ("d90",  ">=", 0.90, "WARNING",  "D90 below 90% of Rx — suboptimal"),
    ],
    "lung": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.95, "WARNING",  "CTV V100 below 95% — suboptimal (ABS target ≥95%)"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.30, "WARNING",  "V200 above 30% — elevated hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "pancreatic": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.30, "WARNING",  "V200 above 30% — elevated hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "liver": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "kidney": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "colon": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "head_neck": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.95, "WARNING",  "CTV V100 below 95% — suboptimal"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.25, "WARNING",  "V200 above 25% — elevated hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "esophageal": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
    ],
    "default": [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose risk"),
        ("v100", ">=", 0.90, "WARNING",  "CTV V100 below 90% — suboptimal coverage"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.35, "WARNING",  "V200 above 35% — elevated hot spots"),
        ("v150", "<=", 0.60, "WARNING",  "V150 above 60% — moderate hot spots"),
        ("d90",  ">=", 0.85, "CRITICAL", "D90 below 85% of Rx — target underdosed"),
        ("d90",  ">=", 1.00, "WARNING",  "D90 below 100% of Rx — marginal target dose"),
    ],
}

# Per-site OAR limits. Values are % of prescription dose unless noted.
_LEGACY_UNUSED_SITE_OAR_LIMITS = {
    "prostate": {
        "urethra":     {"d0.1cc_pct": 120, "d10_pct": 120},
        "rectum":      {"d2cc_gy": 75, "d0.1cc_pct": 100},
        "bladder":     {"d2cc_gy": 90, "d0.1cc_pct": 100},
    },
    "cervical": {
        "bladder":     {"d2cc_gy": 90},
        "rectum":      {"d2cc_gy": 75},
        "sigmoid":     {"d2cc_gy": 70},
        "small_bowel": {"d2cc_gy": 75},
    },
    "pancreatic": {
        "duodenum": {"d2cc_gy": 55, "dmax_gy": 75},
        "stomach":  {"d2cc_gy": 55, "dmax_gy": 75},
        "bowel":    {"d2cc_gy": 55, "dmax_gy": 75},
        "artery":   {"d2cc_gy": 80, "dmax_gy": 100},
        "vein":     {"d2cc_gy": 80, "dmax_gy": 100},
    },
    "liver": {
        "stomach":      {"d2cc_gy": 50, "dmax_gy": 65},
        "duodenum":     {"d2cc_gy": 50, "dmax_gy": 65},
        "colon":        {"d2cc_gy": 50, "dmax_gy": 65},
        "kidney":       {"d2cc_gy": 18, "dmax_gy": 25},
        "normal_liver": {"dmean_gy": 30},
    },
    "lung": {
        "spinal_cord": {"dmax_gy": 45},
        "heart":       {"d2cc_gy": 40, "dmax_gy": 60},
        "esophagus":   {"d2cc_gy": 55, "dmax_gy": 60},
        "trachea":     {"d2cc_gy": 70, "dmax_gy": 75},
    },
    "head_neck": {
        "spinal_cord": {"dmax_gy": 45},
        "brainstem":   {"dmax_gy": 54},
        "parotid":     {"dmean_gy": 26},
        "mandible":    {"dmax_gy": 70},
    },
    "breast": {
        "skin":  {"dmax_pct": 70},
        "ribs":  {"dmax_pct": 80},
        "heart": {"dmean_gy": 3},
    },
    "esophageal": {
        "spinal_cord": {"dmax_gy": 45},
        "heart":       {"dmax_gy": 40},
        "lung":        {"dmean_gy": 20},
    },
    "default": {
        "rectum":      {"d0.1cc_pct": 150, "d1cc_pct": 120, "d2cc_gy": 75},
        "bladder":     {"d0.1cc_pct": 150, "d2cc_gy": 90},
        "urethra":     {"d0.1cc_pct": 120},
        "spinal_cord": {"dmax_gy": 45},
        "brainstem":   {"dmax_gy": 54},
        "heart":       {"dmax_gy": 60},
        "esophagus":   {"dmax_gy": 60},
        "small_bowel": {"d2cc_gy": 55, "dmax_gy": 75},
    },
}


def _normalize_tumor_type(tumor_type: str) -> str:
    """Normalize tumor_type string to site key."""
    if not tumor_type:
        return "unknown"
    tt = tumor_type.lower().replace(" ", "_").replace("-", "_")
    # Map common names
    _map = {
        "nnunet_pancreatic": "pancreatic",
        "pancreas": "pancreatic",
        "voco_liver": "liver",
        "voco_kidney": "kidney",
        "voco_lung": "lung",
        "voco_colon": "colon",
        "voco_brats21": "head_neck",
    }
    for pattern, site in _map.items():
        if pattern in tt:
            return site
    # Direct match
    supported_sites = {
        "prostate", "cervical", "breast", "lung", "pancreatic", "liver",
        "kidney", "colon", "head_neck", "esophageal",
    }
    for key in supported_sites:
        if key in tt or tt in key:
            return key
    # Do not silently apply the composite `default` protocol to an unknown
    # disease site. Callers must clarify the site or provide explicit limits.
    return "unknown"


class SafetyValidatorTool(BaseTool):
    """Validate treatment plans against safety rules and clinical constraints."""

    name = "safety_validator"
    description = """Validate treatment plans against clinical safety rules.
Capabilities:
- validate: Full safety validation of a plan
- check_dose: Check dose constraints for specific organs
- check_coverage: Verify target coverage meets minimums
- check_hotspots: Check for dangerous hot spots
- pre_export: Pre-export safety gate (all checks combined)"""

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: validate, check_dose, check_coverage, check_hotspots, pre_export",
                "enum": ["validate", "check_dose", "check_coverage", "check_hotspots", "pre_export"]
            },
            "plan": {"type": "object", "description": "Plan data with metrics"},
            "organ": {"type": "string", "description": "Specific organ to check (for check_dose)"},
            "tumor_type": {"type": "string", "description": "Tumor site for per-site thresholds (e.g. 'prostate', 'cervical', 'pancreatic')"},
            "strict": {
                "type": "boolean",
                "description": (
                    "Escalate source-backed violations to CRITICAL without "
                    "changing the cited numeric limits (default: false)"
                ),
            },
        },
        "required": ["action"],
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    def _get_rules_for_site(self, tumor_type: str) -> List[tuple]:
        """Get safety rules from the curated clinical standards mirror."""
        site = _normalize_tumor_type(tumor_type)
        std = _target_standard(site)
        rules = []
        if "v100_min" in std:
            rules.append(("v100", ">=", std["v100_min"], "WARNING", f"CTV V100 below curated KB benchmark {std['v100_min']:.0%}"))
        if "v150_max" in std:
            rules.append(("v150", "<=", std["v150_max"], "WARNING", f"V150 above curated KB benchmark {std['v150_max']:.0%}"))
        if "v200_max" in std:
            rules.append(("v200", "<=", std["v200_max"], "WARNING", f"V200 above curated KB benchmark {std['v200_max']:.0%}"))
        if "d90_min_pct" in std:
            rules.append(("d90", ">=", std["d90_min_pct"], "WARNING", f"D90 below curated KB benchmark {std['d90_min_pct']:.0%} of prescription"))
        return rules

    def _get_oar_limits_for_site(self, tumor_type: str) -> Dict:
        """Get OAR limits from the curated clinical standards mirror."""
        site = _normalize_tumor_type(tumor_type)
        std = _oar_standard(site)
        converted = {}
        for organ, limits in std.items():
            entry = {}
            if "d2cc" in limits:
                entry["d2cc_gy"] = limits["d2cc"]
            if "max_dose" in limits:
                entry["dmax_gy"] = limits["max_dose"]
            if "dmean_max" in limits:
                entry["dmean_gy"] = limits["dmean_max"]
            if "max_dose_pct" in limits:
                entry["dmax_pct"] = limits["max_dose_pct"]
            if entry:
                converted[organ] = entry
        return converted

    def _check_rule(self, metrics: Dict, rule: tuple, strict: bool) -> Optional[Dict]:
        """Check a single safety rule."""
        metric_name, op, threshold, severity, message = rule

        # Strict mode escalates a source-backed violation; it must never
        # invent a different clinical threshold.

        value = metrics.get(metric_name)
        if value is None:
            return None

        violated = False
        if op == ">=" and value < threshold:
            violated = True
        elif op == "<=" and value > threshold:
            violated = True

        if violated:
            return {
                "metric": metric_name,
                "value": value,
                "threshold": threshold,
                "operator": op,
                "severity": severity if not strict else "CRITICAL",
                "message": message,
            }
        return None

    def _validate_plan(self, plan: Dict, strict: bool = False, tumor_type: str = "") -> ToolResult:
        """Run full safety validation with per-site thresholds."""
        metrics = plan.get("metrics", plan)
        # Try to get tumor_type from plan if not provided
        if not tumor_type:
            tumor_type = metrics.get("tumor_type", "") or plan.get("tumor_type", "")
        violations = []
        warnings = []

        # Check dose rules (per-site)
        rules = self._get_rules_for_site(tumor_type)
        oar_limits = self._get_oar_limits_for_site(tumor_type)
        standards_available = bool(rules or oar_limits)
        if not standards_available:
            warnings.append({
                "metric": "clinical_standard",
                "severity": "WARNING",
                "message": "No source-backed clinical standard is available for this site.",
            })
        for rule in rules:
            result = self._check_rule(metrics, rule, strict)
            if result:
                if result["severity"] == "CRITICAL":
                    violations.append(result)
                else:
                    warnings.append(result)

        # Check OAR constraints (per-site)
        oar_metrics = metrics.get("oar_metrics", {})
        if isinstance(oar_metrics, dict):
            for organ_name, oar_data in oar_metrics.items():
                matched_name = match_constraint_name(organ_name, oar_limits)
                organ_key = matched_name or organ_name.lower().replace(" ", "_")
                limits = oar_limits.get(matched_name, {}) if matched_name else {}
                if not limits:
                    continue
                dmax = oar_data.get("dmax")
                if dmax is None:
                    dmax = oar_data.get("Dmax")
                d2cc = oar_data.get("d2cc")
                if d2cc is None:
                    d2cc = oar_data.get("D2cc")
                # Check absolute Gy limits
                if dmax is not None and "dmax_gy" in limits and dmax > limits["dmax_gy"]:
                    violations.append({
                        "metric": f"{organ_key}_dmax",
                        "value": dmax,
                        "threshold": limits["dmax_gy"],
                        "severity": "CRITICAL",
                        "message": f"{organ_name} Dmax = {dmax:.1f} Gy exceeds limit {limits['dmax_gy']} Gy",
                    })
                if d2cc is not None and "d2cc_gy" in limits and d2cc > limits["d2cc_gy"]:
                    violations.append({
                        "metric": f"{organ_key}_d2cc",
                        "value": d2cc,
                        "threshold": limits["d2cc_gy"],
                        "severity": "CRITICAL",
                        "message": f"{organ_name} D2cc = {d2cc:.1f} Gy exceeds limit {limits['d2cc_gy']} Gy",
                    })

        # Also check legacy oar_violations list
        oar_violations = metrics.get("oar_violations", [])
        for ov in oar_violations:
            violations.append({
                "metric": "oar_constraint",
                "value": ov.get("dose", 0),
                "threshold": ov.get("limit", 0),
                "severity": "CRITICAL",
                "message": f"OAR violation: {ov.get('organ', 'unknown')} exceeds dose limit",
            })

        safe = standards_available and len(violations) == 0
        site = _normalize_tumor_type(tumor_type)

        return ToolResult(
            success=True,
            data={
                "safe": safe,
                "critical_violations": violations,
                "warnings": warnings,
                "total_issues": len(violations) + len(warnings),
                "strict_mode": strict,
                "site": site,
                "standards_available": standards_available,
            },
            message=f"Validation {'PASSED' if safe else 'FAILED'} ({site}): {len(violations)} critical, {len(warnings)} warnings"
        )

    def _check_dose(self, plan: Dict, organ: str, tumor_type: str = "") -> ToolResult:
        """Check dose constraints for a specific organ using per-site limits."""
        metrics = plan.get("metrics", plan)
        organ_lower = organ.lower().replace(" ", "_")
        if not tumor_type:
            tumor_type = metrics.get("tumor_type", "") or plan.get("tumor_type", "")

        oar_limits = self._get_oar_limits_for_site(tumor_type)
        limits = oar_limits.get(organ_lower, {})
        if not limits:
            return ToolResult(
                success=True,
                data={"organ": organ, "limits": None, "message": f"No specific limits for '{organ}'"},
                message=f"No limits defined for {organ}"
            )

        results = {}
        for metric_key, limit_val in limits.items():
            actual = metrics.get(f"{organ_lower}_{metric_key}")
            if actual is not None:
                results[metric_key] = {
                    "actual": actual,
                    "limit": limit_val,
                    "passed": actual <= limit_val,
                }

        all_passed = all(r["passed"] for r in results.values()) if results else True

        return ToolResult(
            success=True,
            data={"organ": organ, "checks": results, "all_passed": all_passed},
            message=f"Dose check for {organ}: {'PASSED' if all_passed else 'FAILED'}"
        )

    def _check_coverage(self, plan: Dict, strict: bool = False, tumor_type: str = "") -> ToolResult:
        """Verify target coverage using the curated clinical standards mirror."""
        metrics = plan.get("metrics", plan)
        if not tumor_type:
            tumor_type = metrics.get("tumor_type", "") or plan.get("tumor_type", "")
        v100 = metrics.get("v100", 0)
        d90 = metrics.get("d90", 0)

        site = _normalize_tumor_type(tumor_type)
        target_std = _target_standard(site)
        if not target_std:
            return ToolResult(
                success=True,
                data={"checks": {}, "all_passed": False, "site": site,
                      "standards_available": False},
                message=f"Coverage check unavailable: no source-backed standard for {site}",
            )
        min_v100 = target_std.get("v100_min")
        min_d90_pct = target_std.get("d90_min_pct")

        v100 = normalized_fraction(v100)
        d90_ratio = d90
        prescribed = metrics.get("prescribed_dose", plan.get("prescribed_dose"))
        if d90 is not None and d90 > 5:
            d90_ratio = d90 / prescribed if prescribed and prescribed > 0 else None

        checks = {
            "v100": {"value": v100, "min": min_v100, "passed": min_v100 is None or (v100 is not None and v100 >= min_v100)},
            "d90": {"value": d90_ratio, "min_pct": min_d90_pct, "passed": min_d90_pct is None or (d90_ratio is not None and d90_ratio >= min_d90_pct)},
        }

        all_passed = all(c["passed"] for c in checks.values())

        return ToolResult(
            success=True,
            data={"checks": checks, "all_passed": all_passed, "site": site, "source": "curated_clinical_kb_mirror"},
            message=f"Coverage check ({site}): {'PASSED' if all_passed else 'FAILED'}"
        )

    def _check_hotspots(self, plan: Dict, strict: bool = False, tumor_type: str = "") -> ToolResult:
        """Check hot-spot metrics using the curated clinical standards mirror."""
        metrics = plan.get("metrics", plan)
        if not tumor_type:
            tumor_type = metrics.get("tumor_type", "") or plan.get("tumor_type", "")
        v150 = metrics.get("v150", 0)
        v200 = metrics.get("v200", 0)

        site = _normalize_tumor_type(tumor_type)
        target_std = _target_standard(site)
        if not target_std:
            return ToolResult(
                success=True,
                data={"checks": {}, "all_passed": False, "site": site,
                      "standards_available": False},
                message=f"Hotspot check unavailable: no source-backed standard for {site}",
            )
        max_v150 = target_std.get("v150_max")
        max_v200 = target_std.get("v200_max")
        v150 = normalized_fraction(v150)
        v200 = normalized_fraction(v200)

        checks = {
            "v150": {"value": v150, "max": max_v150, "passed": max_v150 is None or (v150 is not None and v150 <= max_v150)},
            "v200": {"value": v200, "max": max_v200, "passed": max_v200 is None or (v200 is not None and v200 <= max_v200)},
        }
        all_passed = all(c["passed"] for c in checks.values())

        return ToolResult(
            success=True,
            data={"checks": checks, "all_passed": all_passed, "site": site, "source": "curated_clinical_kb_mirror"},
            message=f"Hotspot check ({site}): {'PASSED' if all_passed else 'WARNING'}"
        )
    def _pre_export_gate(self, plan: Dict, tumor_type: str = "") -> ToolResult:
        """Pre-export safety gate — all checks must pass."""
        result = self._validate_plan(plan, strict=False, tumor_type=tumor_type)
        data = result.data

        if data.get("safe"):
            return ToolResult(
                success=True,
                data={"approved": True, "message": "Plan approved for export"},
                message="✅ Plan passed all safety checks — approved for export"
            )
        else:
            critical = data.get("critical_violations", [])
            return ToolResult(
                success=False,
                data={
                    "approved": False,
                    "violations": critical,
                    "warnings": data.get("warnings", []),
                    "message": f"Plan REJECTED: {len(critical)} critical violation(s)"
                },
                message=f"❌ Plan REJECTED: {len(critical)} critical violation(s) must be fixed before export"
            )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        plan = kwargs.get("plan", {})
        strict = kwargs.get("strict", False)
        tumor_type = kwargs.get("tumor_type", "")

        if not action:
            return ToolResult(success=False, error="No action", message="Specify: validate, check_dose, check_coverage, check_hotspots, pre_export")

        if not plan and action != "check_dose":
            return ToolResult(success=False, error="No plan data", message="Provide 'plan' with metrics")

        if action == "validate":
            return self._validate_plan(plan, strict, tumor_type)
        elif action == "check_dose":
            return self._check_dose(plan, kwargs.get("organ", ""), tumor_type)
        elif action == "check_coverage":
            return self._check_coverage(plan, strict, tumor_type)
        elif action == "check_hotspots":
            return self._check_hotspots(plan, strict, tumor_type)
        elif action == "pre_export":
            return self._pre_export_gate(plan, tumor_type)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: validate, check_dose, check_coverage, check_hotspots, pre_export")
