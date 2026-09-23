"""Routing contracts for method/provenance questions about the active plan.

The 2026-09-23 conversation regression: "刚刚完成的这个规划任务是使用的
算法是基于RL的还是规则-based的" fell through every read boundary because
``is_interrogative`` cannot see a ``是…还是…`` choice question, landed in the
broad ``semantic_action`` tool loop, and the provider answered with a
``query_metrics(all_metrics)`` dose table instead of the requested algorithm
provenance.  These contracts pin: choice questions are questions; method
wordings resolve to grounded planning provenance; the LLM can SEE the
historical execution trajectory (tool calls and their key results) instead of
having it stripped; ``query_metrics(metric_type='planning_method')`` serves
method/provenance questions so the model can fetch specifics and compose; and
the synthesis surface refuses to substitute a metrics dump for a method answer.
"""
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


INCIDENT_QUESTION = "刚刚完成的这个规划任务是使用的算法是基于RL的还是规则-based的"


class ChoiceQuestionDetectionTests(unittest.TestCase):
    def test_chinese_choice_question_is_interrogative(self):
        from agent_runtime.request_parse import is_interrogative

        self.assertTrue(is_interrogative(INCIDENT_QUESTION))
        self.assertTrue(is_interrogative("这次计划是用RL还是规则法做的"))
        self.assertTrue(is_interrogative("基于RL的还是规则-based的？"))

    def test_choice_statement_is_not_a_question(self):
        from agent_runtime.request_parse import is_interrogative

        self.assertFalse(is_interrogative("无论是规则法还是RL都可以接受。"))
        self.assertFalse(is_interrogative("我最终还是选了规则法。"))


class MethodQuestionRoutingTests(unittest.TestCase):
    def test_incident_question_routes_to_planning_provenance(self):
        from agent_runtime.turn_policy import classify_local_turn

        policy = classify_local_turn(INCIDENT_QUESTION)
        self.assertEqual(policy.intent, "planning_provenance_query")
        self.assertFalse(policy.direct_execution)
        self.assertFalse(policy.allow_tools or frozenset())

    def test_method_wording_variants_route_to_planning_provenance(self):
        from agent_runtime.turn_policy import classify_local_turn

        for message in (
            "这个规划用的什么算法？",
            "刚刚的计划是用什么方法生成的",
            "What method or algorithm produced this plan, RL or rule-based?",
            "本次规划采用的是哪种优化方式",
        ):
            with self.subTest(message=message):
                policy = classify_local_turn(message)
                self.assertEqual(policy.intent, "planning_provenance_query",
                                 message)

    def test_reexecution_request_stays_an_action(self):
        from agent_runtime.turn_policy import classify_local_turn

        policy = classify_local_turn("请重新执行放射性粒子植入规划")
        self.assertNotEqual(policy.intent, "planning_provenance_query")
        self.assertTrue(
            policy.action_plan or policy.execution_grants,
            "a re-execution request must keep its clinical action grants",
        )


class ProvenanceAnswerContentTests(unittest.TestCase):
    def test_provenance_answer_reports_the_algorithm_family(self):
        from agent_runtime.chat_workflows import ChatWorkflowMixin

        class Memory:
            user_lang = "zh"

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
                        "total_seeds": 181,
                        "num_trajectories": 24,
                        "plan_config": {
                            "requested_mode": "rl",
                            "mode": "rl",
                            "effective_mode": "rule_based_fallback",
                            "rl_fallback_used": True,
                            "rl_fallback_reason": "strict_coverage_improvement",
                            "rl_target_coverage": 0.9,
                            "rl_fallback_coverage": 0.9023,
                        },
                        "dose_recompute_provenance": {
                            "operation": "planning",
                            "planning_id": "planning-4",
                            "planning_label": "Planning_4",
                            "planning_status": "completed",
                            "source": "active_planning_run",
                            "total_seeds": 181,
                            "num_trajectories": 24,
                        },
                    },
                    "plan_config": {
                        "requested_mode": "rl",
                        "mode": "rl",
                        "effective_mode": "rule_based_fallback",
                        "rl_fallback_used": True,
                        "rl_fallback_reason": "strict_coverage_improvement",
                        "rl_target_coverage": 0.9,
                        "rl_fallback_coverage": 0.9023,
                    },
                }

            def retrieve(self, key, default=None):
                return self.values.get(key, default)

        workflow = object.__new__(ChatWorkflowMixin)
        workflow.memory = Memory()
        response = workflow._build_current_planning_provenance_response("zh")

        self.assertIn("Planning_4", response)
        self.assertIn("24 个针道", response)
        lowered = response.lower()
        self.assertTrue(
            ("rl" in lowered and ("规则" in response or "rule_based" in lowered
                                  or "rule-based" in lowered)),
            response,
        )
        self.assertTrue(
            ("兜底" in response or "fallback" in lowered),
            response,
        )


class ToolAndSynthesisGuardTests(unittest.TestCase):
    def test_query_metrics_routes_method_questions_to_planning_method(self):
        from tool_factory.viewer_command.query_metrics import QueryMetricsTool

        description = QueryMetricsTool().description.lower()
        self.assertIn("algorithm", description)
        self.assertIn("provenance", description)
        self.assertIn("planning_method", description)

    def test_final_synthesis_requires_question_fit(self):
        from agent_runtime.llm_runtime import _FINAL_SYNTHESIS_INSTRUCTION

        text = _FINAL_SYNTHESIS_INSTRUCTION.lower()
        self.assertIn("algorithm", text)
        self.assertIn("mode", text)
        self.assertIn("planning_method", text)


class ExecutionTrajectoryVisibilityTests(unittest.TestCase):
    """The root fix: the LLM must SEE the historical execution trajectory.

    Tool results used to enter memory as ``[Tool result: ...]`` artifacts that
    message assembly strips, and the structured ``memory.tool_results`` log
    was never injected, while the prompt told the model to "read from
    tool_results".  The model was blind to what the previous turn executed.
    """

    def test_trajectory_digest_includes_tool_results_and_method_facts(self):
        from agent_runtime.llm_runtime import build_execution_trajectory_context

        class Memory:
            def __init__(self):
                self.values = {
                    "tool_results": [
                        {
                            "tool": "planning_pipeline",
                            "inputs": {"mode": "rl"},
                            "success": True,
                            "message": "Planning completed",
                            "execution_time": 1582.0,
                            "summary": {
                                "requested_mode": "rl",
                                "effective_mode": "rule_based_fallback",
                                "total_seeds": 181,
                            },
                        },
                        {
                            "tool": "query_metrics",
                            "inputs": {"metric_type": "all_metrics"},
                            "success": True,
                            "message": "V100 90.23%",
                            "execution_time": 1.0,
                            "summary": {"metric_type": "all_metrics"},
                        },
                    ],
                    "plan_config": {
                        "requested_mode": "rl",
                        "effective_mode": "rule_based_fallback",
                        "rl_fallback_used": True,
                        "rl_fallback_reason": "strict_coverage_improvement",
                    },
                    "rl_status": {
                        "execution": "interrupted",
                        "stop_reason": "dose_inference_deadline",
                        "best_coverage": 0.097,
                        "target_coverage": 0.9,
                    },
                }

            def retrieve(self, key, default=None):
                return self.values.get(key, default)

        digest = build_execution_trajectory_context(Memory())
        self.assertIn("planning_pipeline", digest)
        self.assertIn("query_metrics", digest)
        self.assertIn("rule_based_fallback", digest)
        self.assertIn("dose_inference_deadline", digest)
        self.assertIn("rl", digest.lower())

    def test_empty_history_produces_no_trajectory_noise(self):
        from agent_runtime.llm_runtime import build_execution_trajectory_context

        class Memory:
            def retrieve(self, key, default=None):
                return default

        self.assertEqual(build_execution_trajectory_context(Memory()), "")

    def test_log_tool_call_captures_a_metadata_summary(self):
        from agent_runtime.core import AgentMemory
        from tool_factory import ToolResult

        memory = AgentMemory(session_id="test")
        result = ToolResult(
            success=True,
            message="Planning completed",
            metadata={"effective_mode": "rule_based_fallback",
                      "requested_mode": "rl",
                      "response_contract": {"mode": "direct_read"}},
        )
        memory.log_tool_call("planning_pipeline", {"mode": "rl"}, result)
        entry = memory.tool_results[-1]
        self.assertEqual(entry["tool"], "planning_pipeline")
        self.assertEqual(entry["summary"].get("effective_mode"),
                         "rule_based_fallback")
        self.assertEqual(entry["summary"].get("requested_mode"), "rl")
        self.assertNotIn("response_contract", entry["summary"])

    def test_message_assembly_wires_the_trajectory_digest(self):
        import inspect

        from agent_runtime import llm_runtime

        source = inspect.getsource(llm_runtime)
        self.assertGreaterEqual(
            source.count("build_execution_trajectory_context("), 2,
            "both streaming and non-streaming assembly must include the digest",
        )


class PlanningMethodToolTests(unittest.TestCase):
    def test_query_metrics_planning_method_reports_the_algorithm_family(self):
        from tool_factory.viewer_command.query_metrics import QueryMetricsTool

        result = QueryMetricsTool()._execute(
            metric_type="planning_method",
            planning_method={
                "requested_mode": "rl",
                "effective_mode": "rule_based_fallback",
                "rl_fallback_used": True,
                "rl_fallback_reason": "strict_coverage_improvement",
                "rl_target_coverage": 0.9,
                "rl_fallback_coverage": 0.9023,
                "rl_status": {
                    "execution": "interrupted",
                    "stop_reason": "dose_inference_deadline",
                    "best_coverage": 0.097,
                },
            },
        )
        self.assertTrue(result.success)
        text = f"{result.message} {json.dumps(result.data, default=str)}".lower()
        self.assertIn("rl", text)
        self.assertIn("rule_based_fallback", text)
        self.assertIn("strict_coverage_improvement", text)
        self.assertIn("dose_inference_deadline", text)
        covers = (result.metadata.get("response_contract") or {}).get("covers") or []
        self.assertIn("planning_method", covers)


if __name__ == "__main__":
    unittest.main()
