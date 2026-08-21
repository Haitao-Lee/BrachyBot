"""Per-turn execution authorization for conversational tool calls.

The language model owns semantic intent: mentioning an operation is not the
same as authorizing it.  Deterministic code still owns safety, prerequisites,
ordering, and persistence once an operation has been authorized.

This module intentionally contains no natural-language keyword matching.  A
grant can come from either a high-confidence local fast path or an explicit
tool call selected by the configured LLM.  Workflow recovery code must consume
these grants instead of re-parsing the user's raw message.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Mapping, Set

from agent_runtime.action_plan import ActionPlan


PLANNING_WORKFLOW = "clinical_planning"

# These tools change case data or persistent UI/report state.  Read-only tools
# do not need an execution grant, but remain subject to their normal schemas,
# Session ownership, and backend validators.
MUTATING_TOOLS: FrozenSet[str] = frozenset({
    "ctv_segmentation",
    "oar_segmentation",
    "biomedparse_segmentation",
    "trajectory_init",
    "trajectory_refine",
    "trajectory_planning",
    "seed_planning",
    "seed_planning_rule_based",
    "seed_planning_rl",
    "dose_engine",
    "dose_recompute",
    "dose_evaluation",
    "planning_pipeline",
    "surgical_guide",
    "plan_refinement",
    "report_auto_fill",
    "report_generator",
    "ui_controller",
})

PLANNING_ANCHOR_TOOLS: FrozenSet[str] = frozenset({
    "planning_pipeline",
    "trajectory_init",
    "trajectory_refine",
    "trajectory_planning",
    "seed_planning",
    "seed_planning_rule_based",
    "seed_planning_rl",
    "dose_engine",
    "dose_evaluation",
})

# Missing masks are deterministic prerequisites of an authorized full planning
# workflow.  A guide is deliberately absent: it is generated only when the
# user/LLM explicitly granted ``surgical_guide`` (or the exact legacy planning
# shortcut included that tool), so "plan but do not generate a guide" works.
PLANNING_DERIVED_TOOLS: FrozenSet[str] = frozenset({
    "ctv_segmentation",
    "oar_segmentation",
    "planning_pipeline",
})


@dataclass
class TurnExecutionAuthorization:
    """Execution grants scoped to one isolated chat turn."""

    token: int
    granted_tools: Set[str] = field(default_factory=set)
    granted_workflows: Set[str] = field(default_factory=set)
    events: List[Dict[str, object]] = field(default_factory=list)
    action_plan: ActionPlan = field(default_factory=ActionPlan)

    def set_action_plan(self, plan: ActionPlan, *, source: str = "llm") -> None:
        """Record the ordered action plan for this isolated turn."""
        if not isinstance(plan, ActionPlan):
            return
        plan = plan.with_request_id(f"turn_{self.token}")
        self.action_plan = self.action_plan.merge(plan).with_request_id(
            f"turn_{self.token}"
        )
        self.events.append({
            "source": str(source or "llm"),
            "action_plan": self.action_plan.to_dict(),
        })

    def grant_tools(self, tools: Iterable[str], *, source: str) -> None:
        names = {str(name or "").strip() for name in tools}
        names.discard("")
        if not names:
            return
        self.granted_tools.update(names)
        if names.intersection(PLANNING_ANCHOR_TOOLS):
            self.granted_workflows.add(PLANNING_WORKFLOW)
        self.events.append({
            "source": str(source or "unknown"),
            "tools": sorted(names),
            "workflows": sorted(self.granted_workflows),
        })

    def grant_tool_calls(
        self,
        calls: Iterable[Mapping[str, object]],
        *,
        source: str,
    ) -> None:
        self.grant_tools(
            (str(call.get("tool") or "") for call in calls if isinstance(call, Mapping)),
            source=source,
        )

    def grant_policy(self, policy) -> None:
        self.grant_tools(
            getattr(policy, "execution_grants", frozenset()) or frozenset(),
            source="local_fast_path",
        )
        workflows = {
            str(item or "").strip()
            for item in (getattr(policy, "workflow_grants", frozenset()) or frozenset())
        }
        workflows.discard("")
        if workflows:
            self.granted_workflows.update(workflows)
            self.events.append({
                "source": "local_fast_path",
                "tools": [],
                "workflows": sorted(workflows),
            })

    def workflow_allowed(self, workflow: str) -> bool:
        return str(workflow or "") in self.granted_workflows

    def tool_allowed(self, tool_name: str) -> bool:
        name = str(tool_name or "")
        if name not in MUTATING_TOOLS:
            return True
        if name in self.granted_tools:
            return True
        return (
            self.workflow_allowed(PLANNING_WORKFLOW)
            and name in PLANNING_DERIVED_TOOLS
        )

    def snapshot(self) -> Dict[str, object]:
        return {
            "token": int(self.token),
            "granted_tools": sorted(self.granted_tools),
            "granted_workflows": sorted(self.granted_workflows),
            "action_plan": self.action_plan.to_dict(),
            "events": list(self.events),
        }
