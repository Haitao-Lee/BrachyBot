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
import json
from typing import Dict, FrozenSet, Iterable, List, Mapping, Set

from agent_runtime.action_plan import ActionPlan
from agent_runtime.execution_scope import ExecutionScope


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
    "dicom_rt_exporter",
    "case_memory",
    "clinical_kb",
    "code_executor", "code_writer", "write_tool", "create_tool", "tool_creator",
    "self_evolve", "evolve", "shell_executor", "env_manager",
})

PLANNING_ANCHOR_TOOLS: FrozenSet[str] = frozenset({"planning_pipeline"})

# Mixed-effect tools must be classified by the validated operation, not merely
# by the tool name. Unknown/missing explicit operations remain fail-closed.
READ_ONLY_ACTIONS = {
    "case_memory": frozenset({"retrieve", "search", "list", "statistics", "recommend"}),
    "surgical_guide": frozenset({"status", "analyze"}),
    "clinical_kb": frozenset({"standards", "constraints", "tolerance", "protocol", "benchmark", "search", "guidelines", "source_search", "review_queue"}),
}


def _same_json_value(actual, expected):
    """Compare finite, typed JSON values; True is not the integer 1."""
    try:
        return (json.dumps(actual, sort_keys=True, allow_nan=False)
                == json.dumps(expected, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError):
        return False


def tool_call_is_mutating(tool_name: str, params: object = None) -> bool:
    """Classify an invocation without granting it any execution permission.

    A name-only legacy case-memory query describes the read capability. Actual
    callers must pass parameters (including {} for a missing action); that
    distinction preserves the old introspection API without allowing a save
    or a malformed call to acquire the read exemption.
    """
    name = str(tool_name or "")
    if name not in MUTATING_TOOLS:
        return False
    if name == "ui_controller" and isinstance(params, Mapping):
        from agent_runtime.export_request import is_export_dialog_action
        actions = params.get("actions")
        if isinstance(actions, list) and actions and all(is_export_dialog_action(action) for action in actions):
            # A chooser cannot write until a separate browser gesture. This
            # exemption never includes arbitrary UI or mixed mutation batches.
            return False
    if name == "case_memory" and params is None:
        return False
    if name in READ_ONLY_ACTIONS and isinstance(params, Mapping):
        action = params.get("action")
        if isinstance(action, str) and action.strip().lower() in READ_ONLY_ACTIONS[name]:
            return False
    return True

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
    execution_receipts: List[Dict[str, object]] = field(default_factory=list)
    _name_grants: Set[str] = field(default_factory=set, repr=False)
    _call_grants: Dict[str, List[dict]] = field(default_factory=dict, repr=False)
    effect_scope: ExecutionScope = field(default_factory=ExecutionScope)

    def bind_request(self, message) -> bool:
        """Freeze a denial-only ceiling before any routing/provider grants."""
        incoming = ExecutionScope.from_request(message)
        if self.effect_scope.request_sha256:
            return self.effect_scope.request_sha256 == incoming.request_sha256
        self.effect_scope = incoming
        return True

    def effect_allowed(self, tool_name, params=None) -> bool:
        return (not tool_call_is_mutating(tool_name, params)
                or self.effect_scope.allows(tool_name, params))

    def set_action_plan(self, plan: ActionPlan, *, source: str = "llm") -> bool:
        """Record the ordered action plan for this isolated turn.

        A merge that cannot be remapped unambiguously leaves the previous plan
        in place; say so in the event trail rather than letting a dropped step
        look like a silent success (audit defect R03).  Structural problems on
        the resulting plan are recorded too: the execution entry consults
        :meth:`ActionPlan.validate` and will refuse to run them.
        """
        if not isinstance(plan, ActionPlan):
            return False
        plan = plan.with_request_id(f"turn_{self.token}")
        merged = self.action_plan.merge(plan).with_request_id(f"turn_{self.token}")
        incoming_problems = plan.validate()
        problems = incoming_problems or merged.validate()
        refused = bool(problems) or (merged.steps == self.action_plan.steps and bool(plan.steps))
        if not refused:
            self.action_plan = merged
        self.events.append({
            "source": str(source or "llm"),
            "action_plan": self.action_plan.to_dict(),
            "execution_receipts": list(self.execution_receipts),
            "merge_refused": refused,
            "plan_problems": list(problems),
        })
        return not refused

    def grant_tools(self, tools: Iterable[str], *, source: str) -> None:
        self._record_grants(tools, source=source, name_grant=True)

    def _record_grants(self, tools, *, source, name_grant):
        names = {str(name or "").strip() for name in tools}
        names.discard("")
        if name_grant:
            names = {name for name in names if self.effect_allowed(name)}
        if not names:
            return
        self.granted_tools.update(names)
        if name_grant:
            self._name_grants.update(names)
        # A local needle/seed edit or dose evaluation is not permission to
        # launch the full planning pipeline. Only the full-pipeline operation
        # can grant its missing CTV/OAR prerequisites.
        if ('planning_pipeline' in names and (name_grant or any(
                params.get('step', 'full') == 'full'
                for params in self._call_grants.get('planning_pipeline', ())))):
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
        admitted = []
        for call in calls:
            if (not isinstance(call, Mapping) or call.get('_argument_error')
                    or not tool_call_is_mutating(call.get('tool', ''), call.get('params') or {})):
                continue
            params = call.get('params') or {}
            if not isinstance(params, Mapping):
                continue
            try:
                frozen = json.loads(json.dumps(dict(params), allow_nan=False))
            except (TypeError, ValueError):
                continue
            name = str(call.get('tool') or '')
            if not self.effect_allowed(name, frozen):
                self.events.append({'source': str(source), 'scope_denied_tool': name})
                continue
            self._call_grants.setdefault(name, []).append(frozen)
            admitted.append(name)
        self._record_grants(admitted, source=source, name_grant=False)

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
        plan = getattr(policy, "action_plan", None)
        full_plan_granted = (
            "planning_pipeline" in (getattr(policy, "execution_grants", ()) or ())
            or (plan is not None and plan.requires_tool("planning_pipeline"))
        )
        if PLANNING_WORKFLOW in workflows and not full_plan_granted:
            workflows.discard(PLANNING_WORKFLOW)
        if not self.effect_allowed('planning_pipeline', {'step': 'full'}):
            workflows.discard(PLANNING_WORKFLOW)
        if workflows:
            self.granted_workflows.update(workflows)
            self.events.append({
                "source": "local_fast_path",
                "tools": [],
                "workflows": sorted(workflows),
            })

    def workflow_allowed(self, workflow: str) -> bool:
        return str(workflow or "") in self.granted_workflows

    def tool_allowed(self, tool_name: str, params: object = None) -> bool:
        name = str(tool_name or "")
        if not tool_call_is_mutating(name, params):
            return True
        if not self.effect_allowed(name, params):
            return False
        if name in self.granted_tools:
            if params is None or name in self._name_grants:
                return True  # legacy introspection or proved whole-command grant
            if isinstance(params, Mapping):
                # Normalization can enrich a call with server-owned inputs,
                # but cannot replace its explicit operation/target/value.
                protected = {'action', 'actions', 'planning_id', 'node_id', 'target', 'step'}
                for expected in self._call_grants.get(name, ()):
                    defaults = {'step': 'full'} if name == 'planning_pipeline' else {}
                    if (all(key in params and _same_json_value(params[key], value)
                            for key, value in expected.items())
                            and not any(key in params and key not in expected
                                        and params[key] != defaults.get(key) for key in protected)):
                        return True
            # An existing scoped grant must not fall through to the broader
            # workflow grant and thereby accept another plan or operation.
            return False
        # Only an accepted full planning workflow may derive prerequisites.
        # Granting CTV/OAR alone must never authorize planning_pipeline.
        return (
            self.workflow_allowed(PLANNING_WORKFLOW)
            and name in PLANNING_DERIVED_TOOLS - {'planning_pipeline'}
        )

    def snapshot(self) -> Dict[str, object]:
        return {
            "token": int(self.token),
            "granted_tools": sorted(self.granted_tools),
            "granted_workflows": sorted(self.granted_workflows),
            "action_plan": self.action_plan.to_dict(),
            "effect_scope": self.effect_scope.to_dict(),
            "events": list(self.events),
        }
