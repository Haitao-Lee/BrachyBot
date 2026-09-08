"""Regression tests for the user-visible error boundary."""

from agent_runtime.chat_workflows import ChatWorkflowMixin
from agent_runtime.core import ToolResultPipeline
from tool_factory import ToolResult
from utils.user_errors import sanitize_user_response


def test_tool_result_normalizes_malformed_metadata_and_formats_ctv_failure():
    result = ToolResult(
        success=False,
        error="'list' object has no attribute 'get'",
        metadata=["adapter output should be a mapping"],
    )
    assert isinstance(result.metadata, dict)
    assert result.metadata["_metadata_contract_error"] is True

    message = ToolResultPipeline.format("ctv_segmentation", result, "zh")
    assert "CTV 分割" in message
    assert "attribute" not in message.lower()
    assert "list' object" not in message.lower()
    assert "重新执行" in message or "重新" in message


def test_provider_diagnostics_are_not_user_visible():
    raw = (
        "⚠️ Error: Error code: 400 - {'type': 'error', "
        "'message': 'Request is missing x-opencode-session'}"
    )
    assert ChatWorkflowMixin._is_llm_provider_error(raw)
    message = sanitize_user_response(raw, lang="zh")
    assert "MissingSessionID" not in message
    assert "x-opencode-session" not in message
    assert "Error code" not in message
    assert "AI 语言服务" in message


def test_small_talk_has_a_local_fallback_when_the_provider_is_down():
    message = ChatWorkflowMixin._small_talk_fallback_response("你好", "zh")
    assert message.startswith("你好！")
    assert "AI 语言服务" not in message
    assert "规划" in message


def test_raw_tool_failure_is_sanitized_in_fallback_trace():
    steps = [{
        "type": "tool",
        "tool": "ctv_segmentation",
        "status": "error",
        "result": "'list' object has no attribute 'get'",
    }]
    message = ToolResultPipeline.format_steps(steps, "zh")
    assert "attribute" not in message.lower()
    assert "list' object" not in message.lower()
    assert "请" in message


if __name__ == "__main__":
    test_tool_result_normalizes_malformed_metadata_and_formats_ctv_failure()
    test_provider_diagnostics_are_not_user_visible()
    test_raw_tool_failure_is_sanitized_in_fallback_trace()
    print("test_user_error_contract: PASS")
