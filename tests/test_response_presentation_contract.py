"""Regression tests for the text-plus-evidence response contract."""

from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]


def _response_contract_module():
    """Load the stdlib-only policy module without importing heavy agent deps."""
    path = ROOT / "agent_runtime" / "response_contract.py"
    spec = importlib.util.spec_from_file_location("response_contract_test_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_question_and_mixed_turns_require_text_without_answer_whitelists():
    build_response_contract = _response_contract_module().build_response_contract

    question = build_response_contract("生成结果在哪里")
    mixed = build_response_contract("请显示结果，为什么刚才没有加载出来？")
    command = build_response_contract("请把当前规划显示在 Viewer 中")

    assert question.act == "question"
    assert question.text_required is True
    assert question.evidence_supplemental is True
    assert question.presentation_mode == "explain_with_evidence"
    visual_question = build_response_contract("\u6709\u6ca1\u6709\u56fe\u8bf4\u660e\u4e00\u4e0b")
    assert visual_question.act == "question"
    assert visual_question.text_required is True
    assert visual_question.presentation_mode == "explain_with_evidence"
    assert mixed.act == "mixed"
    assert mixed.text_required is True
    assert command.act == "command"
    assert command.text_required is True
    assert command.presentation_mode == "status_with_evidence"


def test_screenshot_and_inform_demands_the_explanation_not_attachment_only():
    """"截图告知" asks for the content that belongs to the evidence.

    Treating it as a pure capture command let the turn end as an attachment
    gallery (or a stale fallback) with no explanation of what the images show.
    """
    build_response_contract = _response_contract_module().build_response_contract

    inform = build_response_contract("截图告知")
    assert inform.act == "mixed"
    assert inform.text_required is True
    assert inform.evidence_supplemental is True
    assert inform.presentation_mode == "explain_with_evidence"

    pure_capture = build_response_contract("截图")
    assert pure_capture.act == "command"
    assert pure_capture.evidence_supplemental is False


def test_successful_capture_fallback_acknowledges_instead_of_failing_the_turn():
    import importlib

    llm = importlib.import_module("agent_runtime.llm_runtime")
    fallback = llm._presentation_capture_fallback

    capture_steps = [
        {"type": "tool", "tool": "ui_inspector", "status": "done", "result": "Getting current UI state"},
        {
            "type": "tool",
            "tool": "ui_screenshot",
            "status": "done",
            "result": "已创建截图计划，正在捕获目标视图。",
            "metadata": {"internal_only": True, "user_visible": False},
        },
    ]

    # The deliberate capture stop plus read-only helpers must acknowledge the
    # capture, never report "本轮未能完成" for a plan that succeeded.
    pending = fallback("zh", capture_steps, "截图告知", capture_pending=True)
    assert "本轮已发起截图请求" in pending
    assert "未能完成" not in pending

    # The same holds when the turn's tools are all presentation helpers.
    helper_only = fallback("zh", capture_steps, "截图告知")
    assert "本轮已发起截图请求" in helper_only

    # A failed capture and a mixed clinical turn fall back to the normal
    # result collection instead of a capture acknowledgement.
    failed = [{**capture_steps[0]}, {**capture_steps[1], "status": "error"}]
    assert fallback("zh", failed, "截图告知", capture_pending=True) is None
    mixed_tools = capture_steps + [
        {"type": "tool", "tool": "query_metrics", "status": "done", "result": "V100"},
    ]
    assert fallback("zh", mixed_tools, "截图告知") is None


def test_presentation_fallback_is_typed_and_language_matched():
    presentation_fallback_message = _response_contract_module().presentation_fallback_message

    zh = presentation_fallback_message("zh", "生成结果在哪里？", ["ui_screenshot"])
    en = presentation_fallback_message("en", "Where is the generated result?", ["ui_screenshot"])

    assert "\u622a\u56fe\u8bf7\u6c42" in zh
    assert "\u6210\u529f\u6355\u83b7\u6216\u9644\u52a0" in zh
    assert "\u4fdd\u7559" not in zh
    assert "截图" in zh
    assert "screenshot was requested" in en.lower()
    assert "screenshot" in en.lower()
    assert "confirm a successful capture" in en.lower()
    assert "preserved" not in en.lower()


def test_server_and_browser_preserve_text_for_screenshot_questions():
    llm = (ROOT / "agent_runtime" / "llm_runtime.py").read_text(encoding="utf-8")
    chat = (ROOT / "agent_runtime" / "chat_workflows.py").read_text(encoding="utf-8")
    todo = (ROOT / "web" / "app" / "static" / "js" / "brachybot-chat-todo.js").read_text(encoding="utf-8")
    prompt = (ROOT / "config" / "prompts" / "system_prompt.md").read_text(encoding="utf-8")

    assert "response_presentation_instruction(response_contract)" in llm
    assert '"response_contract": response_contract.as_dict()' in llm
    assert "presentation_fallback_message" in chat
    assert "responseContract.text_required === true" in todo
    assert "const visualAnalysisContinuation = shouldAnalyzeVisualEvidence" in todo
    assert "suppressScreenshotAck = visualAnalysisContinuation" in todo
    assert "Never leave an empty assistant bubble" in prompt
    assert "_ui_screenshot_turn_response" not in llm


def test_data_tree_evidence_capture_is_focused_readable_and_restored():
    ui_api = (ROOT / "web" / "app" / "static" / "js" / "brachybot-ui-api.js").read_text(encoding="utf-8")

    # Evidence must come from the actual visible Data Tree, not an off-screen
    # synthetic card that loses the node's real hierarchy and interaction state.
    assert "function _captureDataTreeEvidenceDataUrl" in ui_api
    assert "function _prepareLiveDataTreeForScreenshot" in ui_api
    assert "function _captureDataTreeEvidenceBundle" in ui_api
    assert "locator: 'live-data-tree-dom'" in ui_api
    assert "captured_from_live_dom: true" in ui_api
    assert "capture_surface: 'live-application-dom'" in ui_api
    assert "data-tree-evidence-capture" not in ui_api
    assert "scale: 2" in ui_api
    assert "function _snapshotDataTreeUiState" in ui_api
    assert "function _restoreDataTreeUiState" in ui_api
    assert "_restoreDataTreeUiState(treeSnapshot)" in ui_api
    assert "originalContainerStyle" in ui_api
    assert "ui_state_restored_after_capture: true" in ui_api
    assert "data_tree_node_ids: [...new Set" in ui_api
