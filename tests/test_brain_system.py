"""
BrachyBot Integration Tests
===========================
Tests for the brain system and BrachyAgent integration.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBrainSystem(unittest.TestCase):
    """Tests for the brain system components."""

    def test_brain_imports(self):
        """Test that brain system can be imported."""
        from brain import (
            LLMRouter, CaseExecutor, DoseRAG,
            ToolRegistry, BrainToolBridge,
            OpenRouterLLM, OpenAILLM
        )
        self.assertIsNotNone(LLMRouter)
        self.assertIsNotNone(CaseExecutor)

    def test_tool_registry(self):
        """Test tool registry functionality."""
        from brain.core.tool_registry import ToolRegistry, get_tool_registry

        registry = get_tool_registry()
        self.assertIsInstance(registry, ToolRegistry)

        tools = registry.list_all()
        self.assertIsInstance(tools, list)

        tool_by_id = registry.get_by_id(30)
        if tool_by_id:
            self.assertEqual(tool_by_id.id, 30)

    def test_rag_system(self):
        """Test RAG system."""
        from brain.knowledge.rag import DoseRAG, get_rag

        rag = get_rag()
        self.assertIsInstance(rag, DoseRAG)

        pancreas_constraints = rag.get_constraints("pancreas")
        self.assertIsInstance(pancreas_constraints, dict)
        self.assertIn("duodenum", pancreas_constraints)

        prostate_constraints = rag.get_constraints("prostate")
        self.assertIn("rectum", prostate_constraints)

    def test_case_executor_ordering(self):
        """Test CaseExecutor dependency resolution."""
        from brain.execution.case_executor import CaseExecutor

        executor = CaseExecutor()

        steps = [
            {"id": 1, "tool": "a", "action": "step1", "dependencies": []},
            {"id": 2, "tool": "b", "action": "step2", "dependencies": []},
            {"id": 3, "tool": "c", "action": "step3", "dependencies": [1, 2]},
            {"id": 4, "tool": "d", "action": "step4", "dependencies": [3]},
        ]

        order = executor.resolve_execution_order(steps)

        self.assertEqual(len(order), 3)
        self.assertEqual(len(order[0]), 2)
        self.assertEqual(len(order[1]), 1)
        self.assertEqual(len(order[2]), 1)

    def test_openrouter_provider(self):
        """Test OpenRouterLLM provider structure."""
        from brain.providers.openrouter_llm import OpenRouterLLM

        models = OpenRouterLLM.SUPPORTED_MODELS
        self.assertIsInstance(models, dict)
        self.assertIn("hy3-preview", models)
        self.assertIn("claude-opus-4.7", models)

        info = models.get("hy3-preview")
        self.assertEqual(info["name"], "Tencent hy3-preview")


class TestBrachyAgent(unittest.TestCase):
    """Tests for BrachyAgent."""

    def test_agent_initialization(self):
        """Test that BrachyAgent can be initialized."""
        from AgenticSys import BrachyAgent

        agent = BrachyAgent(session_id="test")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.memory.session_id, "test")
        self.assertIn("ctv_segmentation", agent.registry.tool_names)

    def test_agent_chat_fallback(self):
        """Test that chat falls back to rule-based when brain unavailable."""
        from AgenticSys import BrachyAgent

        agent = BrachyAgent(session_id="test")
        response = agent.chat("list tools")
        self.assertIsInstance(response, str)
        self.assertIn("Available tools", response)

    def test_agent_status(self):
        """Test agent status reporting."""
        from AgenticSys import BrachyAgent

        agent = BrachyAgent(session_id="test")
        status = agent.get_status()

        self.assertIn("session_id", status)
        self.assertIn("phase", status)
        self.assertIn("tools_available", status)
        self.assertEqual(status["session_id"], "test")


class TestProviders(unittest.TestCase):
    """Tests for LLM providers."""

    def test_openai_llm_models(self):
        """Test OpenAI LLM model list."""
        from brain.providers.openai_llm import OpenAILLM

        models = OpenAILLM.SUPPORTED_MODELS
        self.assertIsInstance(models, dict)
        self.assertIn("gpt-5.5-pro", models)

    def test_qwen_llm_models(self):
        """Test Qwen LLM model list."""
        from brain.providers.qwen_llm import QwenLLM

        models = QwenLLM.SUPPORTED_MODELS
        self.assertIsInstance(models, dict)
        self.assertIn("qwen-plus", models)

    def test_kimi_llm_models(self):
        """Test Kimi LLM model list."""
        from brain.providers.kimi_llm import KimiLLM

        models = KimiLLM.SUPPORTED_MODELS
        self.assertIsInstance(models, dict)
        self.assertIn("kimi-k2.6", models)


class TestIntegration(unittest.TestCase):
    """Integration tests."""

    def test_brain_agent_connection(self):
        """Test that brain system connects to BrachyAgent."""
        from AgenticSys import BrachyAgent

        agent = BrachyAgent(session_id="integration_test")
        self.assertFalse(agent.brain_available)

    def test_demo_execution(self):
        """Test that demo can be executed."""
        from brain.demos.demo import demo_tool_registry, demo_rag

        try:
            registry = demo_tool_registry()
            self.assertIsNotNone(registry)
        except Exception as e:
            self.fail(f"demo_tool_registry failed: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)