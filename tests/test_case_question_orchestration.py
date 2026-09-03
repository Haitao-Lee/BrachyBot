"""Regression tests for history-aware case questions and bounded LLM turns."""

from types import SimpleNamespace


def test_parameter_comparison_is_a_read_only_case_question_not_semantic_tool_loop():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn(
        "为什么规划结果是一样的，我改了参数呀，这两次规划参数不一样啊"
    )

    assert policy.intent == "case_state_question"
    assert policy.use_router is False
    assert policy.use_completeness is False
    assert policy.allow_tools == frozenset()


def test_rl_failure_reason_is_a_history_read_with_diagnostic_contract():
    from agent_runtime.turn_policy import classify_local_turn

    policy = classify_local_turn("所以可以检测到之前那次规划RL失败的原因吗")

    assert policy.intent == "case_state_question"
    assert policy.use_router is False
    assert policy.allow_tools == frozenset()


class _Memory:
    def __init__(self, values):
        self.values = dict(values)

    def retrieve(self, key, default=None):
        return self.values.get(key, default)


def _comparison_agent():
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    old_id = "planning-old"
    new_id = "planning-new"
    runs = [
        {
            "planning_id": old_id,
            "sequence": 0,
            "label": "Planning_1",
            "status": "completed",
            "visible": False,
            "data_version": 1,
            "total_seeds": 32,
            "num_trajectories": 8,
            "input_revision": {
                "mode": "rl",
                "planning_fingerprint": "fp-old",
                "planning_parameters": {"max_iter": 4},
            },
        },
        {
            "planning_id": new_id,
            "sequence": 1,
            "label": "Planning_2",
            "status": "completed",
            "visible": True,
            "data_version": 2,
            "total_seeds": 32,
            "num_trajectories": 8,
            "input_revision": {
                "mode": "rule_based",
                "planning_fingerprint": "fp-new",
                "planning_parameters": {"max_iter": 4},
            },
        },
    ]
    snapshots = {
        "planning_run:" + old_id: {
            "plan_config": {
                "mode": "rl",
                "requested_mode": "rl",
                "effective_mode": "rule_based_fallback",
                "rl_fallback_used": True,
                "planning_fingerprint": "fp-old",
                "planning_parameters": {"max_iter": 4, "replan_rate": 0.6},
                "rl_status": {
                    "schema_version": 1,
                    "execution": "completed",
                    "stop_reason": "wall_clock_budget",
                    "target_coverage": 0.90,
                    "best_coverage": 0.394,
                    "best_reward": 0.394,
                    "episodes_completed": 2,
                    "high_level_episodes": 1,
                    "low_level_episodes": 1,
                    "actions_taken": 24,
                    "dense_trajectories_completed": 8,
                    "dense_seed_candidates": 32,
                    "elapsed_seconds": 180.0,
                    "dose_cache_hits": 4,
                    "dose_cache_misses": 12,
                    "_execution": "must_not_escape",
                },
            },
            "total_seeds": 32,
            "num_trajectories": 8,
            "dose_metrics": {"v100": 0.394, "d90": 9.56, "plan_score": 44.32},
        },
        "planning_run:" + new_id: {
            "plan_config": {
                "mode": "rule_based",
                "requested_mode": "rule_based",
                "effective_mode": "rule_based",
                "rl_fallback_used": False,
                "planning_fingerprint": "fp-new",
                "planning_parameters": {"max_iter": 4, "replan_rate": 0.6},
            },
            "total_seeds": 32,
            "num_trajectories": 8,
            "dose_metrics": {"v100": 0.394, "d90": 9.56, "plan_score": 44.32},
        },
    }
    values = {
        "active_planning_id": new_id,
        "planning_run_id": new_id,
        "planning_runs": runs,
        "plan_config": snapshots["planning_run:" + new_id]["plan_config"],
        "dose_metrics": snapshots["planning_run:" + new_id]["dose_metrics"],
    }
    values.update(snapshots)
    memory = _Memory(values)
    agent = object.__new__(ChatWorkflowMixin)
    agent.memory = memory
    return agent


def test_case_question_packet_contains_both_auditable_runs_without_paths_or_arrays():
    import json

    agent = _comparison_agent()
    packet = agent._current_planning_fact_packet("case_state_question")
    history = packet["planning_history"]

    assert [row["label"] for row in history] == ["Planning_1", "Planning_2"]
    assert history[0]["requested_mode"] == "rl"
    assert history[0]["effective_mode"] == "rule_based_fallback"
    assert history[0]["effective_algorithm_family"] == "rule_based"
    assert history[1]["requested_mode"] == "rule_based"
    assert history[1]["effective_algorithm_family"] == "rule_based"
    assert history[0]["planning_fingerprint"] != history[1]["planning_fingerprint"]
    assert history[0]["rl_status"]["stop_reason"] == "wall_clock_budget"
    assert "_execution" not in history[0]["rl_status"]
    assert packet["comparison"] == {
        "available": True,
        "run_count": 2,
        "active_planning_id": "planning-new",
    }
    encoded = json.dumps(packet, ensure_ascii=False, default=str)
    assert "ct_path" not in encoded
    assert "dose_distribution" not in encoded


def test_case_question_uses_one_grounded_llm_answer_and_no_tools():
    agent = _comparison_agent()
    calls = []

    class Router:
        def chat_messages(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=(
                    "两次 Planning 的请求模式和实际生效模式不同，指纹也不同；但保存的针道、粒子数和 V100/D90 指标相同。"
                    "现有快照只能确认输入配置不同且输出相同，不能单独证明是缓存还是算法得到相同结果；还需要核对执行日志。"
                ),
                finish_reason="stop",
                usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                model="test-model",
            )

    agent.brain_router = Router()
    answer, meta = agent._answer_local_read_query(
        "为什么规划结果是一样的，我改了参数呀，这两次规划参数不一样啊",
        "case_state_question",
        "zh",
    )

    assert len(calls) == 1
    assert calls[0]["tools"] is None
    assert meta["llm_calls"] == 1
    assert meta["route"] == "grounded_local_llm"
    assert "不能单独证明" in answer


def test_irrelevant_current_metrics_answer_is_rejected_for_comparison_question():
    agent = _comparison_agent()

    class Router:
        def chat_messages(self, **kwargs):
            return SimpleNamespace(
                content="当前病例 V100 为 39.4%，D90 为 9.56 Gy。",
                finish_reason="stop",
                usage={},
                model="test-model",
            )

    agent.brain_router = Router()
    answer, meta = agent._answer_local_read_query(
        "为什么规划结果是一样的，我改了参数呀，这两次规划参数不一样啊",
        "case_state_question",
        "zh",
    )

    assert meta["llm_calls"] == 1
    assert meta["route"] == "grounded_local_fallback"
    assert "Planning_1" in answer
    assert "Planning_2" in answer
    assert "参数差异" in answer or "指纹差异" in answer


def test_rl_failure_question_uses_persisted_status_in_fallback():
    agent = _comparison_agent()

    answer, meta = agent._answer_local_read_query(
        "所以可以检测到之前那次规划RL失败的原因吗",
        "case_state_question",
        "zh",
    )

    assert meta["route"] == "grounded_local_fallback"
    assert "wall_clock_budget" in answer
    assert "达到墙钟时间预算" in answer
    assert "0.394" in answer
    assert "剂量缓存命中" in answer


def test_followup_prompt_keeps_only_complete_recent_tool_rounds():
    from agent_runtime.llm_runtime import _bound_followup_messages

    base = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "current question"},
    ]
    dynamic = []
    for index in range(3):
        call_id = f"call-{index}"
        dynamic.extend([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "query_metrics", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": call_id, "content": "x" * 5000},
            {"role": "user", "content": f"synthesize round {index}"},
        ])

    bounded = _bound_followup_messages(base + dynamic, len(base), max_tool_rounds=2)

    assert bounded[:2] == base
    assert len([item for item in bounded if item.get("role") == "tool"]) == 2
    assert all(len(item["content"]) <= 2400 for item in bounded if item.get("role") == "tool")
    assert "call-0" not in str(bounded)
    assert "call-1" in str(bounded)
    assert "call-2" in str(bounded)
