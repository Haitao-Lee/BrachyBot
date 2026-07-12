"""
Plan Reviewer Agent
===================
Reviews brachytherapy plans using deterministic checks plus optional LLM
interpretation. Clinical thresholds are accepted only from explicit runtime
configuration or retrieved clinical knowledge, never from prompt examples.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .base_agent import LLMCapableAgent
from .clinical_metrics import (
    cumulative_dvh_consistency,
    dose_ratio,
    first_numeric,
    match_constraint_name,
    metric_value,
    normalized_fraction,
)
from communication.protocol import AgentMessage, AgentResponse, AgentRole, ReviewResult

logger = logging.getLogger(__name__)


def _load_medical_prompts() -> str:
    """Load medical safety and clinical KB instructions for the LLM layer."""
    prompts_dir = os.path.join(os.path.dirname(__file__), "..", "config", "prompts")
    parts: List[str] = []
    for fname in ("medical_safety.md", "clinical_kb.md"):
        fpath = os.path.join(prompts_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    parts.append(f.read())
            except Exception as exc:
                logger.debug("Failed to load %s: %s", fname, exc)
    return "\n\n---\n\n".join(parts)


_MEDICAL_SYSTEM_PROMPT = _load_medical_prompts()


class PlanReviewer(LLMCapableAgent):
    """
    Advisory plan reviewer.

    Layer 1 is deterministic and checks only explicit `plan_config`
    thresholds/constraints. If source-backed constraints are absent, the plan is
    marked conditional instead of being approved from generic defaults.
    """

    _CLINICAL_PROMPT = """You are a brachytherapy plan reviewer.

Use the deterministic check results below and provide a concise clinical interpretation.

## Deterministic Check Results
{deterministic_results}

## Prescription / Unit Context
{prescription_context}

## Rules
- Do not invent target or OAR thresholds.
- Do not treat generic sanity checks as clinical pass/fail criteria.
- If standards are missing, say which clinical_kb lookup is required.
- Do not contradict deterministic facts or actual tool metrics.
- Keep the answer under 200 words.

## Output Format
Return JSON only:
{{
  "clinical_summary": "1-2 sentence assessment",
  "key_concerns": ["concern with actual value and sourced/configured limit"],
  "suggestions": ["actionable suggestion or required clinical_kb lookup"],
  "risk_level": "low|medium|high"
}}"""

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.PLAN_REVIEWER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content
        dose_metrics = content.get("dose_metrics", {}) or {}
        plan_info = content.get("plan_info", {}) or {}
        plan_config = content.get("plan_config", {}) or {}

        self._user_message = content.get("user_message", "")
        self._conversation_state = content.get("conversation_state", {})
        self._patient_info = content.get("patient_info", {})
        self._segmentation = content.get("segmentation", {})
        self._distilled_context = content.get("distilled_context", "")
        self._lang = content.get("lang", "en")

        det_results = self._deterministic_checks(dose_metrics, plan_config)
        llm_results = await self._llm_interpretation(det_results, plan_config, content)
        merged = self._merge_results(det_results, llm_results, plan_info)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=merged,
            confidence=merged.confidence,
            reasoning=self._build_reasoning(det_results, llm_results),
            suggestions=merged.suggestions,
            warnings=list(merged.concerns),
        )

    def _deterministic_checks(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> dict:
        issues: List[dict] = []
        metrics_checked: List[dict] = []
        unverified: List[str] = []

        target_checks = self._configured_target_checks(plan_config)
        for metric, cfg in target_checks.items():
            value = self._metric_value(dose_metrics, metric)
            if value is None:
                continue
            threshold = cfg["threshold"]
            unit = cfg.get("unit", "")
            if unit == "fraction":
                value = normalized_fraction(value)
                threshold = normalized_fraction(threshold)
            elif unit == "fraction_of_prescription":
                value = dose_ratio(dose_metrics, plan_config, metric)
                threshold = normalized_fraction(threshold)
            if value is None or threshold is None:
                unverified.append(
                    f"{metric.upper()} could not be unit-normalized from the supplied dose context."
                )
                continue
            metrics_checked.append({"metric": metric, "value": value, "source": "plan_config"})
            status = self._compare(value, cfg["operator"], threshold)
            if status != "OK":
                issues.append({
                    "metric": metric.upper(),
                    "value": value,
                    "threshold": threshold,
                    "operator": cfg["operator"],
                    "status": status,
                    "source": "plan_config",
                    "unit": unit,
                })

        if not target_checks:
            unverified.append("No source-backed target coverage thresholds were supplied in plan_config.")

        oar_issues: List[dict] = []
        oar_metrics = dose_metrics.get("oar_metrics", {})
        oar_constraints = plan_config.get("oar_constraints", {}) or {}
        if isinstance(oar_metrics, dict) and isinstance(oar_constraints, dict) and oar_constraints:
            oar_issues.extend(self._check_oar_constraints(oar_metrics, oar_constraints))
        elif isinstance(oar_metrics, dict) and oar_metrics:
            unverified.append("OAR dose metrics are present, but no source-backed OAR constraints were supplied.")

        advisory_issues = self._advisory_sanity_checks(dose_metrics, plan_config)

        total_checks = len(metrics_checked) + len(oar_constraints)
        issue_count = len(issues) + len(oar_issues)
        if total_checks == 0:
            score = max(3.0, 6.0 - len(advisory_issues) * 0.9)
        else:
            score = max(3.0, 10.0 - (issue_count / max(1, total_checks)) * 7.0)
            if advisory_issues:
                score = max(3.0, score - len(advisory_issues) * 0.6)

        return {
            "score": round(score, 1),
            "issues": issues,
            "oar_issues": oar_issues,
            "advisory_issues": advisory_issues,
            "metrics_checked": metrics_checked,
            "unverified": unverified,
            "has_clinical_thresholds": total_checks > 0,
        }

    def _advisory_sanity_checks(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any]) -> List[str]:
        """Check mathematical consistency without inventing clinical limits."""
        concerns = cumulative_dvh_consistency(dose_metrics)
        missing = [
            key for key in ("v100", "d90", "max_dose", "mean_dose")
            if self._metric_value(dose_metrics, key) is None
        ]
        if missing:
            concerns.append(
                "Plan output is missing core review metrics: " + ", ".join(missing) + "."
            )
        return concerns

    @staticmethod
    def _normalized_fraction(value: Optional[float]) -> Optional[float]:
        return normalized_fraction(value)

    def _dose_ratio_or_fraction(self, dose_metrics: Dict[str, Any], plan_config: Dict[str, Any], key: str) -> Optional[float]:
        return dose_ratio(dose_metrics, plan_config, key)

    def _configured_target_checks(self, plan_config: Dict[str, Any]) -> Dict[str, dict]:
        checks: Dict[str, dict] = {}

        aliases = {
            "v100": ("v100_min", "v100_target"),
            "v150": ("v150_max", "v150_limit"),
            "v200": ("v200_max", "v200_limit"),
        }
        for metric, keys in aliases.items():
            for key in keys:
                if key in plan_config:
                    checks[metric] = {
                        "threshold": float(plan_config[key]),
                        "operator": ">=" if metric == "v100" else "<=",
                        "unit": "fraction",
                    }
                    break

        if "d90_min_gy" in plan_config:
            checks["d90"] = {"threshold": float(plan_config["d90_min_gy"]), "operator": ">=", "unit": "Gy"}
        elif "d90_min_pct" in plan_config:
            checks["d90"] = {
                "threshold": float(plan_config["d90_min_pct"]),
                "operator": ">=",
                "unit": "fraction_of_prescription",
            }
        elif "d90_min" in plan_config:
            checks["d90"] = {
                "threshold": float(plan_config["d90_min"]),
                "operator": ">=",
                "unit": str(plan_config.get("d90_unit", "configured")),
            }

        return checks

    def _check_oar_constraints(self, oar_metrics: Dict[str, Any], constraints: Dict[str, Any]) -> List[dict]:
        issues: List[dict] = []
        normalized = {str(k): v for k, v in constraints.items() if isinstance(v, dict)}
        for organ_name, organ_vals in oar_metrics.items():
            if not isinstance(organ_vals, dict):
                continue
            source_name = match_constraint_name(organ_name, normalized)
            constraint = normalized.get(source_name) if source_name else None
            if not constraint:
                continue
            for metric_key, aliases in {
                "d2cc": ("d2cc", "D2cc"),
                "max_dose": ("max_dose", "dmax", "Dmax"),
                "mean_dose": ("mean_dose", "dmean", "Dmean"),
            }.items():
                limit = constraint.get(metric_key)
                if limit is None:
                    continue
                value = self._first_numeric(organ_vals, aliases)
                if value is None:
                    continue
                if value > float(limit):
                    issues.append({
                        "organ": organ_name,
                        "matched_constraint": source_name,
                        "metric": metric_key,
                        "value": value,
                        "limit": float(limit),
                        "status": "EXCEEDS",
                        "source": "plan_config",
                    })
        return issues

    @staticmethod
    def _metric_value(metrics: Dict[str, Any], key: str) -> Optional[float]:
        return metric_value(metrics, key)

    @staticmethod
    def _first_numeric(values: Dict[str, Any], keys) -> Optional[float]:
        return first_numeric(values, keys)

    @staticmethod
    def _compare(value: float, operator: str, threshold: float) -> str:
        if operator == ">=":
            return "OK" if value >= threshold else "EXCEEDS"
        if operator == "<=":
            return "OK" if value <= threshold else "EXCEEDS"
        return "UNKNOWN"

    async def _llm_interpretation(
        self,
        det_results: dict,
        plan_config: Dict[str, Any],
        full_context: Optional[dict] = None,
    ) -> Optional[dict]:
        if not self.llm_callback:
            return None

        lines = []
        for issue in det_results["issues"]:
            unit = f" {issue.get('unit')}" if issue.get("unit") else ""
            lines.append(
                f"- {issue['metric']}={issue['value']:.3g}{unit}, "
                f"required {issue['operator']} {issue['threshold']:.3g}{unit}, "
                f"status={issue['status']}, source={issue['source']}"
            )
        for issue in det_results["oar_issues"]:
            lines.append(
                f"- {issue['organ']} {issue['metric']}={issue['value']:.2f} Gy, "
                f"limit={issue['limit']:.2f} Gy, status={issue['status']}, source={issue['source']}"
            )
        for item in det_results["unverified"]:
            lines.append(f"- Unverified: {item}")
        for item in det_results.get("advisory_issues", []):
            lines.append(f"- Advisory sanity issue: {item}")
        if not lines:
            lines.append("No deterministic concerns.")

        context_text = self._format_context(full_context or {})
        prescription_context = json.dumps({
            "prescription": (
                plan_config.get("in_lowest_energy")
                if plan_config.get("in_lowest_energy") is not None
                else plan_config.get("prescribed_dose")
            ),
            "dose_unit": plan_config.get("dose_unit", "from tool output"),
            "configured_threshold_keys": sorted(k for k in plan_config.keys() if "v" in k.lower() or "d90" in k.lower() or "constraint" in k.lower()),
        }, ensure_ascii=False)

        prompt = self._CLINICAL_PROMPT.format(
            deterministic_results="\n".join(lines),
            prescription_context=prescription_context,
        )
        prompt = f"{context_text}\n\n{prompt}"

        # LANGUAGE INSTRUCTION: if the user's language is Chinese, instruct
        # the LLM to output in Chinese so the review sections are consistent
        # with the rest of the chat response.
        if getattr(self, "_lang", "en") == "zh":
            prompt += "\n\n**Language**: 请用中文回答。所有评价、建议和总结都必须使用中文。"

        try:
            response = await self.call_llm(
                prompt,
                system_prompt=_MEDICAL_SYSTEM_PROMPT or self._system_prompt,
                temperature=0.2,
            )
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            logger.debug("LLM interpretation failed; using deterministic results only: %s", exc)
        return None

    def _format_context(self, ctx: Dict[str, Any]) -> str:
        sections: List[str] = []
        user_msg = ctx.get("user_message", "") or getattr(self, "_user_message", "")
        if user_msg:
            sections.append(f"## User Request\n{user_msg[:300]}")
        distilled = ctx.get("distilled_context", "") or getattr(self, "_distilled_context", "")
        if distilled:
            sections.append(f"## Distilled Context\n{distilled}")

        pt = ctx.get("patient_info", {}) or getattr(self, "_patient_info", {})
        seg = ctx.get("segmentation", {}) or getattr(self, "_segmentation", {})
        plan = ctx.get("planning", {})
        clinical_lines: List[str] = []
        if pt.get("tumor_type"):
            clinical_lines.append(f"Tumor type: {pt['tumor_type']}")
        if pt.get("organ"):
            clinical_lines.append(f"Organ: {pt['organ']}")
        if seg.get("ctv_voxels"):
            clinical_lines.append(f"CTV voxels: {seg['ctv_voxels']}")
        if seg.get("oar_count"):
            clinical_lines.append(f"OARs segmented: {seg['oar_count']}")
        if plan.get("total_seeds"):
            clinical_lines.append(f"Seeds: {plan['total_seeds']}, trajectories: {plan.get('num_trajectories', 0)}")
        if clinical_lines:
            sections.append("## Clinical Context\n" + "\n".join(clinical_lines))
        return "\n\n".join(sections) if sections else "No additional context available."

    def _merge_results(self, det_results: dict, llm_results: Optional[dict], plan_info: Dict[str, Any]) -> ReviewResult:
        concerns: List[str] = []
        for issue in det_results["issues"]:
            unit = f" {issue.get('unit')}" if issue.get("unit") else ""
            concerns.append(
                f"{issue['metric']}={issue['value']:.3g}{unit}, "
                f"required {issue['operator']} {issue['threshold']:.3g}{unit} ({issue['status']})"
            )
        for issue in det_results["oar_issues"]:
            concerns.append(
                f"{issue['organ']} {issue['metric']}={issue['value']:.1f} Gy, "
                f"limit={issue['limit']:.1f} Gy ({issue['status']})"
            )
        concerns.extend(det_results.get("advisory_issues", []))
        concerns.extend(det_results["unverified"])

        suggestions: List[str] = []
        if llm_results:
            suggestions.extend(llm_results.get("suggestions", []) or [])
            summary = llm_results.get("clinical_summary", "")
            if summary and len(summary) > 20:
                suggestions.insert(0, summary)
        elif det_results.get("advisory_issues"):
            suggestions.append("Recheck seed distribution, dose scaling, and DVH before clinical approval.")
        elif det_results["unverified"]:
            suggestions.append("Query clinical_kb for site-specific target and OAR limits before final clinical approval.")

        if not plan_info.get("total_seeds"):
            concerns.append("Plan info does not report any seeds.")

        if det_results["issues"] or det_results["oar_issues"] or det_results.get("advisory_issues"):
            decision = "conditional"
        elif det_results["has_clinical_thresholds"] and not det_results["unverified"]:
            decision = "pass"
        else:
            decision = "conditional"

        confidence = 0.9 if det_results["has_clinical_thresholds"] else 0.65
        if llm_results:
            confidence = min(0.95, confidence + 0.05)

        return ReviewResult(
            reviewer="Plan Review",
            decision=decision,
            score=det_results["score"],
            concerns=concerns,
            suggestions=suggestions[:5],
            confidence=confidence,
        )

    def _build_reasoning(self, det_results: dict, llm_results: Optional[dict]) -> str:
        lines = [f"Deterministic score: {det_results['score']}/10"]
        lines.append(f"Target issues: {len(det_results['issues'])}; OAR issues: {len(det_results['oar_issues'])}")
        if det_results.get("advisory_issues"):
            lines.append(f"Advisory sanity issues: {len(det_results['advisory_issues'])}")
        if det_results["unverified"]:
            lines.append(f"Unverified clinical thresholds: {len(det_results['unverified'])}")
        if llm_results:
            lines.append(f"LLM risk level: {llm_results.get('risk_level', 'unknown')}")
        return "\n".join(lines)

    def format_as_appendix(self, result: ReviewResult, lang: str = "en") -> str:
        if not result:
            return ""
        if result.score >= 8.0 and not result.concerns:
            return ""

        if lang == "zh":
            lines = [f"### 质量审查 (评分: {result.score:.1f}/10)"]
            if result.concerns:
                lines.append("\n**需要关注**:")
                lines.extend(f"- {c}" for c in result.concerns[:5])
            if result.suggestions:
                lines.append("\n**建议**:")
                lines.extend(f"- {s}" for s in result.suggestions[:3])
        else:
            lines = [f"### Quality Review (Score: {result.score:.1f}/10)"]
            if result.concerns:
                lines.append("\n**Concerns**:")
                lines.extend(f"- {c}" for c in result.concerns[:5])
            if result.suggestions:
                lines.append("\n**Suggestions**:")
                lines.extend(f"- {s}" for s in result.suggestions[:3])
        return "\n".join(lines)
