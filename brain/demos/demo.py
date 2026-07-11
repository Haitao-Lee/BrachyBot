"""
BrachyBot Brain System Demo
==========================
End-to-end demonstration of the LLM-driven brachytherapy planning system.
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def demo_tool_registry():
    """Demonstrate tool registry with toolset.json."""
    print("\n" + "="*60)
    print("DEMO 1: Tool Registry")
    print("="*60)

    from brain import ToolRegistry, get_tool_registry

    registry = get_tool_registry()
    all_tools = registry.list_all()
    print(f"\nLoaded {len(all_tools)} tools from toolset.json")

    print("\nTool categories:")
    categories = set(spec.category for spec in registry.get_all_tools().values())
    for cat in sorted(categories):
        tools = registry.list_by_category(cat)
        print(f"  {cat}: {len(tools)} tools")

    print("\nSegmentation tools (CTV):")
    ctv_tools = registry.list_by_category("ctv")
    for tool_name in ctv_tools:
        tool = registry.get(tool_name)
        print(f"  - {tool.name}: {tool.description}")

    print("\nTool by ID (ID=30 - seed planning):")
    tool = registry.get_by_id(30)
    if tool:
        print(f"  Name: {tool.name}")
        print(f"  Type: {tool.type}")
        print(f"  Description: {tool.description}")
        print(f"  Input: {tool.input_schema}")
        print(f"  Output: {tool.output_schema}")

    return registry


def demo_rag():
    """Demonstrate RAG system for dose constraints."""
    print("\n" + "="*60)
    print("DEMO 2: RAG System (Dose Constraints)")
    print("="*60)

    from brain import SimpleRAG, DoseRAG, get_rag

    rag = get_rag()

    print(f"\nRAG initialized (DoseRAG - specialized for dose constraints)")

    print("\nQuery: 'pancreas OAR dose constraints'")
    results = rag.retrieve("pancreas OAR dose constraints")
    print(f"  Retrieved {len(results)} relevant chunks")
    for i, r in enumerate(results[:2], 1):
        print(f"  [{i}] {r[:200]}...")

    print("\nQuery: 'prostate D90 target'")
    results = rag.retrieve("prostate D90 target")
    print(f"  Retrieved {len(results)} relevant chunks")
    for i, r in enumerate(results[:2], 1):
        print(f"  [{i}] {r[:200]}...")

    print("\nDose constraints for pancreas:")
    constraints = rag.get_constraints("pancreas")
    for oar, limits in constraints.items():
        print(f"  {oar}: {limits}")

    print("\nDose constraints for prostate:")
    constraints = rag.get_constraints("prostate")
    for oar, limits in constraints.items():
        print(f"  {oar}: {limits}")

    return rag


def demo_llm_providers():
    """Demonstrate available LLM providers."""
    print("\n" + "="*60)
    print("DEMO 3: LLM Providers")
    print("="*60)

    from brain import (
        LLMRouter, OpenRouterLLM, OpenAILLM, AnthropicLLM,
        QwenLLM, KimiLLM, MiniMaxLLM, GLMLLM, GeminiLLM,
        GroqLLM, GrokLLM, MimoLLM, DeepSeekLLM, TencentLLM
    )

    print("\nSupported providers:")
    providers = [
        ("OpenRouter", "Unified access to 100+ models"),
        ("OpenAI", "GPT-5.5, GPT-5.4, o3, o4-mini, GPT-4.1"),
        ("Anthropic", "Claude Opus 4.7, Sonnet 4.6"),
        ("Qwen", "qwen-plus, qwq-32b"),
        ("Kimi", "kimi-k2.6, kimi-k2.5"),
        ("MiniMax", "minimax-m2.7, abab6.5s-chat"),
        ("GLM", "glm-4-flash, glm-z1-32b"),
        ("Gemini", "gemini-2.0-flash, gemini-3-flash-preview"),
        ("Groq", "llama-3.3-70b-versatile"),
        ("Grok", "grok-3, grok-4.3"),
        ("Mimo", "mimo-4"),
        ("DeepSeek", "deepseek-v4-flash, deepseek-v4-pro"),
        ("Tencent", "hy3-preview"),
    ]

    for name, desc in providers:
        print(f"  - {name}: {desc}")

    print("\nOpenRouterLLM top models:")
    top_models = ["hy3-preview", "claude-opus-4.7", "kimi-k2.6", "deepseek-v4-flash",
                  "gemini-3-flash", "minimax-m2.7", "gpt-5.5-pro", "grok-3"]
    for model_id in top_models:
        info = OpenRouterLLM.model_info(model_id)
        print(f"  {model_id}: {info['name']} ({info['provider']})")


def demo_case_executor():
    """Demonstrate CaseExecutor with step dependencies."""
    print("\n" + "="*60)
    print("DEMO 4: Case Executor (MedAgent-Pro Pattern)")
    print("="*60)

    from brain import CaseExecutor, CaseExecutionResult

    executor = CaseExecutor()

    plan = {
        "id": "brachy_plan_001",
        "case_id": "pancreas_case_001",
        "steps": [
            {
                "id": 1,
                "tool": "pancreatic_ctv",
                "action": "Segment pancreatic CTV",
                "action_type": "quantitative",
                "dependencies": [],
            },
            {
                "id": 2,
                "tool": "totalsegmentator_oar",
                "action": "Segment OARs",
                "action_type": "quantitative",
                "dependencies": [],
            },
            {
                "id": 3,
                "tool": "trajectory_init",
                "action": "Generate initial trajectory",
                "action_type": "quantitative",
                "dependencies": [1, 2],
            },
            {
                "id": 4,
                "tool": "unified_seed",
                "action": "Plan seed placement",
                "action_type": "quantitative",
                "dependencies": [3],
            },
            {
                "id": 5,
                "tool": "comprehensive_dose_evaluation",
                "action": "Evaluate dose distribution",
                "action_type": "quantitative",
                "dependencies": [4],
            },
            {
                "id": 6,
                "tool": "clinical_decider",
                "action": "Clinical acceptance decision",
                "action_type": "qualitative",
                "dependencies": [5],
            },
        ],
    }

    print(f"\nExecuting plan: {plan['id']}")
    print(f"Case: {plan['case_id']}")
    print(f"Steps: {len(plan['steps'])}")

    print("\nStep execution order (resolved dependencies):")
    execution_order = executor.resolve_execution_order(plan["steps"])
    for i, step_group in enumerate(execution_order, 1):
        if isinstance(step_group, list):
            print(f"  Phase {i} (parallel): {[s['id'] for s in step_group]}")
        else:
            print(f"  Phase {i}: [{step_group['id']}]")

    print("\n✓ CaseExecutor demonstration complete")
    return executor


def demo_integration():
    """Demonstrate BrainToolBridge integration."""
    print("\n" + "="*60)
    print("DEMO 5: BrainToolBridge Integration")
    print("="*60)

    from brain import initialize_brain_integration, get_bridge

    bridge = initialize_brain_integration()

    print(f"\nBrainToolBridge initialized")
    print(f"  - Tool factories: {list(bridge._tool_factories.keys())}")

    print("\nAvailable planning tools via bridge:")
    for name in bridge._tool_instances.keys():
        print(f"  - {name}")

    print("\nExample: Get CTV segmentation tool")
    ctv_tool = bridge.get_tool("pancreatic_ctv")
    if ctv_tool:
        print(f"  Tool: {ctv_tool.name}")
        print(f"  Description: {ctv_tool.description}")

    print("\nExample: Get seed planning tool")
    seed_tool = bridge.get_tool("unified_seed")
    if seed_tool:
        print(f"  Tool: {seed_tool.name}")
        print(f"  Description: {seed_tool.description}")

    return bridge


def demo_end_to_end_simulation():
    """Simulate an end-to-end brachytherapy planning session."""
    print("\n" + "="*60)
    print("DEMO 6: End-to-End Planning Simulation")
    print("="*60)

    print("""
This simulation shows how the Brain system orchestrates LLM-driven planning:

1. PLANNER generates a tool-chain execution plan based on:
   - Patient case (pancreas cancer)
   - Clinical constraints (OAR dose limits from RAG)
   - Available tools (from ToolRegistry)

2. CASE EXECUTOR executes the plan with dependency resolution:
   Step 1: Segment pancreatic CTV (independent)
   Step 2: Segment OARs via TotalSegmentator (independent)
   Step 3: Generate initial trajectory (depends on 1, 2)
   Step 4: Plan seed placement using RL (depends on 3)
   Step 5: Evaluate dose distribution (depends on 4)
   Step 6: Clinical decision (depends on 5)

3. QUALITY DECIDER evaluates the plan:
   - Checks V100, V150, D90 metrics against constraints
   - Reviews OAR sparing
   - Accepts or rejects with refinements

4. Output: DICOM RT plan files

This architecture mirrors MedAgent-Pro's CaseExecutor pattern,
adapted for brachytherapy planning with:
   - Multi-decider roles (Planner, Clinical, Quality)
   - RAG-powered domain knowledge
   - OpenRouter unified model access
""")

    print("✓ End-to-end simulation complete")


def main():
    """Run all demonstrations."""
    print("="*60)
    print("BrachyBot Brain System - Complete Demo")
    print("="*60)
    print("""
Architecture: MedAgent-Pro inspired
- Tool Registry: 21 tools from toolset.json
- Case Executor: Step dependency resolution
- RAG System: Dose constraints knowledge base
- LLM Providers: 13 providers including OpenRouter
- BrainToolBridge: Integration layer
""")

    try:
        demo_tool_registry()
        demo_rag()
        demo_llm_providers()
        demo_case_executor()
        demo_integration()
        demo_end_to_end_simulation()

        print("\n" + "="*60)
        print("ALL DEMOS COMPLETED SUCCESSFULLY")
        print("="*60)

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
