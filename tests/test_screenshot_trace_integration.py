from pathlib import Path

from agent_runtime.llm_runtime import _collect_tool_fallback_text
from agent_runtime.response_tools import ResponseToolMixin
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


def test_screenshot_failure_is_persisted_on_the_owning_reply():
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")

    failure_start = ui_api.index("function _renderScreenshotFailure")
    failure_end = ui_api.index("async function _interceptScreenshot(", failure_start)
    failure_source = ui_api[failure_start:failure_end]
    assert "saveSessionMessage(" in failure_source
    assert "requestId: context.requestId" in failure_source
    assert "messageId: context.messageId" in failure_source


def test_report_chat_and_monitor_capture_paths_remain_separate():
    tool = _source("tool_factory/ui_screenshot/__init__.py")
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    report = _source("web/app/static/js/brachybot-report-editor.js")

    assert 'SCREENSHOT_MODES = ("chat", "monitor", "report")' in tool
    assert "mode !== 'report'" in ui_api
    assert "_captureDoseOverviewDataUrl" in ui_api
    assert "_autoCaptureReportFiguresImpl" in report


def test_user_visible_screenshot_language_prefers_global_ui_language():
    ui_api = _source("web/app/static/js/brachybot-ui-api.js")
    chat = _source("web/app/static/js/brachybot-chat-todo.js")

    assert "const raw = window._i18nLang || (" in ui_api
    assert "response_language: window._i18nLang || (" in chat
    assert "trace_summary_i18n" in _source("tool_factory/ui_screenshot/__init__.py")
