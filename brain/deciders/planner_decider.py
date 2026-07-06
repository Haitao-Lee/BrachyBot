"""
Planner Decider
==============
Generates structured tool-chain execution plans from natural language tasks.
Inspired by MedAgent-Pro's Planner.py.
"""

import os
import json
from typing import Dict, List, Any, Optional

from ..core.base import BaseLLM, BaseDecider, LLMResponse, PlanStep
from ..core.tool_registry import ToolRegistry


class PlannerDecider(BaseDecider):
    """
    Generates execution plans using LLM.

    Given a task and available tools, produces a JSON plan with:
    - Step IDs (1-based, consecutive)
    - Tool IDs to call for each step
    - Action type (quantitative/qualitative)
    - Input dependencies (step IDs, 0 for raw input)
    - Output type (intermediate result/final indicator)
    - Output path
    """

    def __init__(self, llm: BaseLLM, tool_registry: ToolRegistry):
        super().__init__(llm)
        self.tool_registry = tool_registry

    def decide(self, task: str, context: Dict[str, Any] = None, **kwargs) -> Dict[str, Any]:
        """Generate an execution plan for the task."""
        rag_text = context.get("rag_text", "") if context else ""
        return {"plan": self.plan(task, rag_text)}

    def plan(self, task: str, rag_text: str = "", **kwargs) -> List[Dict]:
        """Generate execution plan."""
        toolset = self.tool_registry.get_toolset_for_prompt()

        system_msg = (
            "You are a brachytherapy planning assistant. "
            "Given a task and available tools, generate a precise execution plan as a JSON array. "
            "Each step must contain: id (int, 1-based), tool (list of tool IDs), action (string), "
            "action_type ('quantitative' or 'qualitative'), input_type (list of step IDs, 0=raw input), "
            "output_type ('intermediate result' or 'final indicator'), output_path (string). "
            "Rules: "
            "(1) ids must be consecutive starting at 1; "
            "(2) tool IDs must reference valid IDs from the toolset; "
            "(3) input dependencies must be produced by prior steps; "
            "(4) quantitative steps compute metrics, qualitative steps make judgments; "
            "(5) output_path for non-image results should be 'result.json'; "
            "(6) OBSERVE/ASSESS/JUDGE steps must be qualitative; "
            "(7) SEGMENT/COMPUTE/MEASURE steps must be quantitative; "
            "(8) Output EXACT JSON array only, no explanation."
        )

        user_text = self._build_user_text(task, rag_text, toolset)

        response = self.llm.chat(
            prompt=user_text,
            system=system_msg,
            tools=self.tool_registry.get_openai_tools(),
        )

        if not response.content:
            return []

        try:
            plan_data = self._safe_json_parse(response.content)
            steps = [PlanStep.from_dict(s) for s in plan_data]
            validated = self._validate_and_clean(steps)
            return [s.to_dict() for s in validated]
        except Exception as e:
            return self._fallback_plan(task)

    def _build_user_text(self, task: str, rag_text: str, toolset: List[Dict]) -> str:
        """Build user message content."""
        lines = []
        for idx, t in enumerate(toolset, 1):
            lines.append(
                f"{idx}. [id:{t['id']}] [{t['type']}] {t['function']} "
                f"(input: {t['input']} -> output: {t['output']})"
            )
        toolset_text = "\n".join(lines)

        rag_section = f"\nRAG Knowledge:\n{rag_text}\n" if rag_text else ""

        return (
            f"Task: {task}\n"
            f"{rag_section}\n"
            f"Available Tools:\n{toolset_text}\n\n"
            "Return ONLY the JSON array."
        )

    def _safe_json_parse(self, text: str) -> List[Dict]:
        """Safely parse JSON from LLM response."""
        t = text.strip()
        if t.startswith("```"):
            parts = sorted(t.split("```"), key=len, reverse=True)
            for p in parts:
                p = p.strip()
                if p.startswith("[") or p.startswith("{"):
                    try:
                        data = json.loads(p)
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        pass
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            start = t.find("[")
            end = t.rfind("]")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(t[start:end+1])
                except json.JSONDecodeError:
                    pass
            start = t.find("{")
            end = t.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(t[start:end+1])
                except json.JSONDecodeError:
                    pass
        return []

    def _validate_and_clean(self, steps: List[PlanStep]) -> List[PlanStep]:
        """Validate and clean plan steps."""
        valid_ids = set(self.tool_registry.list_tool_ids())
        cleaned = []
        seen_ids = set()

        for step in steps:
            if step.id in seen_ids:
                continue
            seen_ids.add(step.id)

            tool_ids = [tid for tid in step.tool if tid in valid_ids]
            if not tool_ids:
                continue

            step.tool = tool_ids
            cleaned.append(step)

        cleaned.sort(key=lambda s: s.id)

        for i, step in enumerate(cleaned):
            step.id = i + 1

        return cleaned

    def _fallback_plan(self, task: str) -> List[Dict]:
        """Fallback plan when LLM planning fails."""
        task_lower = task.lower()
        if any(k in task_lower for k in ["分割", "segment", "tumor", "ctv"]):
            return [
                {"id": 1, "tool": [1], "action": "Segment CTV tumor", "action_type": "quantitative",
                 "input_type": [0], "output_type": "intermediate result", "output_path": "ctv_mask.json"},
            ]
        elif any(k in task_lower for k in ["计划", "plan", "seed"]):
            return [
                {"id": 1, "tool": [1], "action": "Segment tumor", "action_type": "quantitative",
                 "input_type": [0], "output_type": "intermediate result", "output_path": "ctv.json"},
                {"id": 2, "tool": [2], "action": "Plan seed placement", "action_type": "quantitative",
                 "input_type": [1], "output_type": "final indicator", "output_path": "plan.json"},
            ]
        return [
            {"id": 1, "tool": [1], "action": "Process task", "action_type": "quantitative",
             "input_type": [0], "output_type": "final indicator", "output_path": "result.json"},
        ]
