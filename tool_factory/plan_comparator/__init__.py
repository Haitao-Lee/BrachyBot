"""
Plan Comparator Tool
====================
Compare multiple treatment plans side-by-side.
Rank plans by quality metrics and recommend the best option.
"""

import logging
from typing import Dict, Any, Optional, List
from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class PlanComparatorTool(BaseTool):
    """Compare and rank multiple treatment plans."""

    name = "plan_comparator"
    description = """Compare multiple treatment plans side-by-side and rank them.
Capabilities:
- compare: Compare 2+ plans across all metrics
- rank: Rank plans by weighted scoring
- diff: Show differences between two plans
- recommend: Recommend best plan with reasoning"""

    input_schema = {
        "action": {
            "type": "string",
            "description": "Action: compare, rank, diff, recommend",
            "enum": ["compare", "rank", "diff", "recommend"]
        },
        "plans": {
            "type": "array",
            "description": "List of plan objects with metrics (for compare/rank/recommend)",
        },
        "plan_a": {"type": "object", "description": "First plan (for diff)"},
        "plan_b": {"type": "object", "description": "Second plan (for diff)"},
        "weights": {
            "type": "object",
            "description": "Scoring weights (optional): {v100: 0.3, v200: 0.2, oar_compliance: 0.3, seed_count: 0.2}"
        },
    }
    output_schema = {
        "success": {"type": "boolean"},
        "data": {"type": "object"},
    }

    DEFAULT_WEIGHTS = {
        "v100": 0.30,
        "v200": 0.20,
        "d90": 0.20,
        "oar_compliance": 0.20,
        "seed_efficiency": 0.10,
    }

    def _score_plan(self, plan: Dict, weights: Dict) -> Dict:
        """Calculate a composite score for a plan."""
        metrics = plan.get("metrics", plan)

        v100 = metrics.get("v100", 0)
        v200 = metrics.get("v200", 0)
        d90 = metrics.get("d90", 0)
        plan_score = metrics.get("plan_score", 0)
        oar_violations = len(metrics.get("oar_violations", []))
        seed_count = plan.get("seed_count", metrics.get("seed_count", 0))
        ctv_volume = plan.get("ctv_volume_cc", metrics.get("ctv_volume_cc", 1))

        # Normalize scores (0-1)
        v100_score = min(v100 / 0.95, 1.0) if v100 else 0
        v200_score = max(1.0 - (v200 - 0.25) / 0.20, 0) if v200 else 1.0
        d90_score = min(d90 / 100, 1.0) if d90 else 0
        oar_score = max(1.0 - oar_violations * 0.25, 0)
        seed_efficiency = min(ctv_volume / max(seed_count, 1), 2.0) / 2.0 if seed_count else 0.5

        composite = (
            v100_score * weights.get("v100", 0.3) +
            v200_score * weights.get("v200", 0.2) +
            d90_score * weights.get("d90", 0.2) +
            oar_score * weights.get("oar_compliance", 0.2) +
            seed_efficiency * weights.get("seed_efficiency", 0.1)
        ) * 100

        return {
            "composite_score": round(composite, 1),
            "v100_score": round(v100_score * 100, 1),
            "v200_score": round(v200_score * 100, 1),
            "d90_score": round(d90_score * 100, 1),
            "oar_score": round(oar_score * 100, 1),
            "seed_efficiency_score": round(seed_efficiency * 100, 1),
            "raw_metrics": {
                "v100": v100, "v200": v200, "d90": d90,
                "plan_score": plan_score, "oar_violations": oar_violations,
                "seed_count": seed_count,
            },
        }

    def _compare_plans(self, plans: List[Dict], weights: Dict) -> ToolResult:
        """Compare multiple plans."""
        if len(plans) < 2:
            return ToolResult(success=False, error="Need at least 2 plans", message="Provide at least 2 plans to compare")

        scored = []
        for i, plan in enumerate(plans):
            score_data = self._score_plan(plan, weights)
            scored.append({
                "plan_index": i,
                "plan_name": plan.get("name", f"Plan {i+1}"),
                **score_data,
            })

        scored.sort(key=lambda x: x["composite_score"], reverse=True)

        # Find strengths and weaknesses
        for plan in scored:
            strengths = []
            weaknesses = []
            if plan["v100_score"] >= 90:
                strengths.append("Excellent V100 coverage")
            elif plan["v100_score"] < 70:
                weaknesses.append("Poor V100 coverage")
            if plan["v200_score"] >= 80:
                strengths.append("Good hot-spot control")
            elif plan["v200_score"] < 50:
                weaknesses.append("Excessive hot spots")
            if plan["oar_score"] >= 90:
                strengths.append("OAR constraints met")
            elif plan["oar_score"] < 70:
                weaknesses.append("OAR violations detected")
            plan["strengths"] = strengths
            plan["weaknesses"] = weaknesses

        return ToolResult(
            success=True,
            data={"comparison": scored, "best": scored[0]["plan_name"]},
            message=f"Compared {len(plans)} plans. Best: {scored[0]['plan_name']} (score: {scored[0]['composite_score']})"
        )

    def _rank_plans(self, plans: List[Dict], weights: Dict) -> ToolResult:
        """Rank plans by weighted scoring."""
        if not plans:
            return ToolResult(success=False, error="No plans provided", message="Provide plans to rank")

        scored = []
        for i, plan in enumerate(plans):
            score_data = self._score_plan(plan, weights)
            scored.append({
                "rank": 0,
                "plan_name": plan.get("name", f"Plan {i+1}"),
                **score_data,
            })

        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, plan in enumerate(scored):
            plan["rank"] = i + 1

        return ToolResult(
            success=True,
            data={"ranking": scored},
            message=f"Ranked {len(plans)} plans"
        )

    def _diff_plans(self, plan_a: Dict, plan_b: Dict) -> ToolResult:
        """Show differences between two plans."""
        metrics_a = plan_a.get("metrics", plan_a)
        metrics_b = plan_b.get("metrics", plan_b)

        diffs = {}
        all_keys = set(list(metrics_a.keys()) + list(metrics_b.keys()))
        for key in sorted(all_keys):
            val_a = metrics_a.get(key)
            val_b = metrics_b.get(key)
            if val_a != val_b:
                diff = None
                if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                    diff = round(val_b - val_a, 4)
                diffs[key] = {"plan_a": val_a, "plan_b": val_b, "difference": diff}

        name_a = plan_a.get("name", "Plan A")
        name_b = plan_b.get("name", "Plan B")

        return ToolResult(
            success=True,
            data={"plan_a": name_a, "plan_b": name_b, "differences": diffs, "total_diffs": len(diffs)},
            message=f"Found {len(diffs)} difference(s) between {name_a} and {name_b}"
        )

    def _recommend_plan(self, plans: List[Dict], weights: Dict) -> ToolResult:
        """Recommend the best plan with reasoning."""
        if not plans:
            return ToolResult(success=False, error="No plans", message="Provide plans to evaluate")

        scored = []
        for i, plan in enumerate(plans):
            score_data = self._score_plan(plan, weights)
            scored.append({"plan_name": plan.get("name", f"Plan {i+1}"), **score_data})

        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        best = scored[0]

        reasoning = [f"**{best['plan_name']}** recommended with composite score {best['composite_score']}/100"]
        if best["v100_score"] >= 90:
            reasoning.append(f"✅ V100 coverage: {best['raw_metrics']['v100']:.1%} (excellent)")
        elif best["v100_score"] >= 70:
            reasoning.append(f"⚠️ V100 coverage: {best['raw_metrics']['v100']:.1%} (acceptable)")
        else:
            reasoning.append(f"❌ V100 coverage: {best['raw_metrics']['v100']:.1%} (below target)")

        if best["raw_metrics"]["oar_violations"] == 0:
            reasoning.append("✅ All OAR constraints satisfied")
        else:
            reasoning.append(f"⚠️ {best['raw_metrics']['oar_violations']} OAR violation(s)")

        reasoning.append(f"📊 Seed count: {best['raw_metrics']['seed_count']}")

        return ToolResult(
            success=True,
            data={"recommendation": best, "all_scores": scored, "reasoning": reasoning},
            message=f"Recommended: {best['plan_name']} (score: {best['composite_score']})"
        )

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "")
        weights = kwargs.get("weights", self.DEFAULT_WEIGHTS)

        if not action:
            return ToolResult(success=False, error="No action", message="Specify: compare, rank, diff, recommend")

        if action == "compare":
            return self._compare_plans(kwargs.get("plans", []), weights)
        elif action == "rank":
            return self._rank_plans(kwargs.get("plans", []), weights)
        elif action == "diff":
            plan_a = kwargs.get("plan_a")
            plan_b = kwargs.get("plan_b")
            if not plan_a or not plan_b:
                return ToolResult(success=False, error="Need plan_a and plan_b", message="Provide two plans to diff")
            return self._diff_plans(plan_a, plan_b)
        elif action == "recommend":
            return self._recommend_plan(kwargs.get("plans", []), weights)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}", message="Valid: compare, rank, diff, recommend")
