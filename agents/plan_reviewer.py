"""
Plan Reviewer Agent
===================
Dual-layer review with GLOBAL CONTEXT AWARENESS: deterministic threshold checks + LLM clinical judgment.

Layer 1 (deterministic): metric vs threshold comparisons. Cannot be wrong.
Layer 2 (LLM): clinical interpretation WITH full context (user intent, cancer type,
               CTV size, OAR count) and medical safety rules. Bounded by prompt.

The LLM layer is optional — if it fails, deterministic results are used.
The LLM cannot override hard facts (e.g., "V100=0.85" stays "V100=0.85").

SUB-AGENT GLOBAL VIEW: This agent reads the full context passed by the orchestrator
to make clinically relevant judgments. A bystander with full information gives
better advice than one with partial information.
"""

import json
import re
import logging
import os
from typing import Dict, List, Any, Optional
from .base_agent import LLMCapableAgent
from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, Priority
)

logger = logging.getLogger(__name__)

# Load system-level medical prompts once at module level for domain expertise
def _load_medical_prompts():
    """Load medical safety + clinical KB prompts."""
    prompts_dir = os.path.join(os.path.dirname(__file__), '..', 'config', 'prompts')
    parts = []
    for fname in ['medical_safety.md', 'clinical_kb.md']:
        fpath = os.path.join(prompts_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    parts.append(f.read())
            except Exception as e:
                logger.debug(f"Failed to load {fname}: {e}")
    return "\n\n---\n\n".join(parts) if parts else ""

_MEDICAL_SYSTEM_PROMPT = _load_medical_prompts()


class PlanReviewer(LLMCapableAgent):
    """
    Reviews treatment plans with dual-layer checks.

    Layer 1 (deterministic):
    - Compare V100, V150, V200, D90, D2cc against thresholds
    - Check OAR constraints
    - These results are ALWAYS included, cannot be overridden by LLM

    Layer 2 (LLM, optional):
    - Clinical interpretation: "D2cc=85 Gy for duodenum is concerning
      because duodenum is a serial organ with D2cc limit ~75 Gy"
    - Actionable suggestions: "Consider reducing seed density near
      the duodenum or adding a margin constraint"
    - If LLM fails, only Layer 1 results are returned
    """

    # Default OAR constraints as multipliers of prescription dose
    _DEFAULT_OAR_MULTIPLIERS = {
        "duodenum": {"d2cc": 1.0},
        "stomach": {"d2cc": 1.0},
        "small_bowel": {"d2cc": 1.0},
        "colon": {"d2cc": 1.0},
        "spinal_cord": {"d2cc": 0.8},
        "liver": {"d2cc": 0.8},
        "kidney": {"d2cc": 0.6},
    }

    # LLM prompt for clinical interpretation
    _CLINICAL_PROMPT = """You are a brachytherapy plan reviewer. Given the following deterministic metric checks, provide a brief clinical interpretation.

## Deterministic Check Results
{deterministic_results}

## Prescription Dose
{prescription} Gy (normalized)

## Rules
- Do NOT contradict the deterministic results (e.g., if V100=0.85 is flagged as "below target", do NOT say it's acceptable)
- Focus on: clinical significance, actionable suggestions, risk context
- Be specific: cite actual values, not vague statements
- Keep response under 200 words

## Output Format (JSON)
{{
    "clinical_summary": "1-2 sentence overall assessment",
    "key_concerns": ["concern1 with specific values", "concern2"],
    "suggestions": ["actionable suggestion 1", "actionable suggestion 2"],
    "risk_level": "low|medium|high"
}}"""

    def __init__(self, llm_callback=None):
        super().__init__(AgentRole.PLAN_REVIEWER, llm_callback)

    async def process(self, message: AgentMessage) -> AgentResponse:
        content = message.content
        dose_metrics = content.get("dose_metrics", {})
        plan_info = content.get("plan_info", {})
        plan_config = content.get("plan_config", {})

        # ── GLOBAL CONTEXT: read full situational awareness ──────────
        # As a bystander/observer, we need full information to give clinically
        # relevant advice. The orchestrator passes these via _build_agent_context().
        self._user_message = content.get("user_message", "")
        self._conversation_state = content.get("conversation_state", {})
        self._patient_info = content.get("patient_info", {})
        self._segmentation = content.get("segmentation", {})
        self._distilled_context = content.get("distilled_context", "")

        prescription = plan_config.get("in_lowest_energy", 1.0)

        # ── Layer 1: Deterministic checks (always correct) ─────────
        det_results = self._deterministic_checks(dose_metrics, prescription, plan_config)

        # ── Layer 2: LLM clinical interpretation with FULL CONTEXT ──
        llm_results = await self._llm_interpretation(det_results, prescription, content)

        # ── Merge: deterministic facts + LLM judgment ──────────────
        merged = self._merge_results(det_results, llm_results)

        return AgentResponse(
            agent_role=self.role,
            success=True,
            result=merged,
            confidence=merged.confidence,
            reasoning=self._build_reasoning(det_results, llm_results),
            suggestions=merged.suggestions,
            warnings=[c for c in merged.concerns],
        )

    def _deterministic_checks(self, dose_metrics: Dict, prescription: float,
                               plan_config: Dict) -> dict:
        """Layer 1: Pure threshold comparisons. Returns structured data."""
        issues = []
        metrics_checked = []

        # Target coverage checks
        targets = {
            "v100": {"threshold": plan_config.get("v100_target", 0.95),
                     "warn": plan_config.get("v100_warn", 0.90),
                     "direction": "above", "unit": "%"},
            "v150": {"threshold": plan_config.get("v150_limit", 0.50),
                     "warn": plan_config.get("v150_warn", 0.60),
                     "direction": "below", "unit": "%"},
            "v200": {"threshold": plan_config.get("v200_limit", 0.20),
                     "warn": plan_config.get("v200_warn", 0.30),
                     "direction": "below", "unit": "%"},
        }

        for metric, cfg in targets.items():
            value = dose_metrics.get(metric)
            if value is None:
                continue
            try:
                value = float(str(value).replace("%", ""))
            except (ValueError, TypeError):
                continue

            metrics_checked.append({"metric": metric, "value": value})

            if cfg["direction"] == "above":
                if value >= cfg["threshold"]:
                    status = "OK"
                elif value >= cfg["warn"]:
                    status = "WARN"
                else:
                    status = "EXCEEDS"
            else:
                if value <= cfg["threshold"]:
                    status = "OK"
                elif value <= cfg["warn"]:
                    status = "WARN"
                else:
                    status = "EXCEEDS"

            if status != "OK":
                issues.append({
                    "metric": metric.upper(),
                    "value": value,
                    "threshold": cfg["threshold"],
                    "status": status,
                    "direction": cfg["direction"],
                })

        # D90 check
        d90 = dose_metrics.get("d90")
        if d90 is not None:
            try:
                d90_val = float(str(d90).replace("Gy", ""))
                metrics_checked.append({"metric": "d90", "value": d90_val})
                if d90_val < 0.85 * prescription:
                    issues.append({
                        "metric": "D90", "value": d90_val,
                        "threshold": prescription, "status": "EXCEEDS",
                        "direction": "above",
                    })
                elif d90_val < prescription:
                    issues.append({
                        "metric": "D90", "value": d90_val,
                        "threshold": prescription, "status": "WARN",
                        "direction": "above",
                    })
            except (ValueError, TypeError):
                pass

        # OAR constraint checks
        oar_metrics = dose_metrics.get("oar_metrics", {})
        config_oar = plan_config.get("oar_constraints", {})
        oar_issues = []

        for organ_name, organ_vals in oar_metrics.items():
            organ_lower = organ_name.lower()
            constraint = None
            for oar_key, mult in self._DEFAULT_OAR_MULTIPLIERS.items():
                if oar_key in organ_lower:
                    actual_mult = config_oar.get(organ_name, mult)
                    constraint = {k: v * prescription for k, v in actual_mult.items()}
                    break

            if constraint is None:
                continue

            d2cc = organ_vals.get("d2cc") or organ_vals.get("D2cc")
            if d2cc is not None:
                try:
                    d2cc_val = float(str(d2cc).replace("Gy", ""))
                    limit = constraint.get("d2cc", prescription)
                    if d2cc_val > limit:
                        oar_issues.append({
                            "organ": organ_name,
                            "metric": "D2cc",
                            "value": d2cc_val,
                            "limit": limit,
                            "status": "EXCEEDS",
                        })
                    elif d2cc_val > 0.8 * limit:
                        oar_issues.append({
                            "organ": organ_name,
                            "metric": "D2cc",
                            "value": d2cc_val,
                            "limit": limit,
                            "status": "WARN",
                        })
                except (ValueError, TypeError):
                    pass

        # Compute deterministic score
        total_checks = len(metrics_checked) + max(1, len(oar_issues))
        issue_count = len(issues) + len(oar_issues)
        score = max(3.0, 10.0 - (issue_count / max(1, total_checks)) * 7.0)

        return {
            "score": round(score, 1),
            "issues": issues,
            "oar_issues": oar_issues,
            "metrics_checked": metrics_checked,
            "prescription": prescription,
        }

    async def _llm_interpretation(self, det_results: dict,
                                    prescription: float,
                                    full_context: dict = None) -> Optional[dict]:
        """Layer 2: LLM clinical interpretation with FULL GLOBAL CONTEXT.

        As a bystander/observer, this agent uses all available information
        to make clinically relevant judgments about plan quality.
        """
        if not self.llm_callback:
            return None

        # Format deterministic results
        lines = []
        for issue in det_results["issues"]:
            lines.append(f"- {issue['metric']}={issue['value']:.2f}, "
                        f"threshold={issue['threshold']:.2f}, status={issue['status']}")
        for issue in det_results["oar_issues"]:
            lines.append(f"- {issue['organ']} {issue['metric']}={issue['value']:.2f} Gy, "
                        f"limit={issue['limit']:.2f} Gy, status={issue['status']}")
        if not lines:
            lines.append("All metrics within targets.")

        det_text = "\n".join(lines)

        # ── Build comprehensive context from all sources ──────────────
        ctx = full_context or {}
        ctx_sections = []

        # User's original request (what are they trying to achieve?)
        user_msg = ctx.get("user_message", "") or getattr(self, '_user_message', '')
        if user_msg:
            ctx_sections.append(f"## User's Request\n{user_msg[:300]}")

        # Distilled context from orchestrator
        distilled = ctx.get("distilled_context", "") or getattr(self, '_distilled_context', '')
        if distilled:
            ctx_sections.append(f"## Distilled Context\n{distilled}")

        # Clinical context (tumor, CTV, OARs, seeds)
        pt = ctx.get("patient_info", {}) or getattr(self, '_patient_info', {})
        seg = ctx.get("segmentation", {}) or getattr(self, '_segmentation', {})
        plan = ctx.get("planning", {})

        clinical_lines = []
        if pt.get("tumor_type"):
            clinical_lines.append(f"Tumor type: {pt['tumor_type']}")
        if pt.get("organ"):
            clinical_lines.append(f"Organ: {pt['organ']}")
        if seg.get("ctv_voxels"):
            clinical_lines.append(f"CTV: {seg['ctv_voxels']} voxels, {seg.get('ctv_volume_mm3', 0)/1000:.1f} cm³")
        if seg.get("oar_count"):
            clinical_lines.append(f"OARs segmented: {seg['oar_count']} organs")
        if plan.get("total_seeds"):
            clinical_lines.append(f"Seeds: {plan['total_seeds']}, Trajectories: {plan.get('num_trajectories', 0)}")
        if plan.get("mode"):
            clinical_lines.append(f"Planning mode: {plan['mode']}")

        if clinical_lines:
            ctx_sections.append("## Clinical Context\n" + "\n".join(clinical_lines))

        # Conversation state (what's been completed)
        conv_state = ctx.get("conversation_state", {}) or getattr(self, '_conversation_state', {})
        if conv_state:
            state_items = []
            if conv_state.get('ctv_segmented'):
                state_items.append("CTV ✓")
            if conv_state.get('oar_segmented'):
                state_items.append("OAR ✓")
            if conv_state.get('planning_completed'):
                state_items.append("Planning ✓")
            if state_items:
                ctx_sections.append(f"## Pipeline State\n{', '.join(state_items)}")

        context_text = "\n\n".join(ctx_sections) if ctx_sections else "No additional context available."

        # ── Build the full prompt with medical domain expertise ───────
        prompt = self._CLINICAL_PROMPT.format(
            deterministic_results=det_text,
            prescription=prescription,
        )
        prompt = f"{context_text}\n\n{prompt}"

        # Add medical safety rules as domain expertise (truncated to avoid token overflow)
        if _MEDICAL_SYSTEM_PROMPT:
            prompt += f"\n\n## Medical Safety Rules (for reference)\n{_MEDICAL_SYSTEM_PROMPT[:2000]}"

        try:
            response = await self.call_llm(prompt, temperature=0.2)
            # Parse JSON response
            json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.debug(f"LLM interpretation failed (using deterministic only): {e}")

        return None

    def _merge_results(self, det_results: dict, llm_results: Optional[dict]) -> ReviewResult:
        """Merge deterministic facts with LLM judgment."""
        issues = det_results["issues"]
        oar_issues = det_results["oar_issues"]
        score = det_results["score"]

        # Build concerns from deterministic results (hard facts)
        concerns = []
        for issue in issues:
            concerns.append(
                f"{issue['metric']}={issue['value']:.2f}, "
                f"threshold={issue['threshold']:.2f} ({issue['status']})"
            )
        for issue in oar_issues:
            concerns.append(
                f"{issue['organ']} {issue['metric']}={issue['value']:.1f} Gy, "
                f"limit={issue['limit']:.1f} Gy ({issue['status']})"
            )

        # Add LLM suggestions if available
        suggestions = []
        if llm_results:
            suggestions = llm_results.get("suggestions", [])
            # Add LLM clinical summary as a suggestion if it adds value
            summary = llm_results.get("clinical_summary", "")
            if summary and len(summary) > 20:
                suggestions.insert(0, summary)

        return ReviewResult(
            reviewer="Plan Review",
            decision="pass" if score >= 8 else "conditional",
            score=score,
            concerns=concerns,
            suggestions=suggestions[:5],
            confidence=0.9 if not llm_results else 0.95,
        )

    def _score_to_decision(self, score: float) -> str:
        if score >= 7:
            return "pass"
        elif score >= 5:
            return "conditional"
        else:
            return "reject"

    def _build_reasoning(self, det_results: dict, llm_results: Optional[dict]) -> str:
        lines = [f"Deterministic score: {det_results['score']}/10"]
        lines.append(f"Issues: {len(det_results['issues'])} target, {len(det_results['oar_issues'])} OAR")
        if llm_results:
            lines.append(f"LLM risk level: {llm_results.get('risk_level', 'unknown')}")
        return "\n".join(lines)

    def format_as_appendix(self, result: ReviewResult, lang: str = "en") -> str:
        """Format plan review as a markdown appendix section.

        Returns empty string if everything is OK (score >= 8 and no concerns).
        """
        if not result:
            return ""

        if result.score >= 8.0 and not result.concerns:
            return ""

        if lang == "zh":
            lines = [f"### 📊 质量评审 (评分: {result.score:.1f}/10)"]
            if result.concerns:
                lines.append("\n**需关注**:")
                for c in result.concerns[:5]:
                    lines.append(f"- {c}")
            if result.suggestions:
                lines.append("\n**临床建议**:")
                for s in result.suggestions[:3]:
                    lines.append(f"- {s}")
        else:
            lines = [f"### 📊 Quality Review (Score: {result.score:.1f}/10)"]
            if result.concerns:
                lines.append("\n**Concerns**:")
                for c in result.concerns[:5]:
                    lines.append(f"- {c}")
            if result.suggestions:
                lines.append("\n**Clinical Suggestions**:")
                for s in result.suggestions[:3]:
                    lines.append(f"- {s}")

        return "\n".join(lines)
