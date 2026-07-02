"""
Source-aware OAR constraint checker.

This tool provides deterministic OAR dose checks for planning QA. It does not
invent global OAR limits. Constraints must come from either:

1. ``custom_constraints`` supplied by the caller, usually from a case protocol.
2. The curated clinical-standards mirror for an explicit tumor site.

When no applicable source-backed constraint exists for an OAR, the tool reports
``NOT_CHECKED`` and asks the caller to query ``clinical_kb`` or provide
``custom_constraints``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
try:
    from .clinical_standards import OAR_STANDARDS
except ImportError:  # pragma: no cover - direct script execution path
    from clinical_standards import OAR_STANDARDS


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _metric(metrics: Dict[str, Any], *names: str) -> float:
    for name in names:
        if name in metrics and metrics[name] is not None:
            try:
                return float(metrics[name])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


class OARConstraintCheckerTool(BaseTool):
    """Check OAR dose metrics against source-backed constraints."""

    @property
    def name(self) -> str:
        return "oar_constraint_checker"

    @property
    def description(self) -> str:
        return (
            "Check OAR dose metrics against explicit case constraints or the "
            "curated clinical KB mirror for a specified tumor site. If no "
            "source-backed constraint is available, returns NOT_CHECKED rather "
            "than PASS/FAIL."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "oar_metrics": {
                    "type": "object",
                    "description": "Dict of OAR name -> {max_dose/dmax, d2cc, d1cc, mean_dose}",
                },
                "tumor_type": {
                    "type": "string",
                    "description": "Tumor site used to select curated KB mirror limits, e.g. pancreas/prostate/lung.",
                },
                "organ": {
                    "type": "string",
                    "description": "Alias for tumor_type.",
                },
                "custom_constraints": {
                    "type": "object",
                    "description": "Explicit OAR constraints. Values may include max_dose, dmax, d2cc, d1cc, mean_dose.",
                },
            },
            "required": ["oar_metrics"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "all_checked_pass": {
                    "type": "boolean",
                    "description": "True only if every checked constraint passes. Unchecked OARs do not count as pass.",
                },
                "violations": {"type": "array", "description": "Source-backed constraint violations"},
                "oar_status": {"type": "object", "description": "Per-OAR status: PASS, FAIL, or NOT_CHECKED"},
                "unchecked": {"type": "array", "description": "OARs with no source-backed constraints"},
                "constraint_source": {"type": "string"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        oar_metrics = kwargs.get("oar_metrics") or {}
        tumor_type = _norm(kwargs.get("tumor_type") or kwargs.get("organ") or "")
        custom_constraints = kwargs.get("custom_constraints") or {}

        constraints, source = self._build_constraints(tumor_type, custom_constraints)
        violations = []
        unchecked = []
        oar_status = {}

        for raw_oar_name, metrics in oar_metrics.items():
            oar_name = _norm(raw_oar_name)
            metrics = metrics or {}
            oar_constraints = self._match_constraints(oar_name, constraints)

            if not oar_constraints:
                oar_status[raw_oar_name] = {
                    "status": "NOT_CHECKED",
                    "reason": "No source-backed constraint matched this OAR name.",
                }
                unchecked.append(raw_oar_name)
                continue

            status, oar_violations = self._check_oar(raw_oar_name, metrics, oar_constraints)
            oar_status[raw_oar_name] = {
                "status": status,
                "constraints": oar_constraints,
            }
            violations.extend(oar_violations)

        checked_count = len(oar_metrics) - len(unchecked)
        all_checked_pass = checked_count > 0 and not violations
        message = (
            f"OAR constraint check: {len(violations)} violation(s), "
            f"{len(unchecked)} unchecked OAR(s), source={source}."
        )

        return ToolResult(
            success=True,
            data={
                "all_checked_pass": all_checked_pass,
                "violations": violations,
                "oar_status": oar_status,
                "unchecked": unchecked,
                "constraint_source": source,
                "tumor_type": tumor_type or None,
            },
            message=message,
            metadata={
                "all_checked_pass": all_checked_pass,
                "violations": violations,
                "oar_status": oar_status,
                "unchecked": unchecked,
                "constraint_source": source,
                "tumor_type": tumor_type or None,
            },
        )

    def _build_constraints(self, tumor_type: str, custom_constraints: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        constraints: Dict[str, Any] = {}
        source_parts = []

        if tumor_type and tumor_type in OAR_STANDARDS:
            constraints.update({k: dict(v) for k, v in OAR_STANDARDS[tumor_type].items()})
            source_parts.append(f"clinical_standards_mirror:{tumor_type}")

        if custom_constraints:
            for name, value in custom_constraints.items():
                constraints.setdefault(_norm(name), {}).update(value or {})
            source_parts.append("custom_constraints")

        source = "+".join(source_parts) if source_parts else "missing_constraints"
        return constraints, source

    def _match_constraints(self, oar_name: str, constraints: Dict[str, Any]) -> Dict[str, Any]:
        if oar_name in constraints:
            return constraints[oar_name]

        for standard_name, standard in constraints.items():
            if standard_name and (standard_name in oar_name or oar_name in standard_name):
                return standard
        return {}

    def _check_oar(self, oar_name: str, metrics: Dict[str, Any], constraints: Dict[str, Any]) -> Tuple[str, list]:
        violations = []
        checks = [
            ("max_dose", _metric(metrics, "max_dose", "dmax"), constraints.get("max_dose") or constraints.get("dmax")),
            ("d2cc", _metric(metrics, "d2cc", "D2cc"), constraints.get("d2cc")),
            ("d1cc", _metric(metrics, "d1cc", "D1cc"), constraints.get("d1cc")),
            ("mean_dose", _metric(metrics, "mean_dose", "dmean", "Dmean"), constraints.get("mean_dose") or constraints.get("dmean_max")),
        ]

        for constraint_type, actual, limit in checks:
            if limit is None:
                continue
            try:
                limit_f = float(limit)
            except (TypeError, ValueError):
                continue
            if actual > limit_f:
                violations.append({
                    "oar": oar_name,
                    "constraint_type": constraint_type,
                    "actual": float(actual),
                    "limit": limit_f,
                    "excess_pct": float((actual - limit_f) / limit_f * 100.0) if limit_f else None,
                })

        return ("FAIL" if violations else "PASS"), violations


def main():
    parser = argparse.ArgumentParser(description="Source-aware OAR constraint checker")
    parser.add_argument("--oar_metrics", required=True, help="JSON dict of OAR metrics")
    parser.add_argument("--tumor_type", default="", help="Tumor site used for curated KB mirror constraints")
    parser.add_argument("--custom_constraints", default="{}", help="JSON dict of explicit constraints")
    args = parser.parse_args()

    tool = OARConstraintCheckerTool()
    result = tool._execute(
        oar_metrics=json.loads(args.oar_metrics),
        tumor_type=args.tumor_type,
        custom_constraints=json.loads(args.custom_constraints or "{}"),
    )
    print(result.message)
    for violation in result.metadata["violations"]:
        print(
            f"  - {violation['oar']}: {violation['constraint_type']}="
            f"{violation['actual']:.2f} > {violation['limit']:.2f}"
        )


if __name__ == "__main__":
    main()
