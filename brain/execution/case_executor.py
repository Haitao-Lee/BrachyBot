"""
Case Executor for BrachyAgent
============================
Executes LLM-generated plans step-by-step.
Inspired by MedAgent-Pro's Case_level.py execution pattern.
"""

import os
import json
import time
import logging
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass

from ..core.tool_registry import ToolRegistry, get_tool_registry
from ..core.base import PlanStep
from .types import ExecutionStatus

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    step_id: int
    tool_name: str
    tool_id: int
    action: str
    action_type: str
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0
    output_path: str = ""
    output_type: str = "intermediate result"


@dataclass
class CaseExecutionResult:
    plan_id: str
    status: ExecutionStatus
    steps: List[StepResult] = None
    final_result: Any = None
    summary: str = ""
    total_time: float = 0.0

    def __post_init__(self):
        if self.steps is None:
            self.steps = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status.value,
            "total_time": self.total_time,
            "summary": self.summary,
            "steps": [
                {
                    "step_id": s.step_id,
                    "tool_name": s.tool_name,
                    "tool_id": s.tool_id,
                    "action": s.action,
                    "action_type": s.action_type,
                    "status": s.status.value,
                    "result": str(s.result)[:500] if s.result else None,
                    "error": s.error,
                    "execution_time": s.execution_time,
                    "output_path": s.output_path,
                    "output_type": s.output_type,
                }
                for s in self.steps
            ],
            "final_result": str(self.final_result)[:500] if self.final_result else None,
        }


class CaseExecutor:
    """
    Executes plans following MedAgent-Pro's Case_level.py pattern.

    Key differences from PlanExecutor:
    - Uses integer tool IDs (not names)
    - Resolves step dependencies via input_type references
    - Handles both quantitative (tool calls) and qualitative (VLM) steps
    - Output files stored in per-step directories
    """

    def __init__(self, tool_registry: ToolRegistry = None):
        self.tool_registry = tool_registry or get_tool_registry()
        self._hooks: Dict[str, List[Callable]] = {
            "before_step": [],
            "after_step": [],
            "on_error": [],
            "on_complete": [],
            "on_qualitative": [],
        }

    def add_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def resolve_execution_order(self, steps: List[Dict]) -> List[Any]:
        """
        Resolve step execution order based on dependencies.
        Returns phases - each phase is a list of steps that can run in parallel.
        """
        ids = []
        for step in steps:
            try:
                step_id = int(step["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Every plan step must have an integer id") from exc
            if step_id <= 0:
                raise ValueError(f"Step id {step_id} is invalid; id 0 is reserved for case input")
            ids.append(step_id)
        if len(ids) != len(set(ids)):
            raise ValueError("Plan contains duplicate step ids")

        known_ids = set(ids)
        for step in steps:
            step_id = int(step["id"])
            dependencies = self._step_input_refs(step, include_zero=False)
            missing = sorted(set(dependencies) - known_ids)
            if missing:
                raise ValueError(f"Step {step_id} references missing dependencies: {missing}")
            if step_id in dependencies:
                raise ValueError(f"Step {step_id} depends on itself")

        executed = set()
        phases = []

        while len(executed) < len(steps):
            current_phase = []
            for step in steps:
                step_id = int(step["id"])
                if step_id in executed:
                    continue
                deps = self._step_input_refs(step, include_zero=False)
                if all(d in executed for d in deps):
                    current_phase.append(step)

            if not current_phase:
                unresolved = sorted(known_ids - executed)
                raise ValueError(f"Plan dependency cycle detected among steps: {unresolved}")

            phases.append(current_phase)
            for step in current_phase:
                executed.add(int(step["id"]))

        return phases

    @staticmethod
    def _step_input_refs(step: Dict, include_zero: bool = True) -> List[int]:
        """Normalize MedAgent-Pro input_type and generic dependencies fields."""
        refs: List[int] = []
        for key in ("input_type", "dependencies"):
            raw_refs = step.get(key, [])
            if raw_refs is None:
                continue
            if isinstance(raw_refs, int):
                raw_refs = [raw_refs]
            elif not isinstance(raw_refs, (list, tuple, set)):
                continue
            for ref in raw_refs:
                try:
                    ref_int = int(ref)
                except (TypeError, ValueError):
                    continue
                if ref_int == 0 and not include_zero:
                    continue
                if ref_int not in refs:
                    refs.append(ref_int)
        return refs

    def execute(self, plan: List[Dict], case_input: Any = None,
                output_dir: str = "./output", plan_id: str = "plan") -> CaseExecutionResult:
        """
        Execute a plan following MedAgent-Pro's pattern.

        Args:
            plan: List of step dicts with keys: id, tool, action, action_type,
                  input_type, output_type, output_path
            case_input: Primary input (image path, data, etc.)
            output_dir: Directory to save outputs
            plan_id: Identifier for this plan

        Returns:
            CaseExecutionResult with step results and final diagnosis
        """
        os.makedirs(output_dir, exist_ok=True)

        result = CaseExecutionResult(
            plan_id=plan_id,
            status=ExecutionStatus.RUNNING
        )

        start_time = time.time()
        step_outputs: Dict[int, Any] = {0: case_input}
        try:
            phases = self.resolve_execution_order(plan)
        except ValueError as exc:
            result.status = ExecutionStatus.FAILED
            result.summary = f"Invalid plan: {exc}"
            result.total_time = time.time() - start_time
            return result

        for phase in phases:
            for step_dict in phase:
                step_id = int(step_dict["id"])
                tool_ids = step_dict.get("tool", [])
                if isinstance(tool_ids, int):
                    tool_ids = [tool_ids]
                tool_id = tool_ids[0] if tool_ids else None

                action = step_dict.get("action", "")
                action_type = step_dict.get("action_type", "quantitative")
                input_type = self._step_input_refs(step_dict, include_zero=True)
                output_type = step_dict.get("output_type", "intermediate result")
                output_path = step_dict.get("output_path", "result.json")

                step_result = StepResult(
                    step_id=step_id,
                    tool_name="",
                    tool_id=tool_id,
                    action=action,
                    action_type=action_type,
                    status=ExecutionStatus.PENDING,
                    output_path=output_path,
                    output_type=output_type,
                )

                for hook in self._hooks["before_step"]:
                    hook(step_id, tool_id, action, input_type)

                step_dir = os.path.join(output_dir, f"step_{step_id}")
                os.makedirs(step_dir, exist_ok=True)

                try:
                    if action_type == "quantitative":
                        step_result = self._execute_quantitative(
                            step_id, tool_id, action, input_type,
                            step_outputs, step_dir, output_path, step_result
                        )
                    elif action_type == "qualitative":
                        step_result = self._execute_qualitative(
                            step_id, tool_id, action, input_type,
                            step_outputs, step_dir, output_path, step_result
                        )
                    else:
                        step_result.status = ExecutionStatus.SKIPPED
                        step_result.error = f"Unknown action_type: {action_type}"

                except Exception as e:
                    step_result.status = ExecutionStatus.FAILED
                    step_result.error = str(e)
                    result.steps.append(step_result)
                    result.status = ExecutionStatus.FAILED
                    result.summary = f"Failed at step {step_id}: {action} - {str(e)}"

                    for hook in self._hooks["on_error"]:
                        hook(step_id, tool_id, action, e)

                    result.total_time = time.time() - start_time
                    return result

                result.steps.append(step_result)

                if step_result.status == ExecutionStatus.SUCCESS:
                    step_outputs[step_id] = {
                        "path": os.path.join(step_dir, output_path),
                        "data": step_result.result
                    }
                else:
                    result.status = ExecutionStatus.FAILED
                    result.summary = (
                        f"Failed at step {step_id}: {action} - "
                        f"{step_result.error or step_result.status.value}"
                    )
                    result.total_time = time.time() - start_time
                    for hook in self._hooks["on_error"]:
                        hook(step_id, tool_id, action, RuntimeError(result.summary))
                    return result

                for hook in self._hooks["after_step"]:
                    hook(step_id, tool_id, step_result)

        result.status = ExecutionStatus.SUCCESS
        result.summary = f"Completed {len(result.steps)} steps successfully"
        result.total_time = time.time() - start_time

        final_indicators = [
            s for s in result.steps
            if s.status == ExecutionStatus.SUCCESS and
            s.output_type == "final indicator"
        ]
        if final_indicators:
            result.final_result = {
                "indicators": [
                    {"step_id": s.step_id, "action": s.action, "result": s.result}
                    for s in final_indicators
                ]
            }

        for hook in self._hooks["on_complete"]:
            hook(result)

        return result

    def _execute_quantitative(self, step_id: int, tool_id: int, action: str,
                             input_type: List[int], step_outputs: Dict,
                             step_dir: str, output_path: str,
                             step_result: StepResult) -> StepResult:
        """Execute a quantitative (tool call) step."""
        step_result.status = ExecutionStatus.RUNNING

        tool_spec = self.tool_registry.get_by_id(tool_id)
        if tool_spec is None:
            step_result.status = ExecutionStatus.FAILED
            step_result.error = f"Tool ID {tool_id} not found"
            return step_result

        step_result.tool_name = tool_spec.name

        resolved_inputs = []
        for dep in input_type:
            if dep == 0:
                resolved_inputs.append(step_outputs.get(0))
            else:
                dep_output = step_outputs.get(dep)
                if dep_output:
                    resolved_inputs.append(dep_output.get("path") or dep_output.get("data"))

        full_output_path = self._safe_output_path(step_dir, output_path)
        safe_output_name = os.path.relpath(full_output_path, step_dir)

        exec_start = time.time()
        if resolved_inputs:
            result = tool_spec.execute_fn(
                inputs=resolved_inputs,
                save_dir=step_dir,
                save_name=safe_output_name,
                action=action
            )
        else:
            result = tool_spec.execute_fn(
                save_dir=step_dir,
                save_name=safe_output_name,
                action=action
            )
        step_result.execution_time = time.time() - exec_start

        if hasattr(result, "success") and not result.success:
            step_result.status = ExecutionStatus.FAILED
            step_result.error = getattr(result, "error", None) or getattr(result, "message", "Tool failed")
            step_result.result = result
            return step_result

        if os.path.exists(full_output_path):
            try:
                with open(full_output_path, "r", encoding="utf-8") as f:
                    result = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not load step output JSON %s; keeping tool return value: %s", full_output_path, exc)

        step_result.result = result
        step_result.status = ExecutionStatus.SUCCESS

        return step_result

    @staticmethod
    def _safe_output_path(step_dir: str, output_path: str) -> str:
        """Resolve a plan-provided output path without allowing traversal."""
        base = os.path.realpath(step_dir)
        candidate = os.path.realpath(os.path.join(base, output_path or "result.json"))
        if os.path.commonpath((base, candidate)) != base:
            raise ValueError(f"Output path escapes step directory: {output_path}")
        return candidate

    def _execute_qualitative(self, step_id: int, tool_id: int, action: str,
                             input_type: List[int], step_outputs: Dict,
                             step_dir: str, output_path: str,
                             step_result: StepResult) -> StepResult:
        """Execute a qualitative (VLM judgment) step."""
        step_result.status = ExecutionStatus.RUNNING

        tool_spec = self.tool_registry.get_by_id(tool_id)
        if tool_spec:
            step_result.tool_name = tool_spec.name

        images = []
        texts = []
        for dep in input_type:
            if dep == 0:
                continue
            dep_output = step_outputs.get(dep)
            if dep_output:
                path = dep_output.get("path", "")
                if path and self._is_image_path(path):
                    images.append(path)
                texts.append(str(dep_output.get("data", "")))

        for hook in self._hooks.get("on_qualitative", []):
            hook(step_id, action, images, texts)

        step_result.result = {
            "judgment": f"VLM analysis of step {step_id}: {action}",
            "images": images,
            "texts": texts
        }
        step_result.status = ExecutionStatus.SUCCESS
        step_result.output_type = "final indicator"

        return step_result

    def _is_image_path(self, path: str) -> bool:
        img_exts = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")
        return any(path.lower().endswith(ext) for ext in img_exts)


def execute_plan(plan: List[Dict], case_input: Any = None,
                 output_dir: str = "./output", plan_id: str = "plan") -> CaseExecutionResult:
    """Convenience function to execute a plan."""
    executor = CaseExecutor()
    return executor.execute(plan, case_input, output_dir, plan_id)
