"""
OAR Constraint Checker Tool
==========================
Checks whether OAR doses violate clinical dose constraints.
Provides pass/fail feedback for each OAR structure.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tool_factory import BaseTool, ToolResult
from typing import Dict, List, Optional
import numpy as np


DEFAULT_CONSTRAINTS = {
    "rectum": {"max_dose": 120.0, "d2cc": 100.0},
    "bladder": {"max_dose": 150.0, "d2cc": 125.0},
    "urethra": {"max_dose": 100.0, "d2cc": 90.0},
    "bowel": {"max_dose": 80.0, "d2cc": 70.0},
    "kidney": {"max_dose": 20.0, "d2cc": 18.0},
    "liver": {"max_dose": 30.0, "d2cc": 25.0},
    "stomach": {"max_dose": 50.0, "d2cc": 45.0},
    "pancreas": {"max_dose": 60.0, "d2cc": 50.0},
    "duodenum": {"max_dose": 60.0, "d2cc": 55.0},
    "artery": {"max_dose": 80.0, "d2cc": 70.0},
    "vein": {"max_dose": 60.0, "d2cc": 50.0},
}


class OARConstraintCheckerTool(BaseTool):
    """
    Tool for checking OAR dose constraints.

    Validates OAR doses against clinical constraints (TG-264 / ESTRO guidelines).
    Returns pass/fail status for each OAR and overall plan acceptability.
    """

    @property
    def name(self) -> str:
        return "oar_constraint_checker"

    @property
    def description(self) -> str:
        return (
            "Check OAR doses against clinical dose constraints. "
            "Validates rectum, bladder, urethra, bowel, kidney, liver, etc. "
            "Input: OAR dose metrics and optional custom constraints. "
            "Output: Per-OAR pass/fail status and overall plan acceptability."
        )

    @property
    def input_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "oar_metrics": {
                    "type": "object",
                    "description": "Dict of OAR name -> {max_dose, d2cc, mean_dose}",
                },
                "custom_constraints": {
                    "type": "object",
                    "description": "Custom constraints dict (overrides defaults)",
                },
                "strict_mode": {
                    "type": "boolean",
                    "default": True,
                    "description": "If True, any violation fails the plan",
                },
            },
            "required": ["oar_metrics"],
        }

    @property
    def output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "all_pass": {"type": "boolean", "description": "True if all constraints satisfied"},
                "violations": {"type": "array", "description": "List of constraint violations"},
                "oar_status": {"type": "object", "description": "Per-OAR pass/fail dict"},
            },
        }

    def _execute(self, **kwargs) -> ToolResult:
        oar_metrics = kwargs.get("oar_metrics", {})
        custom_constraints = kwargs.get("custom_constraints", {})
        strict_mode = kwargs.get("strict_mode", True)

        constraints = {**DEFAULT_CONSTRAINTS, **custom_constraints}

        violations = []
        oar_status = {}

        for oar_name, metrics in oar_metrics.items():
            oar_constraints = constraints.get(oar_name, {})
            status, v_list = self._check_oar(oar_name, metrics, oar_constraints)
            oar_status[oar_name] = status
            violations.extend(v_list)

        all_pass = len(violations) == 0

        return ToolResult(
            success=True,
            data={
                "all_pass": all_pass,
                "violations": violations,
                "oar_status": oar_status,
            },
            message=f"OAR constraint check: {'ALL PASS' if all_pass else f'{len(violations)} VIOLATION(S)'}",
            metadata={
                "all_pass": all_pass,
                "violations": violations,
                "oar_status": oar_status,
            },
        )

    def _check_oar(self, oar_name, metrics, constraints):
        violations = []
        status = "PASS"

        max_dose = metrics.get("max_dose", 0)
        d2cc = metrics.get("d2cc", 0)
        mean_dose = metrics.get("mean_dose", 0)

        if "max_dose" in constraints and max_dose > constraints["max_dose"]:
            violations.append({
                "oar": oar_name,
                "constraint_type": "max_dose",
                "actual": float(max_dose),
                "limit": constraints["max_dose"],
                "excess_pct": float((max_dose - constraints["max_dose"]) / constraints["max_dose"] * 100),
            })
            status = "FAIL"

        if "d2cc" in constraints and d2cc > constraints["d2cc"]:
            violations.append({
                "oar": oar_name,
                "constraint_type": "d2cc",
                "actual": float(d2cc),
                "limit": constraints["d2cc"],
                "excess_pct": float((d2cc - constraints["d2cc"]) / constraints["d2cc"] * 100),
            })
            status = "FAIL"

        return status, violations


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OAR Constraint Checker")
    parser.add_argument("--oar_metrics", required=True, help="JSON dict of OAR metrics")
    args = parser.parse_args()

    import json
    oar_metrics = json.loads(args.oar_metrics)

    tool = OARConstraintCheckerTool()
    result = tool._execute(oar_metrics=oar_metrics)
    print(result.message)
    for v in result.metadata["violations"]:
        print(f"  {v['oar']}: {v['constraint_type']} = {v['actual']:.1f} (limit: {v['limit']:.1f})")


if __name__ == "__main__":
    main()