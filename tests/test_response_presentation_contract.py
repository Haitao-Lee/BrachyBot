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
    assert mixed.act == "mixed"
    assert mixed.text_required is True
    assert command.act == "command"
    assert command.text_required is True
    assert command.presentation_mode == "status_with_evidence"


def test_presentation_fallback_is_typed_and_language_matched():
    presentation_fallback_message = _response_contract_module().presentation_fallback_message

    zh = presentation_fallback_message("zh", "生成结果在哪里？", ["ui_screenshot"])
    en = presentation_fallback_message("en", "Where is the generated result?", ["ui_screenshot"])

    assert "Viewer/Data Tree" in zh
    assert "截图" in zh
    assert "Viewer/Data Tree" in en
    assert "screenshot" in en.lower()


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

    assert "function _captureDataTreeEvidenceDataUrl" in ui_api
    assert "data-tree-evidence-capture" in ui_api
    assert "Surgical-guide-related nodes were located automatically" in ui_api
    assert "scale: 2" in ui_api
    assert "function _snapshotDataTreeUiState" in ui_api
    assert "function _restoreDataTreeUiState" in ui_api
    assert "_restoreDataTreeUiState(snapshot.dataTree)" in ui_api
    assert "data_tree_node_ids: [...new Set" in ui_api
