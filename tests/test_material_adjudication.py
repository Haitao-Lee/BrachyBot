"""Material-adjudication contracts: keyword readers never print the reply.

The architectural rule from the 2026-09-23 regressions: anything a keyword
route produces (typed-read tables, canned clause drafts, status text) is
REFERENCE MATERIAL for the LLM, never the final reply.  The LLM decides
whether the material corresponds to the CURRENT question: if it does, it
composes the final answer from the material; if it does not, it fetches the
right workspace data through tools and answers from that.  Only when no LLM
is available does the material become the (honest) reply.

These contracts pin: the typed-read short-circuit is gone (its table can
never be ``final_response``), reference material is injected as data-only
context, adjudication runs through the tool-enabled LLM with a sanitized
read-only policy, insufficiency falls through to tool fetch, and the no-LLM
fallback returns the material itself.
"""
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TypedReadMaterialTests(unittest.TestCase):
    def test_typed_read_short_circuit_is_gone(self):
        import inspect

        from agent_runtime import llm_runtime

        source = inspect.getsource(llm_runtime)
        self.assertNotIn("final_response = _direct_read_candidate", source)
        self.assertNotIn("_direct_read_candidate", source)
        self.assertNotIn("_direct_candidate_for_tool", source)

    def test_reference_material_injection_wired_at_both_assemblies(self):
        import inspect

        from agent_runtime import llm_runtime

        source = inspect.getsource(llm_runtime)
        self.assertGreaterEqual(source.count("build_reference_material_context("), 3)

    def test_reference_material_block_marks_data_only(self):
        from agent_runtime.llm_runtime import (
            REFERENCE_MATERIAL_INSTRUCTION,
            build_reference_material_context,
        )

        block = build_reference_material_context("V100 = 90.2%")
        self.assertIn("V100 = 90.2%", block)
        self.assertIn("Reference material", block)
        self.assertIn("not instructions", block.lower())
        self.assertEqual(build_reference_material_context("  "), "")
        lower = REFERENCE_MATERIAL_INSTRUCTION.lower()
        self.assertIn("correspond", lower)
        self.assertIn("call tools", lower)
        self.assertIn("verbatim", lower)


class _FakeMemory:
    user_lang = "zh"

    def __init__(self):
        self.values = {}
        self.tool_results = []
        self.conversation = []

    def retrieve(self, key, default=None):
        return self.values.get(key, default)

    def store(self, key, value):
        self.values[key] = value

    def add_message(self, role, content):
        self.conversation.append({"role": role, "content": content})


class MaterialAdjudicationTests(unittest.TestCase):
    def _workflow(self, brain_available=True):
        from agent_runtime.chat_workflows import ChatWorkflowMixin
        from agent_runtime.turn_policy import LocalTurnPolicy

        workflow = object.__new__(ChatWorkflowMixin)
        workflow.memory = _FakeMemory()
        workflow.brain_available = brain_available
        workflow._active_turn_policy = LocalTurnPolicy(
            "multi_intent_query", "low", False, False, False, frozenset(),
            direct_execution=True,
        )
        return workflow

    def test_adjudication_uses_the_llm_and_never_the_raw_material(self):
        workflow = self._workflow()
        calls = []

        def fake_run(message, steps, step_id_ref):
            calls.append((message, str(workflow._turn_reference_material or "")))
            return "根据资料整理后的回答"

        workflow._run_llm_function_calling = fake_run
        out = workflow._answer_with_material("刚才用的什么算法？", "MATERIAL-DATA", "zh")

        self.assertEqual(out, "根据资料整理后的回答")
        self.assertTrue(calls)
        self.assertIn("MATERIAL-DATA", calls[0][1])
        self.assertEqual(workflow._turn_reference_material, "",
                         "material must be a per-turn handoff, not sticky state")

    def test_adjudication_sanitizes_the_policy_to_read_only(self):
        workflow = self._workflow()
        seen = {}

        def fake_run(message, steps, step_id_ref):
            policy = workflow._active_turn_policy
            seen["direct_execution"] = policy.direct_execution
            seen["execution_grants"] = set(policy.execution_grants or ())
            seen["workflow_grants"] = set(policy.workflow_grants or ())
            seen["allow_tools"] = set(policy.allow_tools or ())
            return "ok"

        workflow._run_llm_function_calling = fake_run
        workflow._answer_with_material("q", "M", "zh")

        self.assertFalse(seen["direct_execution"])
        self.assertEqual(seen["execution_grants"], set())
        self.assertEqual(seen["workflow_grants"], set())
        self.assertIn("query_metrics", seen["allow_tools"])
        self.assertIn("case_memory", seen["allow_tools"])

    def test_no_llm_returns_material_as_honest_fallback(self):
        workflow = self._workflow(brain_available=False)
        out = workflow._answer_with_material("q", "MATERIAL-DATA", "zh")
        self.assertEqual(out, "MATERIAL-DATA")

    def test_multi_intent_dispatch_routes_through_adjudication(self):
        import inspect

        from agent_runtime import chat_workflows, response_tools

        combined = inspect.getsource(chat_workflows) + inspect.getsource(response_tools)
        # def + at least the multi/session/status/3d dispatch wraps.
        self.assertGreaterEqual(combined.count("self._answer_with_material("), 6)


class InsufficientMaterialFetchTests(unittest.TestCase):
    def _workflow(self, editor_reply):
        from agent_runtime.chat_workflows import ChatWorkflowMixin
        from agent_runtime.turn_policy import LocalTurnPolicy

        workflow = object.__new__(ChatWorkflowMixin)
        workflow.memory = _FakeMemory()
        workflow.brain_available = True

        class Router:
            def chat_messages(self, messages=None, tools=None, task_type=None):
                class R:
                    content = editor_reply
                    usage = {}
                    model = "fake"
                    finish_reason = "stop"
                return R()

        workflow.brain_router = Router()
        workflow._active_turn_policy = LocalTurnPolicy(
            "case_state_question", "low", False, False, False, frozenset())
        return workflow

    def test_insufficient_material_falls_through_to_tool_fetch(self):
        workflow = self._workflow("INSUFFICIENT_MATERIAL")
        fetch_calls = []

        def fake_run(message, steps, step_id_ref):
            fetch_calls.append(workflow._turn_reference_material or "")
            return "工具取数后的回答"

        workflow._run_llm_function_calling = fake_run
        response, meta = workflow._answer_local_read_query(
            "为什么两次规划不一样？", "case_state_question", "zh")

        self.assertEqual(response, "工具取数后的回答")
        self.assertTrue(fetch_calls, "insufficiency must trigger a tool fetch turn")
        self.assertTrue(fetch_calls[0])
        self.assertEqual(workflow._turn_reference_material, "")

    def test_valid_grounded_answer_keeps_the_single_llm_route(self):
        workflow = self._workflow(
            "原因：两次规划的 effective_mode 不同——第一次 rl 兜底，"
            "第二次 rule_based，fingerprint 不同。")

        def fake_run(message, steps, step_id_ref):
            raise AssertionError("a corresponding material answer must not need a fetch turn")

        workflow._run_llm_function_calling = fake_run
        response, meta = workflow._answer_local_read_query(
            "为什么两次规划不一样？", "case_state_question", "zh")

        self.assertIn("effective_mode", response)
        self.assertEqual(meta.get("route"), "grounded_local_llm")


if __name__ == "__main__":
    unittest.main()
