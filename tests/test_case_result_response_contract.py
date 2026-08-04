from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_external_evidence_cannot_be_promoted_to_chat_fallback():
    from agent_runtime.llm_runtime import _collect_tool_fallback_text

    successes, failures = _collect_tool_fallback_text(
        [{
            "type": "tool",
            "tool": "web_fetch",
            "status": "done",
            "result": "Advertisement Ovid internal page body",
        }],
        [{"role": "tool", "content": "raw web page body and internal prompt"}],
        "zh",
    )

    assert len(successes) == 1
    assert "Advertisement" not in successes[0]
    assert "Ovid" not in successes[0]
    assert failures == []


def test_allowlisted_metrics_tool_can_supply_a_structured_fallback():
    from agent_runtime.llm_runtime import _collect_tool_fallback_text

    successes, failures = _collect_tool_fallback_text(
        [{
            "type": "tool",
            "tool": "query_metrics",
            "status": "done",
            "result": "V100=0.91; D90=120 Gy",
        }],
        [],
        "en",
    )

    assert successes == ["V100=0.91; D90=120 Gy"]
    assert failures == []


def test_current_case_dose_response_reads_saved_metrics_without_web_tools():
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Memory:
        def __init__(self):
            self.values = {
                "metrics": {
                    "v100": 0.905,
                    "v150": 0.739,
                    "v200": 0.542,
                    "d90": 123.90,
                    "dmean": 474.12,
                    "d2": 4315.77,
                    "ci": 0.819,
                    "hi": 36.617,
                    "plan_score": 80,
                    "oar_metrics": {
                        "small_bowel": {"dmax": 275.34, "d2cc": 41.94},
                    },
                },
                "plan_config": {"in_lowest_energy": 120, "out_highest_energy": 120},
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    workflow = object.__new__(ChatWorkflowMixin)
    workflow.memory = Memory()
    response = workflow._build_current_dose_response("zh")

    assert "当前病例剂量结果" in response
    assert "V100 / V150 / V200：90.5% / 73.9% / 54.2%" in response
    assert "D90 / Dmean / D2：123.90 / 474.12 / 4315.77 Gy" in response
    assert "small bowel" in response
    assert "web_fetch" not in response
    assert "Advertisement" not in response


def test_restored_turn_order_uses_request_and_explicit_sequence():
    from web.workspace_store import _merge_chat_records

    records = [
        {"id": "assistant-1", "request_id": "r1", "type": "bot-response",
         "message_kind": "assistant_final", "turn_sequence": 2, "timestamp": 300},
        {"id": "trace-1", "request_id": "r1", "type": "thinking",
         "message_kind": "execution_trace", "turn_sequence": 1, "timestamp": 200},
        {"id": "user-1", "request_id": "r1", "type": "user",
         "message_kind": "user_message", "turn_sequence": 0, "timestamp": 100},
    ]

    merged = _merge_chat_records([], records)
    assert [record["id"] for record in merged] == ["user-1", "trace-1", "assistant-1"]


def test_frontend_persists_trace_language_and_rehydrates_it_per_turn():
    core = (ROOT / "web/app/static/js/brachybot-chat-core.js").read_text(encoding="utf-8")
    todo = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")

    assert "msg.trace_language" in core
    assert "_traceStepForDisplay(step, id, traceLanguage)" in core
    assert "wrapper.dataset.traceLanguage" in core
    assert "function _traceStepForDisplay(step, sessionId, turnLanguage = '')" in todo
    assert "responseLanguage: turnIdentity.responseLanguage" in todo
