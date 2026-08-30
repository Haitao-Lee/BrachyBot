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


def test_dose_result_language_is_read_only_but_recalculation_stays_mutating():
    from agent_runtime.turn_policy import _is_current_case_dose_query, classify_local_turn

    read_request = "现在计算的剂量结果中，CTV的几个关键指标是多少"
    assert _is_current_case_dose_query(read_request) is True
    policy = classify_local_turn(read_request)
    assert policy.intent == "case_dose_query"
    assert policy.use_router is False
    assert policy.use_completeness is False

    for mutation in (
        "请重新计算剂量",
        "现在我改了针和粒子的位置，请重新计算剂量",
        "Please recalculate the dose now",
    ):
        assert _is_current_case_dose_query(mutation) is False


def test_planning_provenance_followup_is_localized_read_only_and_never_replans():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from agent_runtime.turn_policy import classify_local_turn

    message = "本次计算是以哪次规划结果为依据的呢"
    policy = classify_local_turn(message)
    assert policy.intent == "planning_provenance_query"
    assert policy.use_router is False
    assert policy.use_completeness is False
    assert policy.direct_execution is False

    class Memory:
        def __init__(self):
            self.values = {
                "active_planning_id": "planning-4",
                "planning_run_id": "planning-4",
                "planning_runs": [{
                    "planning_id": "planning-4",
                    "sequence": 3,
                    "label": "Planning_4",
                    "status": "completed",
                    "visible": True,
                    "data_version": 7,
                }],
                "planning_run:planning-4": {
                    "total_seeds": 54,
                    "num_trajectories": 8,
                    "dose_recompute_provenance": {
                        "operation": "dose_recompute",
                        "planning_id": "planning-4",
                        "planning_label": "Planning_4",
                        "planning_status": "completed",
                        "source": "active_planning_run",
                        "used_saved_geometry": True,
                        "reran_segmentation": False,
                        "reran_trajectory_selection": False,
                        "reran_planning_pipeline": False,
                        "total_seeds": 54,
                        "num_trajectories": 8,
                    },
                },
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

    workflow = object.__new__(ChatWorkflowMixin)
    workflow.memory = Memory()
    response = workflow._build_current_planning_provenance_response("zh")

    assert "Planning_4" in response
    assert "planning-4" in response
    assert "8 个针道、54 个粒子" in response
    assert "没有重新进行分割" in response
    assert "I can help with brachytherapy planning" not in response


def test_current_planning_assessment_is_not_misclassified_as_provenance():
    from agent_runtime.turn_policy import (
        classify_local_turn,
        is_current_planning_assessment_query,
        is_current_planning_provenance_query,
    )

    message = "你好，当前规划有什么问题吗"
    policy = classify_local_turn(message)

    assert is_current_planning_provenance_query(message) is False
    assert is_current_planning_assessment_query(message) is True
    assert policy.intent == "planning_assessment_query"
    assert policy.use_router is False
    assert policy.direct_execution is False


def test_unavailable_provider_never_turns_semantic_question_into_keyword_action_or_english_menu():
    from agent_runtime.chat_workflows import ChatWorkflowMixin
    from agent_runtime.turn_policy import classify_local_turn

    message = "本次计算是以哪次规划结果为依据的呢"

    class Memory:
        user_lang = "zh"

    workflow = object.__new__(ChatWorkflowMixin)
    workflow.memory = Memory()
    workflow._active_turn_policy = classify_local_turn(message)

    response = workflow._rule_based_chat(message)
    assert "I can help with brachytherapy planning" not in response
    assert "没有启动任何临床操作" in response

    legacy_menu = (
        "I can help with brachytherapy planning. Try:\n"
        "  - 'Segment CTV' - Segment CTV\n"
        "  - 'Generate plan' - Generate treatment plan\n"
        "  - 'Evaluate dose' - Evaluate dose distribution\n"
        "  - 'Optimize plan' - Optimize treatment plan\n"
        "  - 'Self-evolve' - Trigger self-evolution\n"
        "  - 'Create tool' - Create new tool"
    )
    normalized = workflow._normalize_user_facing_response(message, legacy_menu)
    assert "I can help with brachytherapy planning" not in normalized
    assert "没有可靠识别出" in normalized


def test_english_planning_provenance_question_uses_the_same_local_read_route():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn("Which planning result was this dose recomputation based on?")
    assert policy.intent == "planning_provenance_query"
    assert policy.use_router is False


def test_streaming_entrypoint_answers_provenance_through_grounded_llm_when_available():
    import json
    import threading
    from types import SimpleNamespace

    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Memory:
        def __init__(self):
            self._lock = threading.RLock()
            self.context_summary = ""
            self.conversation = []
            self.user_lang = "zh"
            self.values = {
                "active_planning_id": "planning-4",
                "planning_run_id": "planning-4",
                "planning_runs": [{
                    "planning_id": "planning-4",
                    "sequence": 3,
                    "label": "Planning_4",
                    "status": "completed",
                    "visible": True,
                }],
                "planning_run:planning-4": {
                    "total_seeds": 54,
                    "num_trajectories": 8,
                    "dose_recompute_provenance": {
                        "planning_id": "planning-4",
                        "planning_label": "Planning_4",
                        "planning_status": "completed",
                        "source": "active_planning_run",
                        "total_seeds": 54,
                        "num_trajectories": 8,
                    },
                },
            }

        def retrieve(self, key, default=None):
            return self.values.get(key, default)

        def add_message(self, role, content):
            self.conversation.append({"role": role, "content": content})

    workflow = object.__new__(ChatWorkflowMixin)
    workflow.memory = Memory()
    workflow.multi_agent_wrapper = None
    workflow.enhanced = None
    calls = []

    class Router:
        def chat_messages(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content="当前重算依据的是 Planning_4；这是从当前 Session 读取到的规划来源。",
                usage={"prompt_tokens": 10, "completion_tokens": 12},
                finish_reason="stop",
                model="test-grounded-router",
            )

    workflow.brain_router = Router()
    workflow.brain_available = True
    workflow.exp_memory = None
    workflow._active_turn_context = {}
    workflow._pending_tumor_site_clarification = lambda: False

    events = list(workflow._chat_with_stream_impl("本次计算是以哪次规划结果为依据的呢"))
    response_events = [
        json.loads(event.split("data: ", 1)[1])
        for event in events
        if event.startswith("event: response\n")
    ]

    assert len(response_events) == 1
    assert response_events[0]["llm_meta"]["route"] == "grounded_local_llm"
    assert response_events[0]["llm_meta"]["llm_calls"] == 1
    assert "Planning_4" in response_events[0]["response"]
    assert "planning_pipeline" not in response_events[0]["response"]
    assert "I can help with brachytherapy planning" not in response_events[0]["response"]
    assert len(calls) == 1
    assert calls[0]["tools"] is None
    assert "本次计算是以哪次规划结果为依据的呢" in calls[0]["messages"][1]["content"]
    assert "FACTS JSON" in calls[0]["messages"][1]["content"]


def test_query_metrics_exposes_typed_direct_read_contract_and_localized_table():
    from agent_runtime.core import ToolResultPipeline
    from tool_factory.viewer_command.query_metrics import QueryMetricsTool

    result = QueryMetricsTool()._execute(
        metric_type="dose_metrics",
        metrics={
            "v100": 0.9143,
            "v150": 0.6584,
            "v200": 0.4489,
            "d90": 122.54,
            "d95": 100.10,
            "dmean": 416.67,
            "d2": 4292.90,
            "dmax": 4780.30,
            "ci": 0.836,
            "hi": 38.8,
            "plan_score": 83.08,
            "prescription_gy": 120.0,
        },
    )

    assert result.success is True
    contract = result.metadata["response_contract"]
    assert contract["mode"] == "direct_read"
    assert contract["source"] == "active_session"
    assert ToolResultPipeline.direct_read_contract(result) == contract

    rendered = ToolResultPipeline.format("query_metrics", result, "zh")
    assert "当前病例剂量指标" in rendered
    assert "V100" in rendered and "91.43%" in rendered
    assert "D95" in rendered and "Dmax" in rendered
    assert "{\"V100\"" not in rendered


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
