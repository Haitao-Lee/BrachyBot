"""
Safety Validator Tool
=====================
Validates treatment plans against clinical safety rules.
Prevents dangerous plans from being exported or executed.
"""

import logging
from typing import Dict, Any, Optional, List
from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


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
            "strict": {"type": "boolean", "description": "Use strict mode (default: false)"},
        },
        "required": ["action"],
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    # Safety rules: (metric, operator, threshold, severity, message)
    SAFETY_RULES = [
        ("v100", ">=", 0.80, "CRITICAL", "CTV V100 below 80% — severe underdose risk"),
        ("v100", ">=", 0.90, "WARNING", "CTV V100 below 90% — suboptimal coverage"),
        ("v200", "<=", 0.50, "CRITICAL", "V200 above 50% — severe overdose risk"),
        ("v200", "<=", 0.35, "WARNING", "V200 above 35% — elevated hot spots"),
        ("v150", "<=", 0.60, "WARNING", "V150 above 60% — moderate hot spots"),
        ("d90", ">=", 85.0, "CRITICAL", "D90 below 85% — target underdosed"),
        ("d90", ">=", 95.0, "WARNING", "D90 below 95% — marginal target dose"),
    ]

    OAR_LIMITS = {
        "rectum": {"d0.1cc": 150, "d1cc": 120},
        "bladder": {"d0.1cc": 150},
        "urethra": {"d0.1cc": 120},
        "spinal_cord": {"d0.1cc": 100},
        "brainstem": {"d0.1cc": 100},
        "heart": {"d0.1cc": 100},
        "esophagus": {"d0.1cc": 100},
        "small_bowel": {"d0.1cc": 100},
    }

    def _check_rule(self, metrics: Dict, rule: tuple, strict: bool) -> Optional[Dict]:
        """Check a single safety rule."""
        metric_name, op, threshold, severity, message = rule

        if strict:
            threshold_map = {0.80: 0.85, 0.90: 0.95, 0.50: 0.45, 0.35: 0.30, 0.60: 0.55, 85.0: 90.0, 95.0: 98.0}
            threshold = threshold_map.get(threshold, threshold)

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

    def _validate_plan(self, plan: Dict, strict: bool = False) -> ToolResult:
        """Run full safety validation."""
        metrics = plan.get("metrics", plan)
        violations = []
        warnings = []

        # Check dose rules
        for rule in self.SAFETY_RULES:
            result = self._check_rule(metrics, rule, strict)
            if result:
                if result["severity"] == "CRITICAL":
                    violations.append(result)
                else:
                    warnings.append(result)

        # Check OAR constraints
        oar_violations = metrics.get("oar_violations", [])
        for ov in oar_violations:
            violations.append({
                "metric": "oar_constraint",
                "value": ov.get("dose", 0),
                "threshold": ov.get("limit", 0),
                "severity": "CRITICAL",
                "message": f"OAR violation: {ov.get('organ', 'unknown')} exceeds dose limit",
            })

        # Check seed count plausibility
        seed_count = plan.get("seed_count", metrics.get("seed_count", 0))
        ctv_volume = plan.get("ctv_volume_cc", metrics.get("ctv_volume_cc", 0))
        if ctv_volume > 0 and seed_count > 0:
            density = seed_count / ctv_volume
            if density > 2.0:
                warnings.append({
                    "metric": "seed_density",
                    "value": round(density, 2),
                    "threshold": 2.0,
                    "severity": "WARNING",
                    "message": f"High seed density ({density:.1f} seeds/cc) — check for clustering",
                })
            elif density < 0.3:
                warnings.append({
                    "metric": "seed_density",
                    "value": round(density, 2),
                    "threshold": 0.3,
                    "severity": "WARNING",
                    "message": f"Low seed density ({density:.1f} seeds/cc) — check coverage",
                })

        safe = len(violations) == 0

        return ToolResult(
            success=True,
            data={
                "safe": safe,
                "critical_violations": violations,
                "warnings": warnings,
                "total_issues": len(violations) + len(warnings),
                "strict_mode": strict,
            },
            message=f"Validation {'PASSED' if safe else 'FAILED'}: {len(violations)} critical, {len(warnings)} warnings"
        )

    def _check_dose(self, plan: Dict, organ: str) -> ToolResult:
        """Check dose constraints for a specific organ."""
        metrics = plan.get("metrics", plan)
        organ_lower = organ.lower().replace(" ", "_")

        limits = self.OAR_LIMITS.get(organ_lower, {})
        if not limits:
            return ToolResult(
                success=True,
                data={"organ": organ, "limits": None, "message": f"No specific limits for '{organ}'"},
                message=f"No limits defined for {organ}"
            )

        results = {}
        for metric_key, limit_pct in limits.items():
            actual = metrics.get(f"{organ_lower}_{metric_key}")
            if actual is not None:
                results[metric_key] = {
                    "actual": actual,
                    "limit": limit_pct,
                    "unit": "% of prescription",
                    "passed": actual <= limit_pct,
                }

        all_passed = all(r["passed"] for r in results.values()) if results else True

        return ToolResult(
            success=True,
            data={"organ": organ, "checks": results, "all_passed": all_passed},
            message=f"Dose check for {organ}: {'PASSED' if all_passed else 'FAILED'}"
        )

    def _check_coverage(self, plan: Dict, strict: bool = False) -> ToolResult:
        """Verify target coverage."""
        metrics = plan.get("metrics", plan)
        v100 = metrics.get("v100", 0)
        d90 = metrics.get("d90", 0)

        min_v100 = 0.85 if strict else 0.80
        min_d90 = 90.0 if strict else 85.0

        checks = {
            "v100": {"value": v100, "min": min_v100, "passed": v100 >= min_v100},
            "d90": {"value": d90, "min": min_d90, "passed": d90 >= min_d90 if d90 else True},
        }

        all_passed = all(c["passed"] for c in checks.values())

        return ToolResult(
            success=True,
            data={"checks": checks, "all_passed": all_passed},
            message=f"Coverage check: {'PASSED' if all_passed else 'FAILED'}"
        )

    def _check_hotspots(self, plan: Dict, strict: bool = False) -> ToolResult:
        """Check for dangerous hot spots."""
        metrics = plan.get("metrics", plan)
        v150 = metrics.get("v150", 0)
        v200 = metrics.get("v200", 0)

        max_v150 = 0.55 if strict else 0.60
        max_v200 = 0.30 if strict else 0.35

        checks = {
            "v150": {"value": v150, "max": max_v150, "passed": v150 <= max_v150 if v150 else True},
            "v200": {"value": v200, "max": max_v200, "passed": v200 <= max_v200 if v200 else True},
        }

        all_passed = all(c["passed"] for c in checks.values())

        return ToolResult(
            success=True,
            data={"checks": checks, "all_passed": all_passed},
            message=f"Hotspot check: {'PASSED' if all_passed else 'FAILED'}"
        )

    def _pre_export_gate(self, plan: Dict) -> ToolResult:
        """Pre-export safety gate — all checks must pass."""
        result = self._validate_plan(plan, strict=False)
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

        if not action:
            return ToolResult(success=False, error="No action", message="Specify: validate, check_dose, check_coverage, check_hotspots, pre_export")

        if not plan and action != "check_dose":
            return ToolResult(success=False, error="No plan data", message="Provide 'plan' with metrics")

        if action == "validate":
            return self._validate_plan(plan, strict)
        elif action == "check_dose":
            return self._check_dose(plan, kwargs.get("organ", ""))
        elif action == "check_coverage":
            return self._check_coverage(plan, strict)
        elif action == "check_hotspots":
            return self._check_hotspots(plan, strict)
        elif action == "pre_export":
            return self._pre_export_gate(plan)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: validate, check_dose, check_coverage, check_hotspots, pre_export")
