import json
from pathlib import Path

import pytest

from agent_runtime.chat_workflows import ChatWorkflowMixin
from agent_runtime.llm_runtime import _collect_tool_fallback_text
from agent_runtime.core import ToolResultPipeline
from agent_runtime.response_tools import ResponseToolMixin
from agent_runtime.turn_policy import (
    classify_local_turn,
    resolve_session_content_presentation,
    resolve_session_content_target,
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


def test_report_chat_and_monitor_capture_paths_remain_separate():
    tool = _source("tool_factory/ui_screenshot/__init__.py")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    report = _source("web/app/static/js/brachybot-report-editor.js")

    assert 'SCREENSHOT_MODES = ("chat", "monitor", "report")' in tool
    assert "mode !== 'report'" in ui_api
    assert "_captureDoseOverviewDataUrl" in ui_api
    assert "_autoCaptureReportFiguresImpl" in report


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
