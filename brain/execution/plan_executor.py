from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import json


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    step_index: int
    tool_name: str
    arguments: Dict[str, Any]
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0.0


@dataclass
class PlanExecutionResult:
    plan_id: str
    status: ExecutionStatus
    steps: List[StepResult] = field(default_factory=list)
    final_result: Any = None
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status.value,
            "steps": [
                {
                    "step_index": s.step_index,
                    "tool_name": s.tool_name,
                    "arguments": s.arguments,
                    "status": s.status.value,
                    "result": str(s.result)[:500] if s.result else None,
                    "error": s.error,
                    "execution_time": s.execution_time
                }
                for s in self.steps
            ],
            "final_result": str(self.final_result)[:500] if self.final_result else None,
            "summary": self.summary
        }


class PlanExecutor:
    def __init__(self, tool_registry):
        self.tool_registry = tool_registry
        self._hooks: Dict[str, List[Callable]] = {
            "before_step": [],
            "after_step": [],
            "on_error": [],
            "on_complete": []
        }

    def add_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def execute_plan(self, plan: Dict[str, Any],
                     context: Optional[Dict[str, Any]] = None) -> PlanExecutionResult:
        plan_id = plan.get("plan_id", "unknown")
        steps = plan.get("steps", [])

        result = PlanExecutionResult(
            plan_id=plan_id,
            status=ExecutionStatus.RUNNING
        )

        context = context or {}

        for idx, step in enumerate(steps):
            tool_name = step.get("tool")
            args = step.get("arguments", {})

            step_result = StepResult(
                step_index=idx,
                tool_name=tool_name,
                arguments=args,
                status=ExecutionStatus.PENDING
            )

            for hook in self._hooks["before_step"]:
                hook(idx, tool_name, args, context)

            try:
                tool_spec = self.tool_registry.get(tool_name)
                if tool_spec is None:
                    raise ValueError(f"Tool '{tool_name}' not found in registry")

                args_resolved = self._resolve_args(args, context)
                step_result.status = ExecutionStatus.RUNNING
                step_result.result = tool_spec.execute_fn(**args_resolved)
                step_result.status = ExecutionStatus.SUCCESS

                context[f"step_{idx}_result"] = step_result.result

            except Exception as e:
                step_result.status = ExecutionStatus.FAILED
                step_result.error = str(e)
                result.steps.append(step_result)
                result.status = ExecutionStatus.FAILED
                result.summary = f"Failed at step {idx}: {tool_name} - {str(e)}"

                for hook in self._hooks["on_error"]:
                    hook(idx, tool_name, args, e, context)

                return result

            result.steps.append(step_result)

            for hook in self._hooks["after_step"]:
                hook(idx, tool_name, step_result.result, context)

        result.status = ExecutionStatus.SUCCESS
        result.final_result = context.get("final_result")
        result.summary = f"Completed {len(steps)} steps successfully"

        for hook in self._hooks["on_complete"]:
            hook(result, context)

        return result

    def _resolve_args(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        resolved = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                var_name = value[1:]
                resolved[key] = context.get(var_name)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_args(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_args({k: v}, context)[k] if isinstance(v, str) and v.startswith("$") else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved


def validate_plan(plan: Dict[str, Any]) -> List[str]:
    errors = []
    if "steps" not in plan:
        errors.append("Plan must contain 'steps' key")
        return errors
    if not isinstance(plan["steps"], list):
        errors.append("'steps' must be a list")
        return errors
    for idx, step in enumerate(plan["steps"]):
        if "tool" not in step:
            errors.append(f"Step {idx} missing 'tool' key")
        if "arguments" in step and not isinstance(step["arguments"], dict):
            errors.append(f"Step {idx} 'arguments' must be a dict")
    return errors
