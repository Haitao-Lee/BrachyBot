"""Structured action plans for multi-step conversational requests.

The language model decides what the user means and which operations belong in
the plan.  This module only preserves that order and represents explicit
business dependencies.  It is deliberately independent from natural-language
keyword matching so the same model-generated plan can be used by the stream,
non-stream, retry, and persistence paths.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple


def _json_safe(value: Any) -> Any:
    """Keep trace metadata serializable without copying runtime payloads."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return {"$runtime_type": type(value).__name__}


@dataclass(frozen=True)
class ActionStep:
    """One planned operation and its explicit prerequisites."""

    key: str
    tool: str
    depends_on: Tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    source: str = "llm"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "tool": self.tool,
            "depends_on": list(self.depends_on),
            "params": _json_safe(self.params),
            "source": self.source,
        }


@dataclass(frozen=True)
class ActionPlan:
    """An ordered, serializable plan for the current chat turn."""

    steps: Tuple[ActionStep, ...] = ()
    source: str = "llm"
    request_id: Optional[str] = None

    @classmethod
    def from_tools(
        cls,
        tools: Iterable[str],
        *,
        source: str = "routing",
        dependencies: Optional[Mapping[str, Tuple[str, ...]]] = None,
    ) -> "ActionPlan":
        """Create a plan while preserving first-seen tool order."""
        dependencies = dependencies or {}
        steps = []
        seen = set()
        for tool in tools:
            name = str(tool or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            steps.append(ActionStep(
                key=name,
                tool=name,
                depends_on=tuple(dependencies.get(name, ())),
                source=source,
            ))
        return cls(tuple(steps), source=source)

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: Iterable[Mapping[str, Any]],
        *,
        source: str = "llm",
    ) -> "ActionPlan":
        """Capture the provider's ordered tool calls without reinterpreting them."""
        steps = []
        counts = {}
        for call in tool_calls or ():
            if not isinstance(call, Mapping):
                continue
            tool = str(call.get("tool") or "").strip()
            if not tool:
                continue
            counts[tool] = int(counts.get(tool, 0)) + 1
            key = tool if counts[tool] == 1 else f"{tool}#{counts[tool]}"
            steps.append(ActionStep(
                key=key,
                tool=tool,
                params=dict(call.get("params") or {}),
                source=source,
            ))
        return cls(tuple(steps), source=source)

    @property
    def tool_names(self) -> Tuple[str, ...]:
        return tuple(step.tool for step in self.steps)

    def requires_tool(self, tool: str) -> bool:
        return str(tool or "") in self.tool_names

    def with_request_id(self, request_id: Optional[str]) -> "ActionPlan":
        """Attach a stable turn identifier without changing the plan steps."""
        if self.request_id or not request_id:
            return self
        return ActionPlan(
            steps=self.steps,
            source=self.source,
            request_id=str(request_id),
        )

    def order_tool_calls(self, tool_calls: Iterable[Mapping[str, Any]]) -> Tuple[Mapping[str, Any], ...]:
        """Order calls by this plan while preserving duplicate-call order.

        Retries, dependency injection, and authorization can rebuild the
        provider's list. This keeps the planned business order stable without
        reinterpreting the provider's parameters.
        """
        calls = list(tool_calls or ())
        if not calls or not self.steps:
            return tuple(calls)
        tool_order = {}
        for index, step in enumerate(self.ordered_steps()):
            tool_order.setdefault(step.tool, index)
        fallback = len(tool_order)
        return tuple(
            call
            for _index, call in sorted(
                enumerate(calls),
                key=lambda item: (
                    tool_order.get(str(item[1].get("tool") or ""), fallback),
                    item[0],
                ),
            )
        )

    def merge(self, other: "ActionPlan") -> "ActionPlan":
        """Append steps while retaining order and preserving repeated actions.

        A provider may emit one action per model round.  A plain set-based
        merge would treat the second ``report_generator`` (or any other
        repeated operation) as the first one and silently discard it.  Keep
        every planned action and assign deterministic ``#2``/``#3`` keys;
        dependencies that refer to keys from the incoming plan are remapped at
        the same time.
        """
        if not isinstance(other, ActionPlan) or not other.steps:
            return self
        steps = list(self.steps)
        seen = {step.key for step in steps}
        counts = {}
        for step in steps:
            suffix = step.key.rsplit("#", 1)[1] if "#" in step.key else "1"
            try:
                ordinal = int(suffix)
            except (TypeError, ValueError):
                ordinal = 1
            counts[step.tool] = max(int(counts.get(step.tool, 0)), ordinal)
        key_map = {}
        for step in other.steps:
            original_key = step.key
            # A local dependency guard deliberately creates empty placeholder
            # steps before the model selects concrete parameters. Match one
            # such placeholder exactly once, retaining its dependency key and
            # avoiding a false second execution in the trace.
            placeholder_index = next(
                (
                    index
                    for index, existing in enumerate(steps)
                    if existing.tool == step.tool
                    and existing.source != "llm"
                    and not existing.params
                    and existing.key not in key_map.values()
                ),
                None,
            )
            if placeholder_index is not None:
                existing = steps[placeholder_index]
                key_map[original_key] = existing.key
                steps[placeholder_index] = ActionStep(
                    key=existing.key,
                    tool=step.tool,
                    depends_on=existing.depends_on or step.depends_on,
                    params=step.params,
                    source=step.source,
                )
                continue
            count = int(counts.get(step.tool, 0)) + 1
            candidate = original_key if original_key not in seen else f"{step.tool}#{count}"
            while candidate in seen:
                count += 1
                candidate = f"{step.tool}#{count}"
            counts[step.tool] = count
            key_map[original_key] = candidate
            dependencies = tuple(key_map.get(dep, dep) for dep in step.depends_on)
            steps.append(ActionStep(
                key=candidate,
                tool=step.tool,
                depends_on=dependencies,
                params=step.params,
                source=step.source,
            ))
            seen.add(candidate)
        return ActionPlan(
            steps=tuple(steps),
            source=self.source if self.steps else other.source,
            request_id=self.request_id or other.request_id,
        )

    def ordered_steps(self) -> Tuple[ActionStep, ...]:
        """Return a stable topological order for explicit dependencies."""
        pending = list(self.steps)
        emitted = set()
        emitted_tools = set()
        ordered = []
        while pending:
            progress = False
            for index, step in enumerate(pending):
                if all(
                    dep in emitted
                    or dep in emitted_tools
                    or dep not in self.tool_names
                    for dep in step.depends_on
                ):
                    ordered.append(step)
                    emitted.add(step.key)
                    emitted_tools.add(step.tool)
                    pending.pop(index)
                    progress = True
                    break
            if not progress:
                # A malformed/cyclic provider plan should remain observable and
                # deterministic rather than being silently dropped.
                ordered.extend(pending)
                break
        return tuple(ordered)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "request_id": self.request_id,
            "steps": [step.to_dict() for step in self.ordered_steps()],
        }
