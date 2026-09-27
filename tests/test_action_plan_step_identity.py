"""Action-plan step identity contracts (audit defect F03).

Dependencies in an :class:`~agent_runtime.action_plan.ActionPlan` reference
*step ids* (``ActionStep.key``), never tool names.  Mixing the two namespaces
lets a consumer run before its producer whenever the producer is the second
occurrence of a repeated tool (``dose_recompute#2``), and silently drops the
``key``/``depends_on`` a provider actually emitted.
"""

import pytest

from agent_runtime.action_plan import ActionPlan, ActionStep


# ---------------------------------------------------------------------------
# from_tool_calls: provider-supplied identity must survive
# ---------------------------------------------------------------------------


def test_from_tool_calls_preserves_provider_keys_and_dependencies():
    plan = ActionPlan.from_tool_calls([
        {"key": "A", "tool": "ui_controller", "params": {"actions": []}},
        {"key": "B", "tool": "ui_screenshot", "depends_on": ["A"], "params": {}},
    ])

    assert [step.key for step in plan.steps] == ["A", "B"]
    assert plan.steps[1].depends_on == ("A",)
    assert [step.key for step in plan.ordered_steps()] == ["A", "B"]


def test_from_tool_calls_accepts_camel_case_and_string_dependencies():
    plan = ActionPlan.from_tool_calls([
        {"key": "produce", "tool": "dose_recompute", "params": {}},
        {
            "key": "consume",
            "tool": "report_generator",
            "dependsOn": "produce",
            "params": {},
        },
    ])

    assert plan.steps[1].depends_on == ("produce",)
    assert [step.key for step in plan.ordered_steps()] == ["produce", "consume"]


def test_from_tool_calls_never_aliases_a_duplicate_provider_key():
    plan = ActionPlan.from_tool_calls([
        {"key": "same", "tool": "report_generator", "params": {"version": 1}},
        {"key": "same", "tool": "report_generator", "params": {"version": 2}},
    ])

    keys = [step.key for step in plan.steps]
    assert len(set(keys)) == 2
    assert keys[0] == "same"
    assert plan.steps[0].params["version"] == 1
    assert plan.steps[1].params["version"] == 2


def test_from_tool_calls_keeps_deterministic_keys_when_the_provider_omits_them():
    plan = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
        {"tool": "report_generator", "params": {"version": 2}},
        {"tool": "ui_content", "params": {"target": "report"}},
    ])

    assert [step.key for step in plan.steps] == [
        "report_generator",
        "report_generator#2",
        "ui_content",
    ]


# ---------------------------------------------------------------------------
# ordered_steps: step identity, not tool name
# ---------------------------------------------------------------------------


def test_ordered_steps_runs_the_named_producer_before_its_consumer():
    """A consumer of ``dose_recompute#2`` must not run before that exact step."""
    plan = ActionPlan(steps=(
        ActionStep("consumer", "report_generator", ("dose_recompute#2",)),
        ActionStep("dose_recompute#2", "dose_recompute"),
    ))

    assert [step.key for step in plan.ordered_steps()] == [
        "dose_recompute#2",
        "consumer",
    ]


def test_ordered_steps_does_not_treat_an_unknown_dependency_as_satisfied():
    """A dependency that names no step is a defect, not an implicit pass."""
    plan = ActionPlan(steps=(
        ActionStep("consumer", "report_generator", ("missing#9",)),
        ActionStep("producer", "dose_recompute"),
    ))

    # The plan stays observable and deterministic, but validation reports the
    # problem so the caller can refuse to execute rather than run blind.
    assert plan.validate() == (
        "unknown dependency 'missing#9' referenced by consumer",
    )


def test_ordered_steps_waits_for_the_second_occurrence_of_a_repeated_tool():
    plan = ActionPlan.from_tool_calls([
        {"key": "dose-1", "tool": "dose_recompute", "params": {"round": 1}},
        {"key": "dose-2", "tool": "dose_recompute", "depends_on": ["dose-1"],
         "params": {"round": 2}},
        {"key": "report", "tool": "report_generator", "depends_on": ["dose-2"],
         "params": {}},
    ])

    assert [step.key for step in plan.ordered_steps()] == [
        "dose-1",
        "dose-2",
        "report",
    ]


# ---------------------------------------------------------------------------
# validate: structural defects surface before execution
# ---------------------------------------------------------------------------


def test_validate_accepts_a_well_formed_plan():
    plan = ActionPlan.from_tool_calls([
        {"key": "produce", "tool": "dose_recompute", "params": {}},
        {"key": "consume", "tool": "report_generator", "depends_on": ["produce"]},
    ])

    assert plan.validate() == ()
    assert plan.is_valid is True


def test_validate_reports_duplicate_step_ids():
    plan = ActionPlan(steps=(
        ActionStep("dup", "report_generator"),
        ActionStep("dup", "report_generator"),
    ))

    assert "duplicate step id: dup" in plan.validate()
    assert plan.is_valid is False


def test_validate_reports_a_self_dependency():
    plan = ActionPlan(steps=(ActionStep("solo", "report_generator", ("solo",)),))

    assert "step solo depends on itself" in plan.validate()


def test_validate_reports_a_cycle():
    plan = ActionPlan(steps=(
        ActionStep("a", "x", ("b",)),
        ActionStep("b", "y", ("a",)),
    ))

    assert "cyclic dependency in action plan" in plan.validate()
    assert plan.is_valid is False


def test_validate_reports_an_empty_step_id():
    plan = ActionPlan(steps=(ActionStep("", "report_generator"),))

    assert "step with empty id" in plan.validate()


# ---------------------------------------------------------------------------
# order_tool_calls: repeated tools keep their planned slots
# ---------------------------------------------------------------------------


def test_order_tool_calls_matches_calls_to_steps_by_explicit_key():
    plan = ActionPlan.from_tool_calls([
        {"key": "produce", "tool": "dose_recompute", "params": {"round": 1}},
        {"key": "consume", "tool": "report_generator", "depends_on": ["produce"]},
    ])
    calls = [
        {"key": "consume", "tool": "report_generator", "params": {}},
        {"key": "produce", "tool": "dose_recompute", "params": {"round": 1}},
    ]

    assert [call["key"] for call in plan.order_tool_calls(calls)] == [
        "produce",
        "consume",
    ]


def test_order_tool_calls_keeps_duplicate_tool_slots_aligned_with_the_plan():
    """The second ``report_generator`` must not be merged into the first slot."""
    plan = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
        {"tool": "ui_content", "params": {"target": "report"}},
        {"tool": "report_generator", "params": {"version": 2}},
    ])
    calls = [
        {"tool": "ui_content", "params": {"target": "report"}},
        {"tool": "report_generator", "params": {"version": 2}},
        {"tool": "report_generator", "params": {"version": 1}},
    ]

    ordered = plan.order_tool_calls(calls)
    # Planned order is report_generator (slot 0) -> ui_content -> report_generator
    # (slot 2).  Calls without explicit keys occupy the same-tool slots in the
    # order the provider emitted them, so the plan's cross-tool structure holds
    # and a second dose/report step can never collapse into the first.
    assert [call["params"] for call in ordered] == [
        {"version": 2},
        {"target": "report"},
        {"version": 1},
    ]


def test_order_tool_calls_places_unmatched_tools_after_the_planned_steps():
    plan = ActionPlan.from_tool_calls([
        {"tool": "planning_pipeline", "params": {}},
    ])
    calls = [
        {"tool": "web_search", "params": {"query": "x"}},
        {"tool": "planning_pipeline", "params": {}},
    ]

    assert [call["tool"] for call in plan.order_tool_calls(calls)] == [
        "planning_pipeline",
        "web_search",
    ]


# ---------------------------------------------------------------------------
# merge: dependency remapping keeps step identity
# ---------------------------------------------------------------------------


def test_merge_remaps_dependencies_that_point_at_renamed_incoming_steps():
    base = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
    ])
    incoming = ActionPlan.from_tool_calls([
        {"key": "prod", "tool": "dose_recompute", "params": {}},
        {"key": "cons", "tool": "report_generator", "depends_on": ["prod"],
         "params": {"version": 2}},
    ])
    merged = base.merge(incoming)

    keys = [step.key for step in merged.steps]
    # Provider step ids are preserved when they are free, so the dependency
    # keeps pointing at the exact producer instead of a renamed alias.
    assert keys == ["report_generator", "prod", "cons"]
    consumer = next(step for step in merged.steps if step.key == "cons")
    assert consumer.depends_on == ("prod",)
    assert [step.key for step in merged.ordered_steps()] == [
        "report_generator",
        "prod",
        "cons",
    ]
    assert merged.validate() == ()


def test_merge_keeps_params_of_repeated_actions_from_later_rounds():
    first = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 1}},
    ])
    second = ActionPlan.from_tool_calls([
        {"tool": "report_generator", "params": {"version": 2}},
    ])
    merged = first.merge(second)

    assert [step.params["version"] for step in merged.steps] == [1, 2]
