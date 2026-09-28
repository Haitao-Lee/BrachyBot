"""Aggregate "update everything" authorization scope (audit defect F01).

An aggregate command names no object of its own.  It used to authorize every
writable target, so a bare "全部更新" in an empty context — or right after a
case switch — authorized re-running CTV/OAR segmentation and a new planning
pipeline.  "Everything" is a *finite, sourced* set of artifacts the user is
pointing at, and it never silently creates new geometry.
"""

from __future__ import annotations

import pytest

from agent_runtime.request_parse import (
    aggregate_scope_targets,
    mutating_execution_authorized,
    parse_request,
)

DOWNSTREAM_TOOLS = (
    "dose_recompute",
    "dose_evaluation",
    "report_auto_fill",
    "report_generator",
    "surgical_guide",
)
GEOMETRY_TOOLS = (
    "ctv_segmentation",
    "oar_segmentation",
    "biomedparse_segmentation",
    "planning_pipeline",
    "plan_refinement",
    "seed_planning",
    "trajectory_init",
)


# ---------------------------------------------------------------------------
# A bare aggregate reproduces artifacts; it never creates new geometry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "全部更新",
    "那请你全部更新",
    "请全部更新",
    "都更新一下",
    "update everything",
])
def test_bare_aggregate_authorizes_only_the_reproducible_artifact_family(message):
    for tool in DOWNSTREAM_TOOLS:
        assert mutating_execution_authorized(message, tool) is True, tool
    # Re-segmentation and a new planning run create geometry. An aggregate
    # that names no object cannot mean "rebuild the anatomy".
    for tool in GEOMETRY_TOOLS:
        assert mutating_execution_authorized(message, tool) is False, tool


def test_bare_aggregate_after_a_case_switch_still_refuses_to_resegment():
    """No conversation means no resolvable object list — nothing to widen to."""
    conversation = []  # fresh case: nothing has been enumerated yet
    for tool in ("ctv_segmentation", "oar_segmentation", "planning_pipeline"):
        assert mutating_execution_authorized("全部更新", tool, conversation) is False, tool
    assert mutating_execution_authorized("全部更新", "report_auto_fill", conversation) is True


def test_bare_aggregate_never_authorizes_a_destructive_clear():
    from agent_runtime.request_parse import ui_action_explicitly_authorized

    for message in ("全部更新", "那请你全部更新", "update everything"):
        assert mutating_execution_authorized(message, "report_auto_fill") is True
        # Destructive UI targets have their own clause-local gate; the
        # aggregate path must not reach them.
        assert ui_action_explicitly_authorized(message, "report.clear") is False
        assert ui_action_explicitly_authorized(message, "plan.reset") is False


# ---------------------------------------------------------------------------
# The utterance's own object list is a valid source
# ---------------------------------------------------------------------------


def test_targets_named_in_the_utterance_bound_the_aggregate():
    message = "导板和报告全部更新"
    scope = aggregate_scope_targets(message)
    assert scope == frozenset({"surgical_guide", "report"})

    assert mutating_execution_authorized(message, "surgical_guide") is True
    assert mutating_execution_authorized(message, "report_auto_fill") is True
    # Not named -> not covered, even though it is a reproducible artifact.
    assert mutating_execution_authorized(message, "dose_recompute") is False
    assert mutating_execution_authorized(message, "ctv_segmentation") is False


def test_a_named_geometry_target_is_explicitly_requested():
    """Naming CTV yourself is a positive clause for CTV; a bare aggregate is not."""
    message = "CTV和报告全部更新"
    scope = aggregate_scope_targets(message)
    assert "ctv" in scope
    assert "report" in scope

    assert mutating_execution_authorized(message, "ctv_segmentation") is True
    assert mutating_execution_authorized(message, "report_auto_fill") is True
    assert mutating_execution_authorized(message, "oar_segmentation") is False


# ---------------------------------------------------------------------------
# An explicit count reference binds to that many prior artifacts
# ---------------------------------------------------------------------------


def test_count_reference_binds_to_that_many_prior_artifacts():
    conversation = [
        {"role": "user", "content": "现在有哪些过期产物？"},
        {
            "role": "assistant",
            "content": "当前过期产物：剂量、报告、导板。CTV 与 OAR 分割仍然可用。",
        },
        {"role": "user", "content": "把刚才三项全部更新"},
    ]
    scope = aggregate_scope_targets("把刚才三项全部更新", conversation)
    assert scope == frozenset({"dose", "report", "surgical_guide"})
    assert mutating_execution_authorized("把刚才三项全部更新", "dose_recompute", conversation) is True
    assert mutating_execution_authorized("把刚才三项全部更新", "report_auto_fill", conversation) is True
    assert mutating_execution_authorized("把刚才三项全部更新", "surgical_guide", conversation) is True
    assert mutating_execution_authorized("把刚才三项全部更新", "ctv_segmentation", conversation) is False


def test_count_reference_takes_only_the_first_n_of_a_longer_list():
    conversation = [
        {"role": "assistant", "content": "过期产物：剂量、报告、导板、CTV 分割、OAR 分割。"},
        {"role": "user", "content": "把刚才三项全部更新"},
    ]
    scope = aggregate_scope_targets("把刚才三项全部更新", conversation)
    assert scope == frozenset({"dose", "report", "surgical_guide"})
    assert mutating_execution_authorized("把刚才三项全部更新", "ctv_segmentation", conversation) is False


def test_unresolvable_count_reference_clarifies_instead_of_executing():
    """"刚才三项" with nothing prior to point at is not a grant."""
    assert mutating_execution_authorized("把刚才三项全部更新", "report_auto_fill", []) is False
    assert mutating_execution_authorized("把刚才三项全部更新", "dose_recompute", None) is False
    assert mutating_execution_authorized("把刚才三项全部更新", "surgical_guide", []) is False


# ---------------------------------------------------------------------------
# An elliptical follow-up points at whatever the preceding reply enumerated
# ---------------------------------------------------------------------------


def test_elliptical_follow_up_targets_the_prior_enumeration():
    conversation = [
        {"role": "assistant", "content": "剂量与导板已过期，CTV 仍可用。"},
        {"role": "user", "content": "那就全部更新"},
    ]
    scope = aggregate_scope_targets("那就全部更新", conversation)
    assert scope == frozenset({"dose", "surgical_guide"})
    assert mutating_execution_authorized("那就全部更新", "dose_recompute", conversation) is True
    assert mutating_execution_authorized("那就全部更新", "surgical_guide", conversation) is True
    assert mutating_execution_authorized("那就全部更新", "report_auto_fill", conversation) is False
    assert mutating_execution_authorized("那就全部更新", "ctv_segmentation", conversation) is False


# ---------------------------------------------------------------------------
# Exclusions apply to the whole execution plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "全部更新，不含导板",
    "全部更新，不要导板",
    "除了导板都更新",
])
def test_exclusions_apply_to_the_whole_aggregate_scope(message):
    scope = aggregate_scope_targets(message)
    assert "surgical_guide" not in scope
    assert mutating_execution_authorized(message, "surgical_guide") is False
    assert mutating_execution_authorized(message, "report_auto_fill") is True
    assert mutating_execution_authorized(message, "dose_evaluation") is True


def test_exclusion_removes_a_named_target_from_the_scope_too():
    message = "导板和报告全部更新，不含导板"
    scope = aggregate_scope_targets(message)
    assert scope == frozenset({"report"})
    assert mutating_execution_authorized(message, "surgical_guide") is False
    assert mutating_execution_authorized(message, "report_auto_fill") is True


def test_excluding_the_only_named_target_leaves_nothing_to_run():
    message = "导板全部更新，不含导板"
    assert aggregate_scope_targets(message) == frozenset()
    assert mutating_execution_authorized(message, "surgical_guide") is False
    assert mutating_execution_authorized(message, "report_auto_fill") is False


# ---------------------------------------------------------------------------
# Non-commands are still not aggregates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("message", [
    "报告生成好了吗？",
    "不要全部更新",
    "如果全部更新会怎样",
    "“全部更新”是什么意思",
])
def test_questions_negations_and_quotes_are_not_aggregate_grants(message):
    assert parse_request(message).aggregate_command is False
    assert mutating_execution_authorized(message, "report_auto_fill") is False
    assert mutating_execution_authorized(message, "ctv_segmentation") is False
