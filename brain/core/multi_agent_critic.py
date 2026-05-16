"""
Multi-Agent Critique System
============================
For critical clinical decisions, multiple specialized critic agents review the plan
before it is presented to the user. This reduces errors from single-model bias.

Inspired by: Multi-Agent Reflexion (MAR) and MedAgent-Pro's decider architecture.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CritiqueResult:
    persona: str
    verdict: str
    score: float
    concerns: list
    recommendations: list
    confidence: float


@dataclass
class ConsensusReport:
    overall_verdict: str
    average_score: float
    unanimous: bool
    critiques: list
    final_recommendation: str
    requires_human_review: bool


class MultiAgentCritic:
    """
    Spawns multiple critic personas to review a clinical plan or decision.
    Each persona has a specific focus area and voting power.
    """

    CRITICAL_PERSONAS = [
        {
            "name": "Dosimetry Safety Expert",
            "focus": "Evaluate whether dose distribution is safe and within constraints. "
                     "Check D90, V100, V150, V200 for prostate or equivalent metrics for other sites. "
                     "Verify OAR doses are within QUANTEC/TG-43 limits.",
            "weight": 1.5,
        },
        {
            "name": "Clinical Protocol Reviewer",
            "focus": "Check if the plan follows standard clinical protocols. "
                     "Verify seed placement follows accepted patterns. "
                     "Check if coverage is adequate for the CTV. "
                     "Flag any deviations from standard practice.",
            "weight": 1.3,
        },
        {
            "name": "Risk Assessment Specialist",
            "focus": "Identify potential risks and complications. "
                     "Consider what could go wrong with this plan. "
                     "Evaluate robustness to uncertainties (seed migration, edema, contouring errors). "
                     "Suggest mitigation strategies.",
            "weight": 1.2,
        },
        {
            "name": "Quality Assurance Auditor",
            "focus": "Perform a systematic QA check. "
                     "Verify all required steps were completed. "
                     "Check for consistency between segmentation, planning, and dose calculation. "
                     "Flag any missing evaluations or incomplete analyses.",
            "weight": 1.0,
        },
    ]

    def __init__(self, llm_callback=None):
        self.llm_callback = llm_callback
        self.critique_history = []
        self._history_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "memory", "data", "critique_history.json",
        )
        self._load_history()

    def _load_history(self):
        if os.path.exists(self._history_path):
            try:
                with open(self._history_path, "r") as f:
                    self.critique_history = json.load(f)
            except (json.JSONDecodeError, TypeError):
                self.critique_history = []

    def _save_history(self):
        os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
        with open(self._history_path, "w") as f:
            json.dump(self.critique_history[-100:], f, indent=2, ensure_ascii=False)

    def review_plan(self, plan_description: str, dose_metrics: dict = None,
                    tool_chain: list = None, context: str = "") -> ConsensusReport:
        critiques = []

        for persona in self.CRITICAL_PERSONAS:
            critique = self._get_critique(
                persona, plan_description, dose_metrics, tool_chain, context,
            )
            critiques.append(critique)

        return self._build_consensus(critiques)

    def _get_critique(self, persona, plan_desc, dose_metrics, tool_chain, context) -> CritiqueResult:
        prompt = f"""You are a {persona['name']} reviewing a brachytherapy treatment plan.

Your role: {persona['focus']}

Plan Description:
{plan_desc}
"""
        if dose_metrics:
            prompt += "\nDose Metrics:\n"
            for k, v in dose_metrics.items():
                prompt += f"  {k}: {v}\n"

        if tool_chain:
            prompt += f"\nExecution Chain: {' -> '.join(tool_chain)}\n"

        if context:
            prompt += f"\nAdditional Context:\n{context}\n"

        prompt += """
Provide your review in this format:
VERDICT: (APPROVE / CONDITIONAL_APPROVE / REJECT)
SCORE: (0-10, where 10 is excellent)
CONCERNS: (list specific concerns, one per line, or "None" if no concerns)
RECOMMENDATIONS: (list specific recommendations, one per line, or "None" if no recommendations)
CONFIDENCE: (0.0-1.0, how confident you are in this assessment)"""

        if self.llm_callback:
            try:
                response = self.llm_callback(prompt)
                return self._parse_critique_response(persona["name"], response)
            except Exception:
                pass

        return self._fallback_critique(persona, plan_desc, dose_metrics)

    def _parse_critique_response(self, persona_name: str, response: str) -> CritiqueResult:
        lines = response.strip().split("\n")
        verdict = "CONDITIONAL_APPROVE"
        score = 5.0
        concerns = []
        recommendations = []
        confidence = 0.7

        in_concerns = False
        in_recommendations = False

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("VERDICT:"):
                verdict = line_stripped[len("VERDICT:"):].strip().upper()
                in_concerns = False
                in_recommendations = False
            elif line_stripped.startswith("SCORE:"):
                try:
                    score = float(line_stripped[len("SCORE:"):].strip().split("/")[0])
                except (ValueError, IndexError):
                    score = 5.0
                in_concerns = False
                in_recommendations = False
            elif line_stripped.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line_stripped[len("CONFIDENCE:"):].strip())
                except (ValueError, IndexError):
                    confidence = 0.7
                in_concerns = False
                in_recommendations = False
            elif line_stripped.startswith("CONCERNS:"):
                in_concerns = True
                in_recommendations = False
                val = line_stripped[len("CONCERNS:"):].strip()
                if val and val.lower() != "none":
                    concerns.append(val)
            elif line_stripped.startswith("RECOMMENDATIONS:"):
                in_concerns = False
                in_recommendations = True
                val = line_stripped[len("RECOMMENDATIONS:"):].strip()
                if val and val.lower() != "none":
                    recommendations.append(val)
            elif in_concerns and line_stripped.startswith("-"):
                concerns.append(line_stripped[1:].strip())
            elif in_recommendations and line_stripped.startswith("-"):
                recommendations.append(line_stripped[1:].strip())

        return CritiqueResult(
            persona=persona_name, verdict=verdict, score=score,
            concerns=concerns, recommendations=recommendations, confidence=confidence,
        )

    def _fallback_critique(self, persona, plan_desc, dose_metrics) -> CritiqueResult:
        concerns = []
        recommendations = []

        if dose_metrics:
            d90 = dose_metrics.get("D90", dose_metrics.get("d90", None))
            if d90 is not None:
                try:
                    d90_val = float(str(d90).replace("%", "").replace("Gy", ""))
                    if d90_val < 100:
                        concerns.append(f"D90 ({d90_val}%) is below the recommended 100% threshold")
                        recommendations.append("Consider adding more seeds to improve D90 coverage")
                    elif d90_val > 150:
                        concerns.append(f"D90 ({d90_val}%) is unusually high, may indicate overdosing")
                        recommendations.append("Verify dose calculation and consider reducing seed activity")
                except (ValueError, TypeError):
                    pass

            v100 = dose_metrics.get("V100", dose_metrics.get("v100", None))
            if v100 is not None:
                try:
                    v100_val = float(str(v100).replace("%", ""))
                    if v100_val < 90:
                        concerns.append(f"V100 ({v100_val}%) is below the recommended 90% threshold")
                        recommendations.append("CTV coverage is insufficient; adjust seed placement")
                except (ValueError, TypeError):
                    pass

        verdict = "REJECT" if concerns else "APPROVE"
        score = max(1, 10 - len(concerns) * 2)

        return CritiqueResult(
            persona=persona["name"], verdict=verdict, score=float(score),
            concerns=concerns, recommendations=recommendations, confidence=0.6,
        )

    def _build_consensus(self, critiques: list[CritiqueResult]) -> ConsensusReport:
        total_weight = sum(
            next((p["weight"] for p in self.CRITICAL_PERSONAS if p["name"] == c.persona), 1.0)
            for c in critiques
        )

        weighted_score = sum(
            c.score * next((p["weight"] for p in self.CRITICAL_PERSONAS if p["name"] == c.persona), 1.0)
            for c in critiques
        ) / total_weight

        all_verdicts = [c.verdict for c in critiques]
        unanimous = len(set(all_verdicts)) == 1

        if "REJECT" in all_verdicts:
            overall = "REJECT"
        elif all(v == "APPROVE" for v in all_verdicts):
            overall = "APPROVE"
        else:
            overall = "CONDITIONAL_APPROVE"

        all_concerns = []
        all_recs = []
        for c in critiques:
            all_concerns.extend(c.concerns)
            all_recs.extend(c.recommendations)

        requires_review = overall == "REJECT" or weighted_score < 5.0

        if overall == "APPROVE":
            final_rec = "Plan is clinically acceptable. Proceed with treatment."
        elif overall == "CONDITIONAL_APPROVE":
            final_rec = f"Plan has {len(all_concerns)} concern(s). Review and address before proceeding: " + "; ".join(all_concerns[:3])
        else:
            final_rec = f"Plan is NOT acceptable. {len(all_concerns)} critical issue(s) found: " + "; ".join(all_concerns[:3])

        report = ConsensusReport(
            overall_verdict=overall,
            average_score=round(weighted_score, 1),
            unanimous=unanimous,
            critiques=[{
                "persona": c.persona, "verdict": c.verdict, "score": c.score,
                "concerns": c.concerns, "recommendations": c.recommendations,
            } for c in critiques],
            final_recommendation=final_rec,
            requires_human_review=requires_review,
        )

        self.critique_history.append({
            "timestamp": datetime.now().isoformat(),
            "verdict": overall,
            "score": weighted_score,
            "requires_review": requires_review,
        })
        self._save_history()

        return report

    def format_report_for_display(self, report: ConsensusReport) -> str:
        lines = [
            "## Multi-Agent Clinical Review",
            "",
            f"**Overall Verdict:** {report.overall_verdict}",
            f"**Weighted Score:** {report.average_score}/10",
            f"**Consensus:** {'Unanimous' if report.unanimous else 'Split decision'}",
            f"**Human Review Required:** {'Yes' if report.requires_human_review else 'No'}",
            "",
        ]

        for c in report.critiques:
            lines.append(f"### {c['persona']}")
            lines.append(f"- Verdict: {c['verdict']}")
            lines.append(f"- Score: {c['score']}/10")
            if c["concerns"]:
                lines.append("- Concerns:")
                for concern in c["concerns"]:
                    lines.append(f"  - {concern}")
            if c["recommendations"]:
                lines.append("- Recommendations:")
                for rec in c["recommendations"]:
                    lines.append(f"  - {rec}")
            lines.append("")

        lines.append(f"**Final Recommendation:** {report.final_recommendation}")
        return "\n".join(lines)
