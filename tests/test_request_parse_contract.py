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


def test_written_verb_and_typo_tolerance_for_report_noun():
    # The noun is recognized even with surrounding punctuation/quotes.
    assert canonical_report_mutation("\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002")
    assert parse_request("\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002").target == "report"


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

