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


def test_successful_answer_with_server_path_is_redacted_not_failed():
    raw = (
        "治疗报告已重新生成。文件已保存至："
        "`/srv/brachybot/BrachyBot/tool_factory/report_generator/../output/reports/plan_20260917_115806.md`"
    )
    message = sanitize_user_response(raw, lang="zh")
    assert "治疗报告已重新生成" in message
    assert "plan_20260917_115806.md" in message
    assert "/home/" not in message
    assert "未能完成" not in message


def test_exception_text_containing_a_path_still_fails_closed():
    raw = (
        "Traceback (most recent call last):\n"
        '  File "/srv/brachybot/BrachyBot/web/server.py", line 1, in <module>\n'
        "ValueError: boom"
    )
    message = sanitize_user_response(raw, lang="zh")
    assert "未能完成" in message
    assert "/home/" not in message
    assert "Traceback" not in message


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


def test_ctv_formatter_ignores_malformed_optional_label_stats():
    cases = (
        {"pancreatic": [1, 2, 3]},
        [{"name": "pancreatic", "volume_cm3": 1.0, "centroid_world": [1, 2, 3]}],
        {"pancreatic": {"volume_cm3": 1.0}},
        3,
    )
    for label_stats in cases:
        result = ToolResult(
            success=True,
            metadata={
                "ctv_volume_mm3": 1000.0,
                "ctv_voxel_count": 8,
                "label_stats": label_stats,
            },
        )
        message = ToolResultPipeline.format("ctv_segmentation", result, "zh")
        assert "CTV 分割" in message
        assert "attribute" not in message.lower()
        assert "KeyError" not in message
        assert "结果已在查看器" in message


def test_ctv_contract_error_explains_internal_format_failure():
    message = ToolResultPipeline.format(
        "ctv_segmentation",
        ToolResult(
            success=False,
            error="'list' object has no attribute 'get'",
            metadata={"ctv_contract_error": True},
        ),
        "zh",
    )
    assert "内部校验" in message
    assert "误传到 CTV mask 入口" in message
    assert "attribute" not in message.lower()
