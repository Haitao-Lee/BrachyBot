from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_free_text_planning_assessment_uses_normal_chat_grounded_response_path():
    chat = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    routes = (ROOT / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    assert "requestPlanningAdvice({ question: text, conversational: true })" not in chat
    assert "function _isAdviceRequest" not in chat
    assert "Natural-language planning questions must continue through the normal" in chat
    assert "payload.natural_language = true" in manual
    assert "const naturalResponse = String(data.natural_response || '').trim();" in manual
    assert "answerer(question, \"planning_assessment_query\", language)" in routes
    assert 'response["natural_response"]' in routes


def test_assessment_language_is_consistent_for_toolbar_fallback():
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    assert "_formatAdviceReport(advice, prefix, language)" in manual
    assert "const prefix = language === 'zh'" in manual


def test_natural_language_assessment_is_read_only_local_intent():
    from agent_runtime.turn_policy import classify_local_turn

    for text in (
        "评价一下当前规划结果",
        "请评价一下当前规划结果",
        "evaluate the current plan",
        "give advice on the current plan",
    ):
        policy = classify_local_turn(text)
        assert policy.intent == "planning_assessment_query", (text, policy)
        assert not policy.direct_execution, (text, policy)
