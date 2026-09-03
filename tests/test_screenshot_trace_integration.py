import json
from pathlib import Path

import pytest

from agent_runtime.chat_workflows import ChatWorkflowMixin
from agent_runtime.llm_runtime import _collect_tool_fallback_text
from agent_runtime.core import ToolResultPipeline
from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import (
    classify_local_turn,
    is_report_generation_request,
    resolve_report_request_action,
    resolve_session_content_presentation,
    resolve_session_content_target,
    visual_analysis_policy,
)
from agent_runtime.visual_evidence import (
    VISUAL_EVIDENCE_PROTOCOL_MARKER,
    build_visual_evidence_prompt,
    normalize_visual_evidence_context,
)
from tool_factory import ToolResult
from tool_factory.ui_content import UISessionContentTool
from tool_factory.ui_screenshot import UIScreenshotTool
from web.chat_tasks import ChatTask


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_screenshot_tool_builds_internal_structured_chat_plan():
    result = UIScreenshotTool().execute(
        mode="chat",
        target="dose-overview",
        question="请截图并分析当前剂量结果",
        object_ids=["seed-1"],
        data_tree_node_ids=["planning-seeds"],
    )

    assert result.success is True
    plan = result.metadata["screenshot_plan"]
    assert plan["mode"] == "chat"
    assert plan["views"] == [
        "viewer-axial",
        "viewer-sagittal",
        "viewer-coronal",
        "dvh",
    ]
    assert plan["object_ids"] == ["seed-1"]
    assert plan["data_tree_node_ids"] == ["planning-seeds"]
    assert result.metadata["internal_only"] is True
    assert result.metadata["user_visible"] is False
    assert result.metadata["trace_summary_i18n"]["zh"].startswith("已创建截图计划")


def test_structured_multi_view_call_does_not_require_legacy_target():
    calls = ResponseToolMixin()._normalize_tool_params(
        [
            {
                "tool": "ui_screenshot",
                "params": {
                    "mode": "monitor",
                    "views": ["viewer-3d", "viewer-axial"],
                    "question": "显示发生干涉的粒子",
                },
            },
            {
                "tool": "ui_screenshot",
                "params": {"views": ["viewer-3d"]},
            },
        ]
    )

    assert len(calls) == 1
    assert calls[0]["params"]["views"] == ["viewer-3d", "viewer-axial"]


def test_internal_screenshot_result_never_becomes_fallback_chat_text():
    successes, failures = _collect_tool_fallback_text(
        [
            {
                "type": "tool",
                "tool": "ui_screenshot",
                "status": "done",
                "result": "Requested screenshot: internal prompt",
                "metadata": {
                    "internal_only": True,
                    "user_visible": False,
                },
            }
        ],
        [],
    )

    assert successes == []
    assert failures == []


def test_session_content_tool_builds_localized_session_bound_command():
    result = UISessionContentTool().execute(
        target="report_figures",
        presentation="attachments",
        mode="chat",
        question="\u6211\u60f3\u770b\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe",
        planning_id="planning-7",
        object_ids=["report-figure-1"],
    )

    assert result.success is True
    assert result.metadata["frontend_action"] == "session_content"
    assert result.metadata["internal_only"] is True
    assert result.metadata["user_visible"] is False
    command = result.metadata["content_command"]
    assert command["command"] == "present_session_content"
    assert command["target"] == "report_figures"
    assert command["planning_id"] == "planning-7"
    assert command["object_ids"] == ["report-figure-1"]
    assert "\u62a5\u544a" in result.metadata["trace_summary_i18n"]["zh"]


def test_dvh_session_content_supports_native_visual_presentation():
    result = UISessionContentTool().execute(
        target="dvh",
        presentation="visual",
        mode="chat",
        question="\u8bf7\u7ed9\u6211\u770b\u770b DVH \u7ed3\u679c",
    )

    assert result.success is True
    assert "visual" in UISessionContentTool().input_schema["properties"]["presentation"]["enum"]
    command = result.metadata["content_command"]
    assert command["target"] == "dvh"
    assert command["presentation"] == "visual"
    assert "\u56fe\u8868" in result.metadata["trace_summary_i18n"]["zh"]


def test_session_content_contract_preserves_ordinal_selection_and_visual_analysis():
    """A provider may omit modifiers, but the content contract cannot lose them."""
    result = UISessionContentTool().execute(
        target="report_figures",
        presentation="attachments",
        mode="chat",
        question="\u6253\u5f00\u6700\u540e\u4e00\u5f20\u622a\u56fe\uff0c\u89e3\u8bfb",
    )

    command = result.metadata["content_command"]
    assert command["selection"] == {"kind": "last"}
    assert command["analysis"] is True
    assert command["presentation"] == "visual"

    trace = ToolResultPipeline.trace_metadata("ui_content", result.metadata)
    assert trace["content_command"]["selection"] == {"kind": "last"}
    assert trace["content_command"]["analysis"] is True
    assert "question" not in trace["content_command"]


def test_session_content_contract_keeps_passive_last_item_view_fast_and_attachment_based():
    result = UISessionContentTool().execute(
        target="report_figures",
        presentation="attachments",
        mode="chat",
        question="\u6253\u5f00\u6700\u540e\u4e00\u5f20\u622a\u56fe",
    )

    command = result.metadata["content_command"]
    assert command["selection"] == {"kind": "last"}
    assert command["analysis"] is False
    assert command["presentation"] == "attachments"


def test_prior_reply_attachment_target_preserves_source_selection_and_analysis_contract():
    message = "\u6253\u5f00\u4e0a\u4e00\u6761\u56de\u590d\u4e2d\u7684\u6700\u540e\u4e00\u5f20\u622a\u56fe\uff0c\u89e3\u8bfb"
    result = UISessionContentTool().execute(
        target="reply_attachments",
        presentation="attachments",
        mode="chat",
        question=message,
    )

    command = result.metadata["content_command"]
    assert command["target"] == "reply_attachments"
    assert command["selection"] == {"kind": "last"}
    assert command["analysis"] is True
    assert command["presentation"] == "visual"
    assert "\u56de\u590d" in result.metadata["trace_summary_i18n"]["zh"]


def test_conversational_attachment_reference_resolves_before_global_figure_collection():
    message = "\u6253\u5f00\u4e0a\u4e00\u6761\u56de\u590d\u4e2d\u7684\u6700\u540e\u4e00\u5f20\u622a\u56fe\uff0c\u89e3\u8bfb"

    assert resolve_session_content_target(message) == "reply_attachments"
    assert resolve_session_content_presentation(message, "reply_attachments") == "attachments"
    assert classify_local_turn(message).intent == "semantic_action"
    # A durable owner remains authoritative when the user names it explicitly.
    assert resolve_session_content_target("\u6253\u5f00\u6700\u540e\u4e00\u5f20\u62a5\u544a\u622a\u56fe") == "report_figures"


def test_visual_analysis_child_uses_a_dedicated_role_instead_of_text_routing():
    """Uploaded evidence must not be reclassified as another ui_content request."""
    policy = visual_analysis_policy()

    assert policy.intent == "visual_analysis"
    assert policy.use_router is False
    assert policy.use_completeness is False
    assert policy.allow_tools is None


def test_tool_normalization_keeps_deictic_attachment_reference_bound_to_previous_reply():
    message = "\u6253\u5f00\u6700\u540e\u4e00\u5f20\u622a\u56fe\uff0c\u89e3\u8bfb"
    calls = ResponseToolMixin()._normalize_tool_params([{
        "tool": "ui_content",
        "params": {
            "target": "report_figures",
            "presentation": "attachments",
            "question": message,
        },
    }])

    assert calls[0]["tool"] == "ui_content"
    assert calls[0]["params"]["target"] == "reply_attachments"
    assert calls[0]["params"]["selection"] == {"kind": "last"}
    assert calls[0]["params"]["analysis"] is True


def test_session_content_tool_returns_localized_unavailable_error_for_an_unknown_resource():
    result = UISessionContentTool().execute(
        target="not_a_real_resource",
        question="\u67e5\u770b\u5f53\u524d\u6570\u636e",
    )

    assert result.success is False
    assert result.metadata["internal_only"] is True
    assert result.metadata["user_visible"] is False
    assert "\u6682\u4e0d\u652f\u6301" in result.metadata["user_error_i18n"]["zh"]
    assert "Unsupported Session content target" not in result.metadata["user_error_i18n"]["zh"]


def test_presentation_result_formatter_never_exposes_internal_instruction_or_raw_error():
    success = UISessionContentTool().execute(
        target="report_figures",
        question="\u6211\u60f3\u770b\u770b\u62a5\u544a\u622a\u56fe",
    )
    failure = ToolResult(
        success=False,
        error="browser command failed at /internal/path with raw details",
        metadata={
            "user_error_i18n": {
                "zh": "\u5f53\u524d Session \u4e2d\u6ca1\u6709\u53ef\u5448\u73b0\u7684\u62a5\u544a\u622a\u56fe\u3002",
                "en": "The current Session has no report figures available to present.",
            },
        },
    )

    assert ToolResultPipeline.format("ui_content", success, "en") == (
        "Reading the saved figures from the current report."
    )
    assert "browser will present" not in ToolResultPipeline.format("ui_content", success, "en").lower()
    assert ToolResultPipeline.format("ui_content", failure, "zh") == (
        "\u5f53\u524d Session \u4e2d\u6ca1\u6709\u53ef\u5448\u73b0\u7684\u62a5\u544a\u622a\u56fe\u3002"
    )
    assert "/internal/path" not in ToolResultPipeline.format("ui_content", failure, "zh")


def test_presentation_trace_metadata_contains_only_the_browser_contract():
    result = UISessionContentTool().execute(
        target="report_figures",
        presentation="attachments",
        question="\u6211\u60f3\u770b\u770b\u62a5\u544a\u622a\u56fe",
        planning_id="planning-7",
        object_ids=["report-figure-1"],
    )

    trace_metadata = ToolResultPipeline.trace_metadata("ui_content", result.metadata)
    assert trace_metadata["content_command"]["target"] == "report_figures"
    assert trace_metadata["content_command"]["planning_id"] == "planning-7"
    assert trace_metadata["content_command"]["object_ids"] == ["report-figure-1"]
    assert "question" not in trace_metadata["content_command"]
    assert "model_instruction" not in trace_metadata
    assert "frontend_action" not in trace_metadata


def test_screenshot_trace_contract_preserves_scene_ids_but_not_model_text():
    result = UIScreenshotTool().execute(
        mode="chat",
        target="dose-overview",
        question="\u8bf7\u622a\u56fe\u5e76\u5206\u6790\u5f53\u524d\u5242\u91cf\u7ed3\u679c",
        object_ids=["seed-1"],
        data_tree_node_ids=["planning-seeds"],
        highlight_object_ids=["seed-1"],
        hide_unrelated=True,
    )

    trace_metadata = ToolResultPipeline.trace_metadata("ui_screenshot", result.metadata)
    plan = trace_metadata["screenshot_plan"]
    assert plan["object_ids"] == ["seed-1"]
    assert plan["data_tree_node_ids"] == ["planning-seeds"]
    assert plan["highlight_object_ids"] == ["seed-1"]
    assert plan["hide_unrelated"] is True
    assert "question" not in plan
    assert "model_instruction" not in trace_metadata


def test_presentation_pending_trace_params_are_safe_before_a_tool_completes():
    pending = ToolResultPipeline.trace_params(
        "ui_screenshot",
        {
            "mode": "chat",
            "target": "viewer-3d",
            "question": "internal user request text",
            "description": "model-only composition instruction",
            "object_ids": ["seed-1"],
            "data_tree_node_ids": ["planning-seeds"],
            "highlight_object_ids": ["seed-1"],
            "hide_unrelated": True,
            "focus": {"kind": "close-up"},
        },
    )

    assert pending["target"] == "viewer-3d"
    assert pending["object_ids"] == ["seed-1"]
    assert pending["data_tree_node_ids"] == ["planning-seeds"]
    assert pending["highlight_object_ids"] == ["seed-1"]
    assert pending["hide_unrelated"] is True
    assert "question" not in pending
    assert "description" not in pending


@pytest.mark.parametrize(
    ("message", "target"),
    [
        ("\u663e\u793a\u5f53\u524d CT \u5f71\u50cf", "ct"),
        ("\u67e5\u770b\u5f53\u524d\u7ed3\u6784\u548c\u5206\u5272\u7ed3\u679c", "structures"),
        ("\u67e5\u770b\u5f53\u524d\u89c4\u5212\u7ed3\u679c", "planning"),
        ("\u67e5\u770b\u5f53\u524d\u5242\u91cf\u7ed3\u679c", "dose"),
        ("\u67e5\u770b\u5f53\u524d DVH", "dvh"),
        ("\u67e5\u770b\u5f53\u524d\u89c4\u5212\u6307\u6807", "metrics"),
        ("\u67e5\u770b\u5f53\u524d\u624b\u672f\u5bfc\u677f", "surgical_guide"),
        ("\u67e5\u770b\u5f53\u524d Data Tree", "data_tree"),
        ("\u67e5\u770b\u5f53\u524d\u5bf9\u8bdd\u5386\u53f2", "chat_history"),
    ],
)
def test_session_content_resolver_covers_each_persisted_resource_family(message, target):
    assert resolve_session_content_target(message) == target
    assert classify_local_turn(message).intent == "session_content_query"


def test_selected_data_tree_object_uses_generic_artifact_focus_without_name_matching():
    message = "\u663e\u793a\u5f53\u524d\u9009\u4e2d\u7684\u8282\u70b9"

    assert resolve_session_content_target(message) == "artifact"
    assert resolve_session_content_presentation(message, "artifact") == "open"
    assert classify_local_turn(message).intent == "session_content_query"


def test_persisted_report_figure_request_uses_session_content_not_live_capture():
    message = "\u6211\u60f3\u770b\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe"

    assert resolve_session_content_target(message) == "report_figures"
    assert classify_local_turn(message).intent == "session_content_query"
    calls = ResponseToolMixin()._normalize_tool_params(
        [{
            "tool": "ui_screenshot",
            "params": {
                "mode": "chat",
                "views": ["report"],
                "question": message,
                "planning_id": "planning-7",
            },
        }]
    )
    assert len(calls) == 1
    assert calls[0]["tool"] == "ui_content"
    assert calls[0]["params"]["target"] == "report_figures"
    assert calls[0]["params"]["planning_id"] == "planning-7"


def test_interpretive_session_content_request_uses_semantic_reasoning_not_read_only_ack():
    message = "\u8bf7\u6253\u5f00\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe\u5e76\u8be6\u7ec6\u89e3\u8bfb"

    assert resolve_session_content_target(message) == "report_figures"
    policy = classify_local_turn(message)
    assert policy.intent == "semantic_action"
    assert "ui_content" in policy.allow_tools


@pytest.mark.parametrize(
    "message",
    [
        "\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a",
        "\u8bf7\u66f4\u65b0\u5f53\u524d\u62a5\u544a",
        "\u6211\u662f\u8981\u4f60\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff0c\u4e0d\u662f\u7ed9\u6211\u622a\u56fe\uff0c\u62a5\u544a\u91cc\u7684\u6587\u5b57\u8fd8\u6ca1\u586b\u5145",
        "regenerate the current report",
        "auto-fill the report",
        "Regenerate the full report, not screenshots; the report text is still empty.",
    ],
)
def test_report_generation_is_an_action_not_a_persisted_content_query(message):
    assert is_report_generation_request(message) is True
    assert resolve_session_content_target(message) is None
    policy = classify_local_turn(message)
    assert policy.intent in {"report_generation", "semantic_action"}
    assert "ui_controller" in policy.allow_tools


def test_report_read_request_remains_read_only_after_generation_intent_split():
    message = "\u8bf7\u67e5\u770b\u5f53\u524d\u62a5\u544a"
    assert is_report_generation_request(message) is False
    assert resolve_session_content_target(message) == "report"
    assert classify_local_turn(message).intent == "session_content_query"
    assert is_report_generation_request("show the generated report") is False


def test_report_action_resolver_honors_negation_and_keeps_operations_distinct():
    assert resolve_report_request_action(
        "\u91cd\u65b0\u751f\u6210\u62a5\u544a\uff0c\u4e0d\u8981\u53ea\u7ed9\u6211\u622a\u56fe"
    ) == "regenerate"
    assert resolve_report_request_action(
        "Regenerate the report rather than showing report figures"
    ) == "regenerate"
    assert resolve_report_request_action("\u8bf7\u67e5\u770b\u62a5\u544a\u622a\u56fe") == "view_figures"
    assert resolve_report_request_action("\u8bf7\u6253\u5f00\u5f53\u524d\u62a5\u544a") == "view"


@pytest.mark.parametrize("tool_name", ["ui_content", "ui_screenshot"])
def test_tool_normalization_cannot_downgrade_report_generation_to_figures(tool_name):
    class Memory:
        conversation = [{
            "role": "user",
            "content": "\u62a5\u544a\u6b63\u6587\u8fd8\u6ca1\u586b\uff0c\u4e0d\u8981\u7ed9\u6211\u62a5\u544a\u622a\u56fe",
        }]

        @staticmethod
        def retrieve(_key):
            return None

    normalizer = ResponseToolMixin()
    normalizer.memory = Memory()
    normalizer._active_turn_policy = classify_local_turn(
        "\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a"
    )
    params = {
        "question": "\u62a5\u544a\u6b63\u6587\u8fd8\u6ca1\u586b\uff0c\u4e0d\u8981\u7ed9\u6211\u62a5\u544a\u622a\u56fe",
    }
    if tool_name == "ui_content":
        params.update({"target": "report_figures", "presentation": "attachments"})
    else:
        params.update({"views": ["report"], "mode": "chat"})

    calls = normalizer._normalize_tool_params([{"tool": tool_name, "params": params}])

    assert calls == [{
        "tool": "ui_controller",
        "params": {"actions": [{"target": "report.autofill", "command": "run"}]},
    }]


def test_report_generation_stream_emits_real_autofill_action_not_report_figures():
    class Memory:
        def __init__(self):
            self.user_lang = "zh"
            self.conversation = []

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

    class Workflow(ChatWorkflowMixin):
        def __init__(self):
            self.memory = Memory()
            self.multi_agent_wrapper = None
            self._turn_token = "turn-report"

        def _begin_turn(self, _message):
            return None

        def _current_turn_token(self):
            return self._turn_token

        def _is_turn_cancelled(self, _token):
            return False

        def _pending_tumor_site_clarification(self):
            return False

        def _execute_tool_with_memory(self, name, params):
            assert name == "ui_controller"
            assert params == {"actions": [{"target": "report.autofill", "command": "run"}]}
            return ToolResult(
                success=True,
                message="report.autofill: run",
                metadata={"actions": params["actions"]},
            )

        def _finish_turn(self, _response):
            return None

    events = list(Workflow().chat_with_stream("\u8bf7\u91cd\u65b0\u751f\u6210\u62a5\u544a"))
    parsed = []
    for event in events:
        lines = event.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event: "):
            parsed.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))

    controller_steps = [data for event, data in parsed if event == "step" and data.get("tool") == "ui_controller"]
    assert len(controller_steps) == 2
    assert controller_steps[-1]["status"] == "done"
    assert controller_steps[-1]["metadata"]["actions"] == [
        {"target": "report.autofill", "command": "run"},
    ]
    assert not any(data.get("tool") == "ui_content" for event, data in parsed if event == "step")
    response = next(data for event, data in parsed if event == "response")
    assert response["llm_meta"]["route"] == "local_report_generation"
    assert "Reference/Status" in response["response"]


def test_session_content_stream_keeps_report_figures_in_the_owning_reply():
    class Memory:
        def __init__(self):
            self.user_lang = "en"
            self.conversation = []

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

        def get_ui_state(self):
            return {}

    class Registry:
        def get(self, name):
            assert name == "ui_content"
            return UISessionContentTool()

    class Workflow(ChatWorkflowMixin):
        def __init__(self):
            self.memory = Memory()
            self.registry = Registry()
            self.multi_agent_wrapper = None
            self._turn_token = "turn-1"

        def _begin_turn(self, _message):
            return None

        def _current_turn_token(self):
            return self._turn_token

        def _is_turn_cancelled(self, _token):
            return False

        def _pending_tumor_site_clarification(self):
            return False

        def _execute_tool_with_memory(self, name, params):
            return self.registry.get(name).execute(**params)

        def _finish_turn(self, _response):
            return None

    workflow = Workflow()
    events = list(workflow.chat_with_stream("\u6211\u60f3\u770b\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe"))
    parsed = []
    for event in events:
        lines = event.splitlines()
        if len(lines) < 2 or not lines[0].startswith("event: "):
            continue
        parsed.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))

    content_steps = [data for event, data in parsed if event == "step" and data.get("tool") == "ui_content"]
    content_step = content_steps[-1]
    assert len(content_steps) == 2
    assert content_steps[0]["id"] == content_step["id"]
    assert content_step["status"] == "done"
    assert content_step["metadata"]["content_command"]["target"] == "report_figures"
    assert content_step["metadata"]["internal_only"] is True
    assert "model_instruction" not in content_step["metadata"]
    assert "browser will present" not in content_step["result"].lower()
    response = next(data for event, data in parsed if event == "response")
    assert response["llm_meta"]["route"] == "local_session_content"
    assert "\u6b63\u5728\u5448\u73b0" in response["response"]
    assert "A valid screenshot could not be generated" not in response["response"]


def test_session_content_json_trace_carries_the_same_safe_browser_command():
    class Memory:
        def __init__(self):
            self.user_lang = "en"
            self.conversation = []

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

    class Workflow(ChatWorkflowMixin):
        def __init__(self):
            self.memory = Memory()
            self._turn_token = "turn-1"

        def _begin_turn(self, _message):
            return None

        def _pending_tumor_site_clarification(self):
            return False

        def _record_experience(self, _message, _response, _steps=None):
            return None

        def _finish_turn(self, _response):
            return None

    result = Workflow().chat_with_trace("show the current report figures")

    content_step = next(step for step in result["steps"] if step.get("tool") == "ui_content")
    assert result["llm_meta"]["route"] == "local_session_content"
    assert content_step["status"] == "done"
    assert content_step["metadata"]["content_command"]["target"] == "report_figures"
    assert content_step["metadata"]["content_command"]["presentation"] == "attachments"
    assert "question" not in content_step["metadata"]["content_command"]
    assert "model_instruction" not in content_step["metadata"]


def test_session_content_stream_returns_localized_unavailable_state_without_registry_error():
    class Memory:
        def __init__(self):
            self.user_lang = "en"
            self.conversation = []

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

        def get_ui_state(self):
            return {}

    class Registry:
        def get(self, _name):
            raise KeyError("old registry")

    class Workflow(ChatWorkflowMixin):
        def __init__(self):
            self.memory = Memory()
            self.registry = Registry()
            self.multi_agent_wrapper = None
            self._turn_token = "turn-2"

        def _begin_turn(self, _message):
            return None

        def _current_turn_token(self):
            return self._turn_token

        def _is_turn_cancelled(self, _token):
            return False

        def _pending_tumor_site_clarification(self):
            return False

        def _finish_turn(self, _response):
            return None

    workflow = Workflow()
    events = list(workflow.chat_with_stream("\u6211\u60f3\u770b\u770b\u5f53\u524d\u62a5\u544a\u4e2d\u7684\u622a\u56fe"))
    response_event = next(event for event in events if event.startswith("event: response\n"))
    response = json.loads(response_event.splitlines()[1].removeprefix("data: "))
    assert "\u6682\u65f6\u65e0\u6cd5\u8bfb\u53d6" in response["response"]
    assert "KeyError" not in response["response"]


def test_chat_task_exposes_stable_request_and_message_identity():
    task = ChatTask(
        task_id="task-1",
        user_id="user-1",
        session_id="case-1",
        agent=None,
        message="hello",
        request_id="request-1",
        user_message_id="user-message-1",
        assistant_message_id="assistant-message-1",
        response_language="zh",
    )

    state = task.public_state()
    assert state["request_id"] == "request-1"
    assert state["user_message_id"] == "user-message-1"
    assert state["assistant_message_id"] == "assistant-message-1"


def test_frontend_keeps_trace_and_attachments_bound_to_stable_ids():
    core = _source("web/app/static/js/brachybot-chat-core.js")
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")

    assert ".thinking-chain:not([id])" not in core
    assert "row.dataset.requestId = stableRequestId;" in core
    assert "row.dataset.messageId = messageId;" in core
    assert "renderAssistantAttachments(shell, [attachment]" in ui_api
    assert "requestId: task.request_id || taskId" in chat
    assert "assistantMessageId: task.assistant_message_id" in chat
    assert ui_api.count("async function _interceptScreenshot(") == 1
    assert "async function _interceptScreenshotLegacy(" in ui_api
    assert "return _interceptScreenshot(target, question, galleryContext, options);" in ui_api
    legacy_start = ui_api.index("async function _interceptScreenshotLegacy(")
    legacy_end = ui_api.index("// Structured chat/Monitor screenshot executor.", legacy_start)
    assert "addChat(" not in ui_api[legacy_start:legacy_end]


def test_chat_images_survive_out_of_order_capture_and_session_restore():
    core = _source("web/app/static/js/brachybot-chat-core.js")
    workspace = _source("web/app/static/js/brachybot-workspace.js")
    routes = _source("web/routes/planning_routes.py")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")

    # The screenshot endpoint must not depend on a long-running ChatTask
    # local variable when it creates the assistant shell itself.
    endpoint = routes.split('@app.route("/api/screenshot"', 1)[1].split(
        '@app.route("/api/sessions/<session_id>/screenshots/<filename>"', 1
    )[0]
    assert 'response_language = str(' in endpoint
    assert 'getattr(task, "response_language"' not in endpoint
    assert 'chat_patch = {"attachments": [attachment]}' in endpoint

    # Restore must merge equal-length messages by stable identity, not replace
    # a richer local attachment list with a stale server copy.
    assert "function mergeSessionChatMessages(sessionId, serverMessages, localMessages, registry = [])" in core
    assert "window.mergeSessionChatMessages(sessionId, chatMessages, localMsgs, chat.attachments)" in workspace
    assert "window.mergeSessionChatMessages(sessionId, messages, currentMessages, chat.attachments)" in workspace
    assert "normalizeChatAttachments" in core
    assert "renderAssistantAttachments(" in core
    assert "user-supplied" in core
    assert "response_language: context.responseLanguage || ''" in ui_api


def test_screenshot_failure_returns_to_the_owning_reply_without_creating_a_new_message():
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")

    failure_start = ui_api.index("function _screenshotFailureMessage")
    failure_end = ui_api.index("async function _interceptScreenshot(", failure_start)
    failure_source = ui_api[failure_start:failure_end]
    assert "function _renderScreenshotFailure" not in ui_api
    assert "saveSessionMessage(" not in failure_source
    assert "ensureAssistantReplyContainer(" not in failure_source
    assert "userMessage: _screenshotFailureMessage(context, errorCode)" in ui_api


def test_session_content_frontend_merges_real_attachments_and_never_emits_raw_logs():
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    routes = _source("web/routes/planning_routes.py")

    assert "window.presentSessionContent = async function" in ui_api
    assert "_appendPersistedReportFigures" in ui_api
    assert "_appendPersistedSessionScreenshots" in ui_api
    assert "_readPlanningResultsForPresentation" in ui_api
    assert "_sessionContentObjectSummary" in ui_api
    assert "function _sessionContentObjectIndex" in ui_api
    assert "_SESSION_CONTENT_VISUAL_CAPABILITIES" in ui_api
    assert "_captureSessionContentVisual" in ui_api
    assert "_ensureSessionDvhChart" in ui_api
    assert "function _selectSessionContentItems" in ui_api
    assert "function _sessionContentRequestsVisualAnalysis" in ui_api
    assert "function _mostRecentVisibleReplyAttachments" in ui_api
    assert "function _appendReferencedReplyAttachments" in ui_api
    assert "source_message_id" in ui_api
    assert "selected_for_analysis" in ui_api
    assert "visual_analysis: analyze" in ui_api
    assert "visual_analysis === true" in chat
    assert "result.analysis === true" in chat
    assert "_queueVisualAnalysisFollowUp" in chat
    assert "visualAnalysisContinuation" in chat
    assert "_visualAnalysisUnavailableMessage" in chat
    assert "visualContentResults," in chat
    assert "presentation.attachments" in chat
    assert "function _focusSessionContentObjects" in ui_api
    for token in (
        "add(tree.ct",
        "tree.ctvLabels",
        "add(tree.skin",
        "tree.organs",
        "planning.trajectories",
        "planning.needles",
        "planning.seeds",
        "planning.doseOverlay",
        "planning.doseLevels",
        "planning.dvh",
        "planning.meshes",
        "tree.annotations",
        "tree.exportArtifacts",
        "viewerState.maskLabels",
    ):
        assert token in ui_api
    assert "function _openSessionContentPanel" in ui_api
    assert "sessionContentTasks" in chat
    assert "presentationAttachments" in chat
    assert "presentationMessages" in chat
    assert "data.tool === 'ui_content'" in chat
    assert "async function _presentJsonSessionContent" in chat
    assert "await _presentJsonSessionContent(data?.steps" in chat
    assert "function _chatUserVisibleFailure" in chat
    assert "AI error: ' + data.message" not in chat
    assert "Send failed: ' + (e?.message || e)" not in chat
    assert 'presentation_tool in {"ui_screenshot", "ui_content"}' in routes
    assert '"content_command"' in routes
    assert "visual_analysis_continuation" in routes
    assert 'get("analysis")' in routes


def test_visual_followup_is_parent_bound_and_cannot_leak_a_hidden_trace():
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    tasks = _source("web/chat_tasks.py")
    routes = _source("web/routes/planning_routes.py")

    assert "const followupRequestId" in chat
    assert "parentRequestId" in chat
    assert "followupKey" in chat
    assert "_cancelVisualFollowups" in chat
    assert "const _ssFingerprint" in chat
    assert "if (isInternalFollowup)" in chat
    assert "saveSessionMessage('thinking'" in chat
    assert "if (!isInternalFollowup)" in chat
    assert "linked_internal_followup" in tasks
    assert "not linked to the active parent task" in tasks
    assert '"internal_followup": True' in _source("agent_runtime/chat_workflows.py")
    assert '"message": "Visual screenshot analysis follow-up"' in _source("agent_runtime/chat_workflows.py")
    assert "if not internal_followup:\n            add_step(\"user\"" in _source("agent_runtime/chat_workflows.py")
    assert "context.urlKeys" in _source("web/app/static/js/brachybot-ui-api.js")
    assert "dataset.attachmentUrl" in _source("web/app/static/js/brachybot-chat-core.js")
    assert '"parent_request_id"' in tasks
    assert "public_message =" in tasks
    assert "durable_request_id" in routes
    assert "visual-analysis-" in routes
    assert "trace_for_snapshot" in routes
    assert "visual_read_only_tools" in _source("agent_runtime/llm_runtime.py")
    visual_filter = _source("agent_runtime/llm_runtime.py").split(
        "if internal_followup and tools_for_llm is not None:", 1
    )[1].split("# The local turn policy", 1)[0]
    assert '"ui_screenshot"' not in visual_filter
    assert '"ui_content"' not in visual_filter
    workflow_source = _source("agent_runtime/chat_workflows.py")
    assert "visual_analysis_policy()" in workflow_source
    assert "if not internal_followup and local_policy.intent == \"session_content_query\":" in workflow_source
    assert "_stripVisualAttachmentEchoes" in chat
    assert "const visualContext" in chat
    assert "visual_context: isInternalFollowup" in chat
    assert "Visual evidence analysis follow-up." in chat
    assert "opts.sessionId || activeSessionId" in chat
    assert "build_visual_evidence_prompt" in routes
    assert "normalize_visual_evidence_context" in routes


def test_typed_visual_evidence_context_is_bound_to_the_current_session():
    """A visual child can only read evidence owned by its active workspace."""
    session_id = "a" * 32
    raw_context = {
        "version": 1,
        "evidence_urls": [
            f"/api/sessions/{session_id}/screenshots/dose-overview.png",
            f"/api/sessions/{session_id}/screenshots/dvh.png",
        ],
        "parent_request": "打开最后一张截图，解读当前剂量结果",
        "attachment_labels": ["剂量分布", "DVH 曲线"],
    }

    context = normalize_visual_evidence_context(raw_context, session_id)

    assert context is not None
    assert context["evidence_urls"] == raw_context["evidence_urls"]
    prompt = build_visual_evidence_prompt(context, "zh-CN")
    assert VISUAL_EVIDENCE_PROTOCOL_MARKER in prompt
    assert raw_context["parent_request"] in prompt
    assert "Use Chinese for every user-visible sentence" in prompt
    assert normalize_visual_evidence_context(raw_context, "b" * 32) is None


def test_compacted_visual_child_stops_before_a_later_real_user_turn():
    """An interrupted legacy child must not erase or steer the next question."""
    summary = (
        f"User: {VISUAL_EVIDENCE_PROTOCOL_MARKER}\n"
        "[Screenshot captured: /api/sessions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/screenshots/dose.png]\n"
        "User request: 打开最后一张截图，解读\n"
        "Analyze the supplied screenshot(s) and answer the user's request directly.\n"
        "Do not request another screenshot.\n"
        "User: 你还可以做什么"
    )

    cleaned = ChatWorkflowMixin._strip_internal_visual_context_text(summary)

    assert "打开最后一张截图" not in cleaned
    assert "Screenshot captured" not in cleaned
    assert "你还可以做什么" in cleaned


def test_compacted_visual_followup_protocol_is_removed_without_erasing_real_context():
    summary = (
        "Previous conversation summary:\n"
        "User: 请帮我查看当前病例\n"
        "User: [Screenshot captured: /api/sessions/case/screenshots/dose.png]\n"
        "Analyze the supplied screenshot(s) and answer the user's request directly.\n"
        "Do not request another screenshot.\n"
        "Assistant: 已完成剂量分析。"
    )

    cleaned = ChatWorkflowMixin._strip_internal_visual_context_text(summary)

    assert "请帮我查看当前病例" in cleaned
    assert "已完成剂量分析" in cleaned
    assert "Screenshot captured" not in cleaned
    assert "Analyze the supplied screenshot" not in cleaned
    assert "Do not request another screenshot" not in cleaned


def test_compacted_visual_followup_removes_the_embedded_parent_request_too():
    """An old partial cleanup must not leave a stale command for the next turn."""
    summary = (
        "User: [Screenshot captured: /api/sessions/case/screenshots/dose.png]\n"
        "User request: 打开最后一张截图，解读\n"
        "Use Chinese for every user-visible sentence.\n"
        "Do not repeat attachment titles or standalone viewer labels in the answer.\n"
        "Assistant: 已完成剂量分析。\n"
        "User: 你还可以做什么"
    )

    cleaned = ChatWorkflowMixin._strip_internal_visual_context_text(summary)

    assert "打开最后一张截图" not in cleaned
    assert "Do not repeat attachment" not in cleaned
    assert "已完成剂量分析" in cleaned
    assert "你还可以做什么" in cleaned


def test_report_chat_and_monitor_capture_paths_remain_separate():
    tool = _source("tool_factory/ui_screenshot/__init__.py")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    report = _source("web/app/static/js/brachybot-report-editor.js")

    assert 'SCREENSHOT_MODES = ("chat", "monitor", "report")' in tool
    assert "mode !== 'report'" in ui_api
    assert "_captureDoseOverviewDataUrl" in ui_api
    assert "_autoCaptureReportFiguresImpl" in report


def test_report_generation_executes_and_persists_the_full_report_transaction():
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    shell = _source("web/app/static/js/brachybot-report-shell.js")

    # Both SSE and plain-JSON transports execute the browser-owned action.
    assert "async function _executeJsonUIActions" in chat
    assert "await _executeJsonUIActions(data?.steps" in chat
    assert "function _hasReportGenerationAction" in chat
    assert "uiActionResults" in chat
    assert "_reportGenerationFailureMessage" in chat

    # Session switches make a report action fail instead of silently succeeding.
    assert "result.success === false || result.stale === true" in ui_api
    assert "result?.success === false" in chat
    assert "result?.stale === true" in chat
    assert "Report.autoFill.fromAll({ sessionId: ownerSessionId })" in ui_api

    # Text, tables, canonical figures, and the durable workspace snapshot are
    # one awaited transaction before the final assistant reply is rendered.
    assert "planningId: expectedPlanningId" in shell
    assert "persist.flush();" in shell
    assert "await window.persistWorkspace('report.autofill.completed')" in shell
    assert "success: true" in shell
    assert "The report form is unavailable." in shell


def test_report_chat_target_reads_session_owned_figure_artifacts_not_the_report_dom():
    tool = _source("tool_factory/ui_screenshot/__init__.py")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")

    assert '"report": "Persisted report figures"' in tool
    assert 'if views == ["report"]' in tool
    assert "function _safePersistedReportFigureUrl" in ui_api
    assert "function _appendPersistedReportFigures" in ui_api
    assert "function _reportFiguresFromArtifactCatalog" in ui_api
    assert "await hydrateDataTreeArtifactCatalog()" in ui_api
    assert "source: 'report_artifact'" in ui_api
    assert "report_figures_unavailable" in ui_api
    assert "const reportViews = plan.views.filter" in ui_api
    assert "const captureViews = plan.views.filter" in ui_api


def test_user_visible_screenshot_language_prefers_request_language_over_global_ui():
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    chat = _source("web/app/static/js/brachybot-chat-todo.js")
    language_block = ui_api.split("function _screenshotLanguage", 1)[1].split(
        "function _localizedScreenshotText", 1
    )[0]

    assert "function _screenshotLanguage(sessionId, preferredLanguage = '')" in ui_api
    assert "const raw = preferredLanguage" in language_block
    assert language_block.index("const raw = preferredLanguage") < language_block.index("|| window._i18nLang")
    assert "responseLanguage: turnIdentity.responseLanguage" in chat
    assert "response_language: turnIdentity.responseLanguage" in chat
    assert "conversationLanguageForSession(turnSessionId)" in chat
    assert "trace_summary_i18n" in _source("tool_factory/ui_screenshot/__init__.py")


def test_agent_reply_language_is_not_overridden_by_the_global_ui_locale():
    runtime = _source("agent_runtime/llm_runtime.py")
    workflows = _source("agent_runtime/chat_workflows.py")

    assert "_lang_detect(message, explicit=_ui_lang)" not in runtime
    assert "_lang_detect(message, explicit=_ui_lang)" not in workflows
    assert "UI locale is presentation state, not an instruction to translate" in runtime
    assert "global UI locale controls static controls and reports" in workflows
