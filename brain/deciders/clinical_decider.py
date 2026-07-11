"""
Clinical Decider
===============
Clinical decision module with weighted indicator scoring.
Inspired by MedAgent-Pro's Pro_Decider.py.
"""

import os
import json
from typing import Dict, List, Any

from ..core.base import BaseLLM, BaseDecider, LLMResponse


class ClinicalDecider(BaseDecider):
    """
    Makes clinical decisions using weighted indicator scoring.

    Given multiple clinical indicators with judgments, allocates
    weights and computes a final weighted score vs threshold.
    """

    def __init__(self, llm: BaseLLM):
        super().__init__(llm)

    def decide(
        self,
        task: str,
        context: Dict[str, Any],
        indicators: List[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make a clinical decision.

        Args:
            task: Clinical task/goal description
            context: Additional context (disease, patient info, etc.)
            indicators: List of {"indicator_name": str, "value": Any, "judgment": str}

        Returns:
            Dict with weights, threshold, score, and diagnosis
        """
        if not indicators:
            indicators = context.get("indicators", [])

        disease_goal = context.get("disease", "brachytherapy planning")
        input_desc = context.get("input", "CT scan")

        system_msg = (
            "You are a careful clinical decision assistant for brachytherapy planning. "
            "Given a task, indicator judgments, propose weights that sum to 1 and a threshold in [0,1]. "
            "Return ONLY a JSON object with: 'weights' (list of {'indicator_name','weight'}), "
            "'threshold' (float in [0,1]), and optional 'notes'."
        )

        lines = []
        for it in indicators:
            name = str(it.get("indicator_name", "")).strip()
            val = it.get("value") or it.get("judgment", "")
            if isinstance(val, (dict, list)):
                val_text = json.dumps(val, ensure_ascii=False)
            else:
                val_text = str(val)
            lines.append(f"- {name}: {val_text}")
        ind_text = "Indicators & judgments:\n" + "\n".join(lines)

        user_text = (
            f"Task & context:\n"
            f"- Input: {input_desc}\n"
            f"- Goal: {disease_goal}\n\n"
            f"{ind_text}\n\n"
            "Constraints:\n"
            "- Sum of weights must be 1.\n"
            "- Threshold must be in [0,1].\n"
            "- Return ONLY the JSON object."
        )

        response = self.llm.chat(prompt=user_text, system=system_msg)

        if not response.content:
            return self._default_result(indicators)

        try:
            obj = self._safe_json_parse(response.content)
        except Exception:
            return self._default_result(indicators)

        w_map = self._weights_from_model(obj, indicators)
        try:
            threshold = max(0.0, min(1.0, float(obj.get("threshold", 0.5))))
        except (ValueError, TypeError):
            threshold = 0.5

        score, contributions = self._compute_score(indicators, w_map)
        diagnosis = "Acceptable" if score >= threshold else "Unacceptable"

        return {
            "weights": w_map,
            "threshold": threshold,
            "score": score,
            "diagnosis": diagnosis,
            "contributions": contributions,
            "model_notes": obj.get("notes", "") if isinstance(obj, dict) else "",
        }

    def decide_from_metrics(
        self,
        metrics: Dict[str, float],
        thresholds: Dict[str, float] = None,
        task: str = "brachytherapy plan evaluation",
    ) -> Dict[str, Any]:
        """
        Quick clinical decision from dose metrics.

        Args:
            metrics: Dict of metric_name -> value (e.g., V100, D90)
            thresholds: Dict of metric_name -> min_acceptable_value
            task: Task description

        Returns:
            Weighted decision result
        """
        if not thresholds:
            return {
                "weights": {},
                "threshold": None,
                "score": None,
                "diagnosis": "UNVERIFIED",
                "contributions": {},
                "model_notes": (
                    "No source-backed thresholds were supplied. Load the "
                    "site-specific criteria from clinical_kb or plan_config."
                ),
            }

        indicators = []
        for name, value in metrics.items():
            norm_value = self._normalize_metric(name, value, thresholds.get(name, 0))
            indicators.append({
                "indicator_name": name,
                "value": value,
                "judgment": norm_value,
            })

        return self.decide(
            task=task,
            context={"disease": "brachytherapy", "indicators": indicators},
            indicators=indicators,
        )

    def _normalize_metric(self, name: str, value: float, threshold: float) -> float:
        """Normalize metric to 0-1 scale based on threshold."""
        if value >= threshold:
            return 1.0
        elif value >= threshold * 0.8:
            return 0.7
        elif value >= threshold * 0.5:
            return 0.4
        return 0.0

    def _weights_from_model(self, obj: Dict, indicators: List[Dict]) -> Dict[str, float]:
        """Map model-proposed weights to indicators."""
        model_ws = obj.get("weights", []) if isinstance(obj, dict) else []
        w_map = {}
        for w in model_ws:
            name = str(w.get("indicator_name", "")).strip()
            try:
                val = float(w.get("weight", 0))
                w_map[name] = max(0.0, min(1.0, val))
            except (ValueError, TypeError):
                continue

        names = [str(it.get("indicator_name", "")).strip() for it in indicators]
        total = sum(w_map.values())

        if total > 0:
            for k in w_map:
                w_map[k] = w_map[k] / total
        else:
            w_map = {n: 1.0 / max(1, len(names)) for n in names}

        return w_map

    def _compute_score(self, indicators: List[Dict], w_map: Dict[str, float]) -> tuple:
        """Compute weighted score from indicators."""
        contributions = []
        score = 0.0

        for it in indicators:
            name = str(it.get("indicator_name", "")).strip()
            val = self._norm_value(it.get("value") or it.get("judgment", 0))
            w = float(w_map.get(name, 0.0))
            contrib = val * w
            contributions.append({
                "indicator_name": name,
                "value": val,
                "weight": w,
                "weighted": contrib,
            })
            score += contrib

        return score, contributions

    def _norm_value(self, value) -> float:
        """Normalize a value to 0-1."""
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        if isinstance(value, str):
            s = value.strip().lower()
            if s in {"yes", "true", "pass", "acceptable", "good"}:
                return 1.0
            if s in {"no", "false", "fail", "unacceptable", "poor"}:
                return 0.0
            try:
                return max(0.0, min(1.0, float(s)))
            except ValueError:
                return 0.5
        return 0.5

    def _safe_json_parse(self, text: str) -> Dict:
        """Safely parse JSON from LLM response."""
        t = (text or "").strip()
        if t.startswith("```"):
            parts = sorted(t.split("```"), key=len, reverse=True)
            for p in parts:
                p = p.strip()
                if p.startswith("{") and '"weights"' in p:
                    try:
                        return json.loads(p)
                    except json.JSONDecodeError:
                        pass
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            s, e = t.find("{"), t.rfind("}")
            if s != -1 and e != -1 and e > s:
                try:
                    return json.loads(t[s:e+1])
                except json.JSONDecodeError:
                    pass
        return {}

    def _default_result(self, indicators: List[Dict]) -> Dict:
        """Default result when parsing fails."""
        names = [str(it.get("indicator_name", "")) for it in indicators]
        w_map = {n: 1.0 / max(1, len(names)) for n in names}
        score, contributions = self._compute_score(indicators, w_map)
        return {
            "weights": w_map,
            "threshold": 0.5,
            "score": score,
            "diagnosis": "Acceptable" if score >= 0.5 else "Unacceptable",
            "contributions": contributions,
            "model_notes": "default (parsing failed)",
        }
