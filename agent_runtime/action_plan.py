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

    @staticmethod
    def _dependency_keys(call: Mapping[str, Any]) -> Tuple[str, ...]:
        """Read the step ids a provider call depends on.

        Both ``depends_on`` and ``dependsOn`` are accepted so a gateway that
        camel-cases tool arguments cannot silently drop a dependency.  A bare
        string is treated as a single dependency rather than a sequence of
        characters.
        """
        raw = call.get("depends_on")
        if raw is None:
            raw = call.get("dependsOn")
        if raw is None:
            return ()
        if isinstance(raw, str):
            raw = (raw,)
        try:
            items = list(raw)
        except TypeError:
            return ()
        return tuple(str(dep).strip() for dep in items if str(dep).strip())

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: Iterable[Mapping[str, Any]],
        *,
        source: str = "llm",
    ) -> "ActionPlan":
        """Capture the provider's ordered tool calls without reinterpreting them.

        A provider may attach its own ``key`` and ``depends_on`` to a call.
        Those are the plan's step identity: dropping them is what previously
        let a consumer run before its producer and turned a real dependency
        graph into a flat name-ordered list.  A missing key still falls back
        to the deterministic ``tool`` / ``tool#N`` naming so callers that only
        name a tool keep working, and a duplicated provider key is never
        allowed to alias two different steps.
        """
        steps = []
        counts = {}
        seen = set()
        for call in tool_calls or ():
            if not isinstance(call, Mapping):
                continue
            tool = str(call.get("tool") or "").strip()
            if not tool:
                continue
            counts[tool] = int(counts.get(tool, 0)) + 1
            fallback = tool if counts[tool] == 1 else f"{tool}#{counts[tool]}"
            raw_key = call.get("key")
            key = str(raw_key).strip() if raw_key is not None else ""
            if not key or key in seen:
                key = fallback
                while key in seen:
                    counts[tool] = int(counts.get(tool, 0)) + 1
                    key = f"{tool}#{counts[tool]}"
            seen.add(key)
            steps.append(ActionStep(
                key=key,
                tool=tool,
                depends_on=cls._dependency_keys(call),
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
        provider's list.  Each call is matched onto one planned step: an
        explicit ``key`` wins, otherwise the n-th call of a tool occupies the
        n-th planned slot of that tool.  Grouping by tool *name* alone is what
        previously collapsed a second ``dose_recompute``/``report_generator``
        into the first occurrence's position and reordered a real dependency
        chain.  Unmatched tools keep their relative order after the planned
        steps.  The provider's parameters are never reinterpreted.
        """
        calls = list(tool_calls or ())
        if not calls or not self.steps:
            return tuple(calls)
        ordered_steps = self.ordered_steps()
        rank = {step.key: index for index, step in enumerate(ordered_steps)}
        steps_by_tool: dict = {}
        for step in ordered_steps:
            steps_by_tool.setdefault(step.tool, []).append(step.key)
        tool_occurrence: dict = {}
        matched = []
        for position, call in enumerate(calls):
            tool = str(call.get("tool") or "")
            raw_key = call.get("key")
            key = str(raw_key).strip() if raw_key is not None else ""
            if key not in rank:
                nth = int(tool_occurrence.get(tool, 0)) + 1
                tool_occurrence[tool] = nth
                slots = steps_by_tool.get(tool) or ()
                key = slots[nth - 1] if len(slots) >= nth else ""
            if key in rank:
                matched.append((rank[key], position, call))
            else:
                matched.append((len(ordered_steps) + position, position, call))
        matched.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in matched)

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

    def validate(self) -> Tuple[str, ...]:
        """Return every structural defect in the plan (empty when it is sound).

        Missing dependencies, duplicate step ids and cycles are execution
        hazards, not cosmetic issues: a plan that names them must be refused
        before any tool runs instead of being silently reordered.  Callers
        that only need a deterministic listing can still use
        :meth:`ordered_steps`, which never drops a step.
        """
        problems = []
        seen = set()
        for step in self.steps:
            if not step.key:
                problems.append("step with empty id")
            elif step.key in seen:
                problems.append(f"duplicate step id: {step.key}")
            seen.add(step.key)
        for step in self.steps:
            for dep in step.depends_on:
                if dep == step.key:
                    problems.append(f"step {step.key} depends on itself")
                elif dep not in seen:
                    problems.append(
                        f"unknown dependency {dep!r} referenced by {step.key}"
                    )
        if not problems and self._has_cycle():
            problems.append("cyclic dependency in action plan")
        return tuple(problems)

    def _has_cycle(self) -> bool:
        remaining = {step.key for step in self.steps}
        blockers = {
            step.key: {dep for dep in step.depends_on if dep in remaining}
            for step in self.steps
        }
        changed = True
        while changed and remaining:
            changed = False
            for key in list(remaining):
                if not (blockers[key] & remaining):
                    remaining.discard(key)
                    changed = True
        return bool(remaining)

    @property
    def is_valid(self) -> bool:
        return not self.validate()

    def ordered_steps(self) -> Tuple[ActionStep, ...]:
        """Return a stable topological order for explicit dependencies.

        Dependencies are resolved against *step ids* only.  Treating a
        dependency as satisfied merely because some step with the same tool
        name has already run is what allowed ``report_generator`` to execute
        before ``dose_recompute#2``.  A malformed or cyclic plan keeps its
        original order so it stays observable and deterministic;
        :meth:`validate` reports why it cannot be executed as scheduled.
        """
        pending = list(self.steps)
        emitted = set()
        ordered = []
        while pending:
            progress = False
            for index, step in enumerate(pending):
                if all(dep in emitted for dep in step.depends_on):
                    ordered.append(step)
                    emitted.add(step.key)
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
