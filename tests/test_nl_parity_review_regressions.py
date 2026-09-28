"""Correct-behaviour regressions for the post-fix parity review (R01-R07).

Every test here started life as a counterexample in
``docs/audits/nl-ui-parity-review-20260928/``.  They assert the behaviour the
contract requires, not the shape of any helper: a green run means the defect is
closed, and a red one names the contract that leaked.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from agent_runtime.action_plan import ActionPlan, ActionStep
from agent_runtime.core import AgentMemory, UI_STATE_DELETE, apply_ui_state_write
from agent_runtime.execution_authorization import TurnExecutionAuthorization
from agent_runtime.request_parse import (
    aggregate_scope_provenance,
    aggregate_scope_targets,
    mutating_execution_authorized,
)
from agent_runtime.ui_operations import resolve_ui_operation_request, values_from_text


@pytest.fixture(autouse=True)
def _isolate_ui_bridge_checkpoint_globals():
    """A pending debounced checkpoint is module-global; do not leak it.

    The checkpoint writer is deliberately debounced, so an earlier test's
    bridge is still sitting in the pending map when the next one starts.  A
    fresh case would then "restore" the previous test's state and the
    assertions would compare against someone else's fixture.
    """
    from web.routes import planning_routes as routes

    pending = routes._UI_BRIDGE_CHECKPOINT_PENDING
    owners = routes._UI_BRIDGE_CHECKPOINT_OWNERS
    timers = routes._UI_BRIDGE_CHECKPOINT_TIMERS
    saved = (dict(pending), dict(owners), dict(timers))
    pending.clear()
    owners.clear()
    timers.clear()
    try:
        yield
    finally:
        pending.clear()
        owners.clear()
        timers.clear()
        pending.update(saved[0])
        owners.update(saved[1])
        timers.update(saved[2])


# ---------------------------------------------------------------------------
# R01 - an aggregate may not borrow a target from a condition, a quotation or
# a question.  The per-tool grant and the aggregate scope must share one
# predicate, or the weaker of the two becomes the real authorization.
# ---------------------------------------------------------------------------

R01_CONDITIONAL = "全部更新；如果以后需要，重新分割CTV。"
R01_QUOTED = "全部更新；他说“重新分割CTV”。"
R01_INTERROGATIVE = "全部更新，CTV分割了吗？"


@pytest.mark.parametrize("message", [R01_CONDITIONAL, R01_QUOTED, R01_INTERROGATIVE])
def test_r01_aggregate_never_authorizes_a_non_executable_clause(message):
    assert mutating_execution_authorized(message, "ctv_segmentation") is False
    assert "ctv" not in aggregate_scope_targets(message)
    assert "oar" not in aggregate_scope_targets(message)


def test_r01_conditional_quoted_and_interrogative_are_all_refused():
    observed = {
        "conditional": mutating_execution_authorized(R01_CONDITIONAL, "ctv_segmentation"),
        "quoted": mutating_execution_authorized(R01_QUOTED, "ctv_segmentation"),
        "interrogative": mutating_execution_authorized(R01_INTERROGATIVE, "ctv_segmentation"),
    }
    assert observed == {"conditional": False, "quoted": False, "interrogative": False}


def test_r01_contested_scope_withholds_even_the_policy_default():
    # Once CTV is on the user's mind without being carved out, "everything"
    # no longer has one reading and the default must not stand in for it.
    provenance, scope = aggregate_scope_provenance(R01_INTERROGATIVE)
    assert provenance == "contested_scope"
    assert scope == frozenset()


def test_r01_an_explicit_carve_out_is_not_a_contested_scope():
    provenance, scope = aggregate_scope_provenance("全部更新，CTV不用动。")
    assert provenance == "policy_default"
    assert scope == frozenset({"dose", "report", "surgical_guide"})
    assert mutating_execution_authorized("全部更新，CTV不用动。", "ctv_segmentation") is False


def test_r01_an_explicit_exclusion_removes_the_target_from_every_source():
    assert aggregate_scope_targets("全部更新，不含导板。") == frozenset({"dose", "report"})


def test_r01_a_named_aggregate_still_authorizes_what_it_names():
    provenance, scope = aggregate_scope_provenance("CTV和OAR全部更新")
    assert provenance == "named"
    assert scope == frozenset({"ctv", "oar"})
    assert mutating_execution_authorized("CTV和OAR全部更新", "ctv_segmentation") is True


def test_r01_policy_default_is_labelled_as_unsourced():
    provenance, scope = aggregate_scope_provenance("全部更新")
    assert provenance == "policy_default"
    assert scope == frozenset({"dose", "report", "surgical_guide"})


# ---------------------------------------------------------------------------
# R03 - merging a graph with a forward reference must rebind the edge to the
# producer that arrived with it, and an unsound plan must not execute.
# ---------------------------------------------------------------------------

def test_r03_forward_dependency_binds_to_the_new_producer():
    base = ActionPlan((ActionStep("A", "dose_recompute", params={"old": True}),))
    incoming = ActionPlan((
        ActionStep("C", "report_auto_fill", depends_on=("A",)),
        ActionStep("A", "dose_recompute", params={"new": True}),
    ))
    merged = base.merge(incoming)

    consumer = next(step for step in merged.steps if step.key == "C")
    producer = next(step for step in merged.steps if step.params.get("new"))
    # The consumer must follow the producer that arrived with it, not the
    # pre-existing step that happened to share its id.
    assert consumer.depends_on == (producer.key,)
    assert producer.params == {"new": True}
    order = [step.key for step in merged.ordered_steps()]
    assert order.index(producer.key) < order.index("C")
    assert merged.validate() == ()


def test_r03_forward_reference_within_one_plan_is_ordered_too():
    plan = ActionPlan.from_tool_calls([
        {"key": "C", "tool": "report_auto_fill", "depends_on": ["A"], "params": {}},
        {"key": "A", "tool": "dose_recompute", "params": {"new": True}},
    ])
    assert [step.key for step in plan.ordered_steps()] == ["A", "C"]
    assert plan.validate() == ()


def test_r03_ambiguous_incoming_ids_are_refused_not_guessed():
    base = ActionPlan((ActionStep("A", "dose_recompute", params={"old": True}),))
    before = base.steps
    ambiguous = ActionPlan((
        ActionStep("X", "first_tool", params={"a": 1}),
        ActionStep("X", "second_tool", depends_on=("X",), params={"b": 2}),
    ))
    assert base.merge(ambiguous).steps == before


def test_r03_validate_reports_a_dangling_dependency():
    plan = ActionPlan((ActionStep("C", "report_auto_fill", depends_on=("ghost",)),))
    assert plan.validate() != ()
    assert not plan.is_valid


def test_r03_validate_reports_a_cycle():
    plan = ActionPlan((
        ActionStep("A", "t1", depends_on=("B",)),
        ActionStep("B", "t2", depends_on=("A",)),
    ))
    assert any("cyclic" in problem for problem in plan.validate())


def test_r03_an_invalid_plan_schedules_nothing_at_all():
    from agent_runtime.llm_runtime import LLMRuntimeMixin

    class _Runtime:
        _order_tool_calls_by_action_plan = LLMRuntimeMixin._order_tool_calls_by_action_plan

        def __init__(self, plan):
            self._plan = plan

        def _current_action_plan(self):
            return self._plan

    sound = ActionPlan.from_tool_calls([
        {"key": "A", "tool": "dose_recompute", "params": {}},
    ])
    calls = [{"tool": "dose_recompute", "params": {}}]
    assert len(_Runtime(sound)._order_tool_calls_by_action_plan(calls)) == 1

    unsound = ActionPlan((ActionStep("C", "report_auto_fill", depends_on=("ghost",)),))
    assert _Runtime(unsound)._order_tool_calls_by_action_plan(calls) == []


def test_r03_a_refused_merge_is_visible_in_the_event_trail():
    authorization = TurnExecutionAuthorization(token=1)
    authorization.set_action_plan(
        ActionPlan((ActionStep("A", "dose_recompute", params={"old": True}),)),
        source="seed",
    )
    authorization.set_action_plan(
        ActionPlan((
            ActionStep("X", "first_tool", params={"a": 1}),
            ActionStep("X", "second_tool", params={"b": 2}),
        )),
        source="ambiguous",
    )
    event = authorization.events[-1]
    assert event["merge_refused"] is True
    assert isinstance(event["plan_problems"], list)


# ---------------------------------------------------------------------------
# R04 - values bind by where they appear in the sentence, and a value stated
# twice is stated twice.
# ---------------------------------------------------------------------------

def test_r04_word_values_keep_the_order_the_user_wrote_them():
    assert values_from_text("CTV和OAR分别设为不透明和半透明", "opacity") == [100, 50]


def test_r04_repeated_word_values_are_all_kept():
    assert values_from_text("CTV和OAR分别设为半透明和半透明", "opacity") == [50, 50]


def test_r04_each_target_receives_its_own_word_value():
    request = resolve_ui_operation_request("CTV和OAR分别设为不透明和半透明", {})
    assert request.get("ambiguous") is False
    assert [
        action["value"] for action in request.get("actions", [])
    ] == ["ctv,100", "oar,50"]


def test_r04_repeated_word_values_bind_per_target():
    request = resolve_ui_operation_request("CTV和OAR分别设为半透明和半透明", {})
    assert request.get("ambiguous") is False
    assert [
        action["value"] for action in request.get("actions", [])
    ] == ["ctv,50", "oar,50"]


def test_r04_a_property_name_is_not_a_value():
    # 「不透明度」 is "opacity", not a request for 100%.
    assert values_from_text("把不透明度设为30%", "opacity") == [30]


def test_r04_mixed_number_and_word_values_keep_sentence_order():
    assert values_from_text("CTV设为30%，OAR设为半透明", "opacity") == [30, 50]
    assert values_from_text("CTV设为不透明，OAR设为30%", "opacity") == [100, 30]


def test_r04_colour_values_keep_sentence_order():
    assert values_from_text("CTV和OAR分别设为红色和蓝色", "color") == ["红色", "蓝色"]


def test_r04_a_length_mismatch_is_still_a_request_to_clarify():
    request = resolve_ui_operation_request("CTV和OAR分别设为不透明", {})
    assert request.get("ambiguous") is True
    assert request.get("actions") in (None, [])


# ---------------------------------------------------------------------------
# R05 - the version fence lives in the control plane, a snapshot of an older
# plan is stale, and a tombstone means the same thing everywhere.
# ---------------------------------------------------------------------------

def _isolated_ui_state_app(memory):
    """Mount /api/ui/state on an in-memory case with no durable store.

    The durable-restore path is deliberately inert: these tests are about the
    control-plane receiver, not about snapshot hydration.
    """
    from contextlib import ExitStack, contextmanager

    from web.routes import planning_routes as routes
    from web.workspace_store import WorkspaceError

    bucket = {"state": {}, "events": [], "training": {}}
    cached = [SimpleNamespace(memory=memory)] if memory is not None else [None]

    class _NoTimer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def cancel(self):
            pass

        def is_alive(self):
            return False

    def _no_durable_store(*args, **kwargs):
        raise WorkspaceError("isolated test store")

    store = SimpleNamespace(
        get_session=lambda *args: SimpleNamespace(id="review-case"),
        load_snapshot=_no_durable_store,
        load_ui_bridge=_no_durable_store,
        save_ui_bridge=_no_durable_store,
    )

    @contextmanager
    def _mounted():
        with ExitStack() as stack:
            stack.enter_context(patch.object(routes, "require_api_key", lambda f: f))
            stack.enter_context(patch.object(routes, "rate_limit", lambda f: f))
            stack.enter_context(patch.object(routes, "current_user", lambda store: {"id": "review-user"}))
            stack.enter_context(patch.object(routes, "_ui_bucket", lambda sid: bucket))
            stack.enter_context(patch.object(routes.threading, "Timer", _NoTimer))
            app = Flask("nl-parity-r05")
            app.extensions["brachybot_workspace_store"] = store
            routes.register_planning_routes(
                app, lambda *a: None,
                get_cached_agent=lambda sid: cached[0],
            )
            yield app.test_client(), bucket

    return _mounted()


def _post_ui_state(client, **payload):
    return client.post(
        "/api/ui/state",
        headers={"X-BrachyBot-Session": "review-case"},
        json={"browser_instance": "review-browser", **payload},
    )


def test_r05_cold_session_refuses_an_older_sequence():
    with _isolated_ui_state_app(None) as (client, bucket):
        first = _post_ui_state(client, state={"value": "new"}, state_seq=9, mode="replace")
        assert first.status_code == 200, first.get_json()

        # No cached agent at all: the fence must still hold.
        stale = _post_ui_state(client, state={"value": "old"}, state_seq=4, mode="replace")
        assert stale.status_code == 409
        assert stale.get_json()["accepted_revision"]["reason"] == "stale_state_seq"
        assert bucket["state"] == {"value": "new"}


def test_r05_a_snapshot_of_an_older_plan_is_refused():
    memory = AgentMemory("r05-plan-fence")
    memory.set_ui_state(
        {"plan": "new"}, mode="replace",
        state_seq=1, browser_instance="browser", plan_revision=2,
    )
    rejected = memory.set_ui_state(
        {"plan": "old"}, mode="replace",
        state_seq=2, browser_instance="browser", plan_revision=1,
    )
    assert rejected["accepted"] is False
    assert rejected["reason"] == "stale_plan_revision"
    assert memory.get_ui_state() == {"plan": "new"}


def test_r05_a_newer_plan_revision_is_accepted():
    memory = AgentMemory("r05-plan-fence-up")
    memory.set_ui_state(
        {"plan": "old"}, mode="replace",
        state_seq=1, browser_instance="browser", plan_revision=1,
    )
    accepted = memory.set_ui_state(
        {"plan": "new"}, mode="replace",
        state_seq=2, browser_instance="browser", plan_revision=2,
    )
    assert accepted["accepted"] is True
    assert memory.get_ui_state() == {"plan": "new"}


def test_r05_tombstone_removes_the_key_from_memory_and_bucket():
    memory = AgentMemory("r05-tombstone")
    with _isolated_ui_state_app(memory) as (client, bucket):
        _post_ui_state(
            client,
            state={"keep": True, "deleted": "old"},
            state_seq=10,
            mode="patch",
        )
        response = _post_ui_state(
            client,
            state={},
            state_seq=11,
            mode="patch",
            tombstones=["deleted"],
        )

        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert "deleted" not in body["state_keys"]
        assert "deleted" not in bucket["state"]
        assert "deleted" not in memory.get_ui_state()
        assert bucket["state"] == memory.get_ui_state() == {"keep": True}


def test_r05_a_delete_marker_matches_an_explicit_tombstone():
    assert apply_ui_state_write(
        {"keep": True, "deleted": "old"},
        {"deleted": UI_STATE_DELETE},
        mode="patch",
    ) == {"keep": True}
    assert apply_ui_state_write(
        {"keep": True, "deleted": "old"},
        {},
        mode="patch",
        tombstones=["deleted"],
    ) == {"keep": True}


def test_r05_replace_drops_keys_the_snapshot_omits():
    assert apply_ui_state_write(
        {"gone": 1, "keep": 2},
        {"keep": 3},
        mode="replace",
    ) == {"keep": 3}


# ---------------------------------------------------------------------------
# R02 / R06 / R07 live in the browser bundle and are asserted in
# tests/ui-action-terminal-state.test.cjs.  This guard keeps the two suites
# from drifting apart silently.
# ---------------------------------------------------------------------------

def test_r02_r06_r07_are_covered_by_the_node_contract():
    from pathlib import Path

    node_suite = Path(__file__).with_name("ui-action-terminal-state.test.cjs")
    assert node_suite.exists()
    text = node_suite.read_text(encoding="utf-8")
    for marker in ("R02", "R06", "R07", "_uiActionResultState", "_resolveOverlayOpacityPercent"):
        assert marker in text, f"{node_suite.name} must cover {marker}"
