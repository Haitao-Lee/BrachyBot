"""Structured whole-request parsing contract.

Every fix ships a positive and a negative case, plus the four semantic classes
(negation, condition, question, quotation) that must never authorize a write.
The regression sentences from the report-generation incident are included
verbatim.
"""
import pytest

from agent_runtime import request_parse as rp
from agent_runtime.request_parse import (
    ParsedRequest,
    parse_request,
    is_interrogative,
    is_negated,
    is_conditional,
    is_quoted,
    is_affirmative_command,
    is_unconditional_command,
    is_affirmative_acknowledgement,
    canonical_report_mutation,
    canonical_guide_generation,
    mutating_execution_authorized,
    ui_action_explicitly_authorized,
    resolve_reference_target,
)
from agent_runtime.turn_policy import (
    classify_local_turn,
    is_report_generation_request,
    is_surgical_guide_generation_request,
    unambiguous_report_generation_request,
    unambiguous_guide_generation_request,
)
from agent_runtime.response_tools import ResponseToolMixin


# ---------------------------------------------------------------------------
# Required regression sentences
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("message", "target", "action"), [
    ("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a", "report", "generate"),
    ("\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "report", "generate"),
    ("\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u548c\u62a5\u544a", "surgical_guide", "generate"),
    ("\u5982\u679c\u8fd8\u6ca1\u6709\u5bfc\u677f\u5c31\u751f\u6210\u4e00\u4e2a", "surgical_guide", "generate"),
    ("\u751f\u6210 surgery report", "report", "generate"),
])
def test_required_sentences_parse_into_the_structured_record(message, target, action):
    parsed = parse_request(message)
    assert isinstance(parsed, ParsedRequest)
    assert parsed.target == target
    assert parsed.action == action
    assert parsed.goals  # every sentence names at least one goal


def test_reference_only_turn_resolves_to_nearest_prior_target():
    conversation = [{"role": "user", "content": "\u751f\u6210\u624b\u672f\u5bfc\u677f"}]
    assert parse_request("\u5c31\u5b83\u5427").references
    assert resolve_reference_target("\u5c31\u5b83\u5427", conversation) == "surgical_guide"
    conversation = [{"role": "user", "content": "\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a"}]
    assert resolve_reference_target("\u7167\u8fd9\u4e2a\u518d\u6765\u4e00\u6b21", conversation) == "report"
    # An explicit new target overrides the prior one.
    assert resolve_reference_target("\u5c31\u5b83\u5427\uff0c\u770b\u770b\u5f53\u524d ctv", conversation) == "ctv"


# ---------------------------------------------------------------------------
# Four semantic classes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "Is the report ready?",
    "\u5206\u5272\u5b8c\u6210\u4e86\u6ca1", "why did planning fail?",
])
def test_interrogatives_are_questions_not_commands(message):
    assert is_interrogative(message)
    assert not is_affirmative_command(message)
    parsed = parse_request(message)
    assert parsed.interrogative
    assert not parsed.affirmative_command


@pytest.mark.parametrize("message", [
    "\u4e0d\u8981\u751f\u6210\u62a5\u544a", "do not regenerate the report",
    "\u5220\u9664\u62a5\u544a",  # destructive but negated below
])
def test_negation_is_never_an_affirmative_write(message):
    if message == "\u5220\u9664\u62a5\u544a":
        # This one is affirmative; guard against a bad parametrization.
        assert is_affirmative_command(message)
        return
    assert is_negated(message)
    assert not is_unconditional_command(message)


@pytest.mark.parametrize("message", [
    "分别截图告知", "识别当前肿瘤", "查看类别和结构", "看看别的分割对象",
])
def test_ordinary_words_containing_bie_are_not_negation(message):
    assert not is_negated(message)


@pytest.mark.parametrize("message", [
    "别生成报告", "请别重新执行规划", "你别删除当前规划",
])
def test_imperative_bie_still_blocks_writes(message):
    assert is_negated(message)
    assert not is_unconditional_command(message)


def test_quoted_text_does_not_authorize_an_action():
    assert is_quoted("\u201c\u91cd\u65b0\u751f\u6210\u62a5\u544a\u201d")
    assert not is_unconditional_command("\u201c\u91cd\u65b0\u751f\u6210\u62a5\u544a\u201d")


def test_conditional_request_is_not_an_unconditional_write():
    message = "\u5982\u679c\u8fd8\u6ca1\u6709\u5bfc\u677f\u5c31\u751f\u6210\u4e00\u4e2a"
    parsed = parse_request(message)
    assert parsed.conditional
    assert not parsed.unconditional_command
    assert not mutating_execution_authorized(message, "surgical_guide")
    # The conditional marker must not silently negate an explicit guide command.
    assert parse_request("\u751f\u6210\u624b\u672f\u5bfc\u677f").unconditional_command


# ---------------------------------------------------------------------------
# P0-1 / P1-5 report object protection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a",
    "\u751f\u6210\u5206\u6790\u62a5\u544a",
    "\u91cd\u65b0\u751f\u6210\u5242\u91cf\u62a5\u544a",
    "regenerate the current report",
])
def test_positive_report_commands_are_unambiguous(message):
    assert is_report_generation_request(message)
    assert unambiguous_report_generation_request(message)


@pytest.mark.parametrize("message", [
    "\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f",
    "\u4e0d\u8981\u751f\u6210\u62a5\u544a",
    "\u5982\u679c\u62a5\u544a\u7a7a\u4e86\u5c31\u91cd\u65b0\u751f\u6210",
    "\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u548c\u62a5\u544a",
    "\u91cd\u65b0\u751f\u6210\u7684\u62a5\u544a\u89e3\u8bfb\u4e00\u4e0b",
])
def test_report_questions_negations_conditions_and_compounds_are_not_unambiguous(message):
    assert not unambiguous_report_generation_request(message)


def test_analysis_qualifier_stays_a_report_generation_fast_path():
    policy = classify_local_turn("\u751f\u6210\u5206\u6790\u62a5\u544a")
    assert policy.intent == "report_generation"
    assert policy.direct_execution
    assert policy.execution_grants == {"ui_controller"}


# ---------------------------------------------------------------------------
# P0-2 bidirectional object guard
# ---------------------------------------------------------------------------

def _normalizer(message, calls):
    class Memory:
        conversation = [{"role": "user", "content": message}]

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    return normalizer._normalize_tool_params(calls)


def test_question_about_report_is_not_rewritten_to_report_autofill():
    calls = _normalizer(
        "\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f",
        [{
            "id": "shot", "tool": "ui_screenshot",
            "params": {"question": "?", "views": ["viewer-3d"]},
        }],
    )
    assert calls and calls[0]["tool"] == "ui_screenshot"


def test_explicit_report_command_converts_read_calls_to_autofill():
    calls = _normalizer(
        "\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a",
        [{"id": "guide", "tool": "surgical_guide", "params": {"action": "generate"}}],
    )
    assert calls == [{
        "id": "guide",
        "tool": "ui_controller",
        "params": {"actions": [{"target": "report.autofill", "command": "run"}]},
    }]


def test_explicit_guide_command_is_not_downgraded_to_report():
    assert is_surgical_guide_generation_request("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f")
    assert unambiguous_guide_generation_request("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f")
    calls = _normalizer(
        "\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f",
        [{"id": "rep", "tool": "report_auto_fill", "params": {}}],
    )
    assert calls and calls[0]["tool"] == "surgical_guide"
    assert calls[0]["params"] == {"action": "generate"}


def test_compound_guide_and_report_is_not_collapsed():
    assert not unambiguous_guide_generation_request("\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u548c\u62a5\u544a")
    assert not unambiguous_report_generation_request("\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u548c\u62a5\u544a")


# ---------------------------------------------------------------------------
# P0-3 provider-boundary second check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("message", "tool_name", "expected"), [
    ("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a", "report_auto_fill", True),
    ("\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "report_auto_fill", False),
    ("\u4e0d\u8981\u751f\u6210\u62a5\u544a", "report_auto_fill", False),
    ("\u5982\u679c\u8fd8\u6ca1\u6709\u5bfc\u677f\u5c31\u751f\u6210\u4e00\u4e2a", "surgical_guide", False),
    ("\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f", "surgical_guide", True),
    ("\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212", "planning_pipeline", True),
])
def test_mutating_execution_requires_an_affirmative_matching_command(
    message, tool_name, expected
):
    assert mutating_execution_authorized(message, tool_name) is expected


def test_non_mutating_tools_are_unaffected_by_the_second_check():
    assert mutating_execution_authorized("\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "case_memory")


@pytest.mark.parametrize(("message", "tool_name", "expected"), [
    ("\u201c\u91cd\u65b0\u751f\u6210\u62a5\u544a\u201d", "report_auto_fill", False),
    ("\u65e5\u5fd7\u4e2d\u5199\u7740\u201c\u91cd\u65b0\u751f\u6210\u62a5\u544a\u201d", "report_auto_fill", False),
    ("\u4e0d\u8981\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff1b\u8bf7\u751f\u6210\u624b\u672f\u5bfc\u677f", "report_auto_fill", False),
    ("\u4e0d\u8981\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff1b\u8bf7\u751f\u6210\u624b\u672f\u5bfc\u677f", "surgical_guide", True),
    ("\u5982\u679c\u62a5\u544a\u6ca1\u6709\u751f\u6210\uff0c\u5c31\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff1b\u8bf7\u751f\u6210\u624b\u672f\u5bfc\u677f", "report_auto_fill", False),
    ("\u5982\u679c\u62a5\u544a\u6ca1\u6709\u751f\u6210\uff0c\u5c31\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff1b\u8bf7\u751f\u6210\u624b\u672f\u5bfc\u677f", "surgical_guide", True),
])
def test_mutation_authorization_is_local_to_positive_unquoted_unconditional_subtasks(
    message, tool_name, expected
):
    assert mutating_execution_authorized(message, tool_name) is expected


def test_subtask_source_ranges_and_quote_scope_are_preserved():
    message = "\u4e0d\u8981\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff1b\u8bf7\u751f\u6210\u624b\u672f\u5bfc\u677f"
    parsed = parse_request(message)
    assert [message[task.start:task.end] for task in parsed.subtasks] == [
        task.raw for task in parsed.subtasks
    ]
    assert [task.negated for task in parsed.subtasks] == [True, False]
    assert [task.target for task in parsed.subtasks] == ["report", "surgical_guide"]


# ---------------------------------------------------------------------------
# P1-6 UI action whitelist and destructive gate
# ---------------------------------------------------------------------------

def test_destructive_ui_action_requires_explicit_command():
    assert ui_action_explicitly_authorized("\u5220\u9664\u62a5\u544a", "report.clear")
    assert ui_action_explicitly_authorized("\u6e05\u7a7a\u5f53\u524d\u62a5\u544a", "report.clear")
    assert not ui_action_explicitly_authorized("\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "report.clear")
    assert not ui_action_explicitly_authorized("\u751f\u6210\u62a5\u544a", "report.clear")
    # A non-destructive target is always allowed through this gate.
    assert ui_action_explicitly_authorized("\u751f\u6210\u62a5\u544a", "report.autofill")


def test_unknown_ui_target_is_dropped_and_destructive_question_is_blocked():
    calls = _normalizer(
        "\u4f60\u53ef\u4ee5\u6e05\u7a7a\u5f53\u524d\u7684\u62a5\u544a\u5417",
        [{
            "id": "clear", "tool": "ui_controller",
            "params": {"actions": [{"target": "report.clear", "command": "run"}]},
        }],
    )
    assert calls == []

    calls = _normalizer(
        "\u5220\u9664\u62a5\u544a",
        [{
            "id": "unknown", "tool": "ui_controller",
            "params": {"actions": [{"target": "not.a.real.control", "command": "run"}]},
        }],
    )
    assert calls == []


@pytest.mark.parametrize("message", [
    "\u8bf7\u9690\u85cf OAR\uff0c\u5e76\u8be2\u95ee\u62a5\u544a\u662f\u5426\u5df2\u751f\u6210",
    "\u8bf7\u663e\u793a OAR\uff1b\u62a5\u544a\u751f\u6210\u4e86\u5417\uff1f",
    "\u8bf7\u67e5\u770b\u5f53\u524d\u89c4\u5212\uff0c\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417",
])
def test_provider_ui_action_cannot_borrow_report_action_from_another_clause(message):
    calls = _normalizer(message, [{
        "id": "report",
        "tool": "ui_controller",
        "params": {"actions": [{"target": "report.autofill", "command": "run"}]},
    }])
    assert calls == []


def test_positive_report_subtask_still_authorizes_its_exact_ui_action():
    message = "\u8bf7\u91cd\u65b0\u751f\u6210\u624b\u672f\u62a5\u544a"
    action = {"target": "report.autofill", "command": "run"}
    calls = _normalizer(message, [{
        "id": "report", "tool": "ui_controller", "params": {"actions": [action]},
    }])
    assert calls == [{
        "id": "report", "tool": "ui_controller", "params": {"actions": [action]},
    }]


def test_destructive_authorization_does_not_leak_between_clauses_or_quote_labels():
    assert not ui_action_explicitly_authorized(
        "\u4e0d\u8981\u5220\u9664\u62a5\u544a\uff1b\u5220\u9664\u624b\u672f\u5bfc\u677f",
        "report.clear",
    )
    assert ui_action_explicitly_authorized(
        "\u8bf7\u5220\u9664\u201c\u62a5\u544a\u201d", "report.clear"
    )


# ---------------------------------------------------------------------------
# P2-8 vocabulary coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("message", "target", "action"), [
    ("\u751f\u6210 surgery report", "report", "generate"),
    ("\u5199\u4e00\u4efd\u672f\u540e\u62a5\u544a", "report", "generate"),
    ("\u6e05\u7a7a\u5f53\u524d\u62a5\u544a", "report", "clear"),
    ("\u6838\u9a8c\u5f53\u524d\u62a5\u544a", "report", None),
    ("\u5220\u6389\u5bfc\u677f", "surgical_guide", "clear"),
])
def test_vocabulary_covers_mixed_language_and_extended_verbs(message, target, action):
    parsed = parse_request(message)
    assert parsed.target == target
    if action is not None:
        assert parsed.action == action


def test_synthetic_tool_result_does_not_replace_latest_user_reference():
    from agent_runtime.request_parse import resolve_reference_target

    conversation = [
        {"role": "user", "content": "手术导板在哪里"},
        {"role": "assistant", "content": "已读取当前界面"},
        {"role": "user", "content": "[Tool result: 肿瘤在左侧]"},
    ]

    assert resolve_reference_target("就它吧", conversation) == "surgical_guide"


def test_written_verb_and_typo_tolerance_for_report_noun():
    # The noun is recognized even with surrounding punctuation/quotes.
    assert canonical_report_mutation("\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002")
    assert parse_request("\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002").target == "report"


# ---------------------------------------------------------------------------
# Elliptical aggregate follow-up ("那请你全部更新")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "\u90a3\u8bf7\u4f60\u5168\u90e8\u66f4\u65b0",   # then please update everything
    "\u8bf7\u5168\u90e8\u66f4\u65b0",
    "\u5168\u90e8\u66f4\u65b0",
    "\u90fd\u66f4\u65b0\u4e00\u4e0b",
    "\u6240\u6709\u90fd\u66f4\u65b0\u4e00\u4e0b",
    "\u8bf7\u5168\u90e8\u91cd\u65b0\u751f\u6210",
    "\u628a\u62a5\u544a\u548c\u5bfc\u677f\u90fd\u66f4\u65b0",
    "update everything",
])
def test_aggregate_follow_up_authorizes_the_stale_artifacts(message):
    parsed = parse_request(message)
    assert parsed.aggregate_command
    for tool in (
        "dose_recompute",
        "dose_evaluation",
        "report_auto_fill",
        "report_generator",
        "surgical_guide",
    ):
        assert mutating_execution_authorized(message, tool) is True, tool


@pytest.mark.parametrize("message", [
    "\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f",          # question
    "\u4e0d\u8981\u5168\u90e8\u66f4\u65b0",                    # negation
    "\u5982\u679c\u5168\u90e8\u66f4\u65b0\u4f1a\u600e\u6837",  # conditional
    "\u201c\u5168\u90e8\u66f4\u65b0\u201d\u662f\u4ec0\u4e48\u610f\u601d",  # quotation
    "\u6bcf\u6b21\u91cd\u5efa\u90fd\u5931\u8d25",              # declarative noise
    "\u5168\u90e8\u6e05\u7a7a\u62a5\u544a",                    # destructive only
])
def test_aggregate_scope_does_not_authorize_questions_negations_or_clears(message):
    assert not parse_request(message).aggregate_command
    assert not mutating_execution_authorized(message, "dose_recompute")
    assert not mutating_execution_authorized(message, "report_auto_fill")


def test_aggregate_scope_never_authorizes_a_destructive_clear():
    # "update everything" must not become a destructive reset through the
    # aggregate path; destructive UI targets have their own explicit gate.
    assert not ui_action_explicitly_authorized("\u5168\u90e8\u66f4\u65b0", "report.clear")
    assert not ui_action_explicitly_authorized("\u5168\u90e8\u66f4\u65b0", "plan.reset")


@pytest.mark.parametrize("message", [
    "\u5168\u90e8\u66f4\u65b0\uff0c\u4e0d\u542b\u5bfc\u677f",   # all update, not the guide
    "\u5168\u90e8\u66f4\u65b0\uff0c\u4e0d\u8981\u5bfc\u677f",
    "\u9664\u4e86\u5bfc\u677f\u90fd\u66f4\u65b0",             # everything except the guide
])
def test_aggregate_scope_respects_an_explicit_exclusion(message):
    parsed = parse_request(message)
    assert "surgical_guide" in parsed.excluded_targets
    assert mutating_execution_authorized(message, "report_auto_fill") is True
    assert mutating_execution_authorized(message, "dose_evaluation") is True
    assert mutating_execution_authorized(message, "surgical_guide") is False


@pytest.mark.parametrize("message", [
    "\u5f00\u59cb\u5427", "\u6267\u884c", "\u597d\u7684", "\u53ef\u4ee5",
    "\u5c31\u6309\u4f60\u8bf4\u7684\u505a", "\u7ee7\u7eed", "go ahead", "do it",
])
def test_bare_acknowledgements_are_recognized(message):
    assert is_affirmative_acknowledgement(message)


@pytest.mark.parametrize("message", [
    "\u7ee7\u7eed\u89c4\u5212", "\u6267\u884c\u5206\u5272", "\u53ef\u4ee5\u751f\u6210\u62a5\u544a\u5417",
    "\u5168\u90e8\u66f4\u65b0",
])
def test_new_requests_are_not_acknowledgements(message):
    assert not is_affirmative_acknowledgement(message)


def test_explanatory_tool_list_cannot_authorize_a_later_acknowledgement():
    conversation = [
        {"role": "user", "content": "\u5982\u679c\u8981\u5168\u90e8\u66f4\u65b0\u5e94\u8be5\u4f7f\u7528\u54ea\u4e9b\u5de5\u5177"},
        {"role": "assistant", "content": "\u9700\u8981 dose_recompute\u3001dose_evaluation\u3001"
                                          "report_auto_fill\u3001surgical_guide\u3002"},
        {"role": "user", "content": "\u6267\u884c\u5427"},
    ]
    for tool in ("dose_recompute", "dose_evaluation", "report_auto_fill", "surgical_guide"):
        assert mutating_execution_authorized("\u6267\u884c\u5427", tool, conversation) is False
    assert mutating_execution_authorized("\u6267\u884c\u5427", "planning_pipeline", conversation) is False
    # Without the prior assistant proposal, a bare "do it" grants nothing.
    assert mutating_execution_authorized("\u6267\u884c\u5427", "dose_recompute") is False


def test_blocked_mutation_feedback_names_the_operations_for_confirmation():
    from agent_runtime.llm_runtime import _blocked_mutation_message

    zh = _blocked_mutation_message("zh", ["dose_recompute", "surgical_guide"])
    assert "dose_recompute" in zh and "surgical_guide" in zh
    assert "\u6267\u884c" in zh
    en = _blocked_mutation_message("en", ["dose_recompute"])
    assert "go ahead" in en



@pytest.mark.parametrize("message", [
    "\u91cd\u65b0\u8ba1\u7b97\u5242\u91cf",              # recompute the dose
    "\u8bf7\u91cd\u65b0\u8ba1\u7b97\u5f53\u524d\u5242\u91cf\u548cdvh",
    "\u91cd\u7b97\u5242\u91cf",
    "recompute the dose",
])
def test_recompute_synonyms_authorize_dose_recompute(message):
    assert mutating_execution_authorized(message, "dose_recompute")


def _provider_gate_normalizer(message, calls):
    from agent_runtime.turn_policy import LocalTurnPolicy

    class Memory:
        conversation = [{"role": "user", "content": message}]

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    normalizer._active_turn_policy = LocalTurnPolicy(
        "semantic_action", "medium", False, True, True, None,
        direct_execution=False,
    )
    return normalizer._normalize_tool_params(calls)


def test_provider_mutations_survive_for_an_aggregate_follow_up():
    calls = _provider_gate_normalizer("\u90a3\u8bf7\u4f60\u5168\u90e8\u66f4\u65b0", [
        {"id": "dose", "tool": "dose_recompute", "params": {}},
        {"id": "report", "tool": "report_auto_fill", "params": {}},
        {"id": "guide", "tool": "surgical_guide", "params": {"action": "generate"}},
    ])
    tools = {call["tool"] for call in calls}
    assert {"dose_recompute", "report_auto_fill", "surgical_guide"} <= tools


@pytest.mark.parametrize("message", ["\u62a5\u544a\u751f\u6210\u597d\u4e86\u5417\uff1f", "\u4e0d\u8981\u5168\u90e8\u66f4\u65b0"])
def test_provider_mutations_stay_blocked_for_non_commands(message):
    calls = _provider_gate_normalizer(message, [
        {"id": "dose", "tool": "dose_recompute", "params": {}},
        {"id": "report", "tool": "report_auto_fill", "params": {}},
    ])
    assert calls == []


def test_provider_excludes_a_carved_out_target():
    calls = _provider_gate_normalizer("\u5168\u90e8\u66f4\u65b0\uff0c\u4e0d\u542b\u5bfc\u677f", [
        {"id": "report", "tool": "report_auto_fill", "params": {}},
        {"id": "guide", "tool": "surgical_guide", "params": {"action": "generate"}},
    ])
    tools = {call["tool"] for call in calls}
    assert "report_auto_fill" in tools
    assert "surgical_guide" not in tools


def test_provider_acknowledgement_does_not_execute_an_explanatory_tool_list():
    from agent_runtime.turn_policy import LocalTurnPolicy

    conversation = [
        {"role": "user", "content": "\u8981\u5168\u90e8\u66f4\u65b0\u8be5\u7528\u54ea\u4e9b\u5de5\u5177"},
        {"role": "assistant", "content": "dose_recompute, dose_evaluation, "
                                          "report_auto_fill, surgical_guide"},
        {"role": "user", "content": "\u6267\u884c\u5427"},
    ]

    class Memory:
        def __init__(self):
            self.conversation = conversation

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    normalizer._active_turn_policy = LocalTurnPolicy(
        "semantic_action", "medium", False, True, True, None,
        direct_execution=False,
    )
    calls = normalizer._normalize_tool_params([
        {"id": "dose", "tool": "dose_recompute", "params": {}},
        {"id": "report", "tool": "report_auto_fill", "params": {}},
        {"id": "guide", "tool": "surgical_guide", "params": {"action": "generate"}},
    ])
    assert calls == []





# ---------------------------------------------------------------------------
# P1-4 compound ordered goals
# ---------------------------------------------------------------------------

def test_compound_write_goals_are_parsed_in_order_and_stay_semantic():
    policy = classify_local_turn("\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f\u548c\u62a5\u544a")
    assert policy.intent == "semantic_action"
    assert not policy.direct_execution
    assert policy.parsed_goals == (
        ("surgical_guide", "generate"),
        ("report", "generate"),
    )


def test_single_read_of_two_objects_is_not_a_compound_write():
    assert not parse_request("\u67e5\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe").compound_write
    assert classify_local_turn("\u67e5\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe").intent == "session_content_query"


# ---------------------------------------------------------------------------
# P1-7 in-memory state gate
# ---------------------------------------------------------------------------

def test_report_state_gate_refuses_without_a_plan_and_allows_with_one():
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Memory:
        user_lang = "zh"

        def __init__(self, values):
            self.values = values
            self.conversation = []

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

    class Workflow(ChatWorkflowMixin):
        pass

    workflow = Workflow()
    workflow.memory = Memory({})
    blocked = workflow._report_generation_state_gate()
    assert blocked and "\u89c4\u5212\u7ed3\u679c" in blocked
    workflow.memory = Memory({"dose_metrics": {"D90": 1.0}})
    assert workflow._report_generation_state_gate() is None


def test_guide_state_gate_presents_a_ready_guide_instead_of_recomputing():
    from tool_factory import ToolResult

    class Memory:
        user_lang = "en"

        def __init__(self, values):
            self.values = values
            self.conversation = []

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def get_ui_state(self):
            return {}

    class Harness(ResponseToolMixin):
        def __init__(self, memory):
            self.memory = memory

    ready = Harness(Memory({"surgical_guide": {"status": "ready"}}))
    calls = ready._detect_tool_request("\u751f\u6210\u624b\u672f\u5bfc\u677f")
    assert calls and calls[0]["tool"] == "ui_controller"
    assert calls[0]["params"]["actions"][0]["target"] == "viewer.refresh_planning"

    # An explicit regeneration still reaches the clinical tool.
    forced = Harness(Memory({"surgical_guide": {"status": "ready"}}))
    calls = forced._detect_tool_request("\u91cd\u65b0\u751f\u6210\u624b\u672f\u5bfc\u677f")
    assert calls and calls[0]["tool"] == "surgical_guide"

def test_confirmation_prompt_ack_authorizes_full_planning_chain():
    """A bare 'execution' after a confirmation prompt must not re-block the chain.

    The LLM re-emits only the first steps (ctv_segmentation, oar_segmentation)
    instead of the anchor tool named in the prompt.  Those are prerequisites of
    the confirmed plan and must not trigger a second confirmation loop.
    """
    from agent_runtime.request_parse import mutating_execution_authorized

    conversation = [
        {"role": "user", "content": "\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212"},
        {
            "role": "assistant",
            "content": (
                "\u4e3a\u907f\u514d\u8bef\u6539\u5f53\u524d\u75c5\u4f8b\uff0c"
                "\u4e0b\u9762\u8fd9\u4e9b\u64cd\u4f5c\u9700\u8981\u4f60\u4e00\u53e5\u660e\u786e\u786e\u8ba4\u540e\u518d\u6267\u884c\uff1a\n\n"
                "`planning_pipeline, surgical_guide`\n\n"
                "\u56de\u590d\u300c\u6267\u884c\u300d\u6211\u5c31\u6309\u4f9d\u8d56\u987a\u5e8f\u8fd0\u884c\uff1b"
                "\u82e5\u8981\u8df3\u8fc7\u67d0\u4e00\u9879\uff0c\u8bf7\u8bf4\u660e\uff08\u4f8b\u5982\u300c\u4e0d\u542b\u5bfc\u677f\u300d\uff09\u3002"
            ),
        },
        {"role": "user", "content": "\u6267\u884c"},
    ]

    # The full planning dependency chain is authorized.
    for tool in ("ctv_segmentation", "oar_segmentation", "planning_pipeline"):
        assert mutating_execution_authorized("\u6267\u884c", tool, conversation) is True

    # A tool named in the confirmation prompt is also authorized.
    assert mutating_execution_authorized("\u6267\u884c", "surgical_guide", conversation) is True

    # An unrelated mutation is still blocked.
    assert mutating_execution_authorized("\u6267\u884c", "dose_recompute", conversation) is False


def test_confirmation_list_must_be_bounded_and_not_inherited_from_prose():
    conversation = [
        {"role": "assistant", "content": (
            "为避免误改当前病例，下面这些操作需要你一句明确确认后再执行：\n\n"
            "`dose_recompute, surgical_guide`\n\n回复「执行」我就按依赖顺序运行。"
        )},
        {"role": "user", "content": "执行"},
    ]
    assert mutating_execution_authorized("执行", "dose_recompute", conversation)
    assert mutating_execution_authorized("执行", "surgical_guide", conversation)
    assert not mutating_execution_authorized("执行", "report_auto_fill", conversation)


def test_confirmation_prompt_detection_requires_the_prompt_markers():
    """Only the blocked-mutation prompt text triggers chain-wide authorization."""
    from agent_runtime.request_parse import mutating_execution_authorized

    # A normal assistant reply that happens to name planning_pipeline does not
    # unlock the chain for tools it never mentioned.
    conversation = [
        {"role": "user", "content": "\u8bf7\u6267\u884c\u653e\u5c04\u6027\u7c92\u5b50\u690d\u5165\u89c4\u5212"},
        {
            "role": "assistant",
            "content": "\u6211\u5efa\u8bae\u5148\u8fd0\u884c planning_pipeline\u3002",
        },
        {"role": "user", "content": "\u6267\u884c"},
    ]
    assert mutating_execution_authorized("\u6267\u884c", "ctv_segmentation", conversation) is False


def test_partial_planning_grant_does_not_unlock_full_chain():
    """CTV/OAR work alone cannot silently authorize treatment planning."""
    from agent_runtime.execution_authorization import TurnExecutionAuthorization

    auth = TurnExecutionAuthorization(token=1)
    auth.grant_tools({"ctv_segmentation", "oar_segmentation"}, source="test")

    assert auth.tool_allowed("ctv_segmentation") is True
    assert auth.tool_allowed("oar_segmentation") is True
    assert auth.tool_allowed("planning_pipeline") is False
    # Non-chain mutations remain blocked.
    assert auth.tool_allowed("surgical_guide") is False
    assert auth.tool_allowed("dose_recompute") is False


def test_explicit_full_planning_grant_unlocks_required_prerequisites():
    """Only an accepted full-planning operation may derive missing masks."""
    from agent_runtime.execution_authorization import TurnExecutionAuthorization

    auth = TurnExecutionAuthorization(token=1)
    auth.grant_tools({"planning_pipeline"}, source="test")

    assert auth.tool_allowed("planning_pipeline") is True
    assert auth.tool_allowed("ctv_segmentation") is True
    assert auth.tool_allowed("oar_segmentation") is True
    assert auth.tool_allowed("surgical_guide") is False

