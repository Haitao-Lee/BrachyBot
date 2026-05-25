"""
BrachyBot Brain System
======================
LLM-powered decision-making layer for the BrachyAgent.
Architecture inspired by MedAgent-Pro:
- Deciders: Role-specific LLM decision modules
- Planner: Generates tool-chain execution plans
- Executor: Executes planned steps
- Tool Registry: Bridges tool_factory tools with brain

Directory Structure:
- core/          Base classes, router, tool registry
- providers/     LLM provider implementations (14 providers)
- execution/     Plan and case executors
- knowledge/     RAG-based knowledge retrieval
- integration/   Brain-tool integration
- deciders/     Role-specific decision modules
- prompts/       LLM prompt templates
- demos/         System demonstrations
"""

from .core import (
    BaseLLM, BaseDecider, BasePlanner, LLMResponse, PlanStep,
    LLMRouter, ToolRegistry, get_tool_registry, ToolCodeWriter,
    MultiAgentCritic, CritiqueResult, ConsensusReport,
    PlanningTreeSearch, PlanningNode
)
from .execution import (
    ExecutionStatus, BaseStepResult,
    PlanExecutor, validate_plan,
    CaseExecutor, CaseExecutionResult, execute_plan
)
from .knowledge import SimpleRAG, DoseRAG, get_rag
from .integration import BrainToolBridge, get_bridge, initialize_brain_integration
from .providers import (
    OpenAILLM, AnthropicLLM, LocalLLM, OllamaLLM,
    QwenLLM, KimiLLM, MiniMaxLLM, GLMLLM,
    GeminiLLM, GroqLLM, GrokLLM, MimoLLM,
    DeepSeekLLM, TencentLLM, OpenRouterLLM
)
from .deciders import PlannerDecider, ClinicalDecider, QualityDecider

__all__ = [
    # Core
    "BaseLLM",
    "BaseDecider",
    "BasePlanner",
    "LLMResponse",
    "PlanStep",
    "LLMRouter",
    "ToolRegistry",
    "get_tool_registry",
    "ToolCodeWriter",
    "MultiAgentCritic",
    "CritiqueResult",
    "ConsensusReport",
    "PlanningTreeSearch",
    "PlanningNode",
    # Execution
    "ExecutionStatus",
    "BaseStepResult",
    "PlanExecutor",
    "validate_plan",
    "CaseExecutor",
    "CaseExecutionResult",
    "execute_plan",
    # Knowledge
    "SimpleRAG",
    "DoseRAG",
    "get_rag",
    # Integration
    "BrainToolBridge",
    "get_bridge",
    "initialize_brain_integration",
    # Providers
    "OpenAILLM",
    "AnthropicLLM",
    "LocalLLM",
    "OllamaLLM",
    "QwenLLM",
    "KimiLLM",
    "MiniMaxLLM",
    "GLMLLM",
    "GeminiLLM",
    "GroqLLM",
    "GrokLLM",
    "MimoLLM",
    "DeepSeekLLM",
    "TencentLLM",
    "OpenRouterLLM",
    # Deciders
    "PlannerDecider",
    "ClinicalDecider",
    "QualityDecider",
]