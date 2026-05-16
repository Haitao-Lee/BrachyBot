"""
BrachyAgent-Brain Integration Example
====================================
Shows how BrachyAgent can use BrainToolBridge for LLM-driven planning.

This example demonstrates:
1. Creating a brain-aware BrachyAgent
2. Using LLM deciders for planning decisions
3. Executing plans via BrainToolBridge
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def example_llm_driven_planning():
    """
    Example: LLM-driven brachytherapy planning using brain system.
    """
    print("\n" + "="*60)
    print("Example: LLM-Driven Planning with BrainSystem")
    print("="*60)

    from brain import (
        LLMRouter,
        CaseExecutor,
        CaseExecutionResult,
        ToolRegistry,
        BrainToolBridge,
        DoseRAG,
        OpenRouterLLM,
    )
    from brain.deciders import PlannerDecider, ClinicalDecider, QualityDecider

    print("\n1. Initialize Brain System Components")

    router_config = {
        "openrouter": {
            "enabled": True,
            "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "model": "hy3-preview",
        }
    }

    router = LLMRouter(router_config)
    print(f"   - LLM Router: {len(router.providers)} providers")
    print(f"   - Default provider: {router.default_provider}")

    tool_registry = ToolRegistry()
    print(f"   - Tool Registry: {len(tool_registry.list_all())} tools")

    case_executor = CaseExecutor(tool_registry)
    print(f"   - Case Executor: initialized")

    rag = DoseRAG()
    print(f"   - Dose RAG: initialized with constraints")

    print("\n2. Initialize BrainToolBridge")

    bridge = BrainToolBridge()
    bridge.set_brain_registry(tool_registry)
    bridge.set_plan_executor(case_executor)

    print(f"   - BrainToolBridge: connected to registry and executor")

    print("\n3. Create LLM Deciders")

    try:
        llm = router.providers.get("openrouter")
        if llm is None:
            print("   - Skipping decider init (no OpenRouter key)")
            llm = None
    except Exception as e:
        print(f"   - Skipping decider init: {e}")
        llm = None

    if llm:
        planner = PlannerDecider(llm, tool_registry)
        clinical = ClinicalDecider(llm)
        quality = QualityDecider(llm)
        print("   - PlannerDecider: initialized")
        print("   - ClinicalDecider: initialized")
        print("   - QualityDecider: initialized")
    else:
        planner = clinical = quality = None
        print("   - LLM deciders: skipped (no API key)")

    print("\n4. Example: Get Dose Constraints for Prostate")

    constraints = rag.get_constraints("prostate")
    print(f"   - Prostate OAR constraints:")
    for oar, limits in constraints.items():
        print(f"     {oar}: {limits}")

    print("\n5. Example: Plan Execution Order")

    plan = {
        "id": "prostate_plan_001",
        "case_id": "prostate_case_001",
        "steps": [
            {"id": 1, "tool": "prostate_ctv", "action": "Segment prostate CTV",
             "action_type": "quantitative", "dependencies": []},
            {"id": 2, "tool": "totalsegmentator_oar", "action": "Segment OARs",
             "action_type": "quantitative", "dependencies": []},
            {"id": 3, "tool": "trajectory_init", "action": "Generate trajectory",
             "action_type": "quantitative", "dependencies": [1, 2]},
            {"id": 4, "tool": "unified_seed", "action": "Plan seeds",
             "action_type": "quantitative", "dependencies": [3]},
            {"id": 5, "tool": "comprehensive_dose_evaluation", "action": "Evaluate dose",
             "action_type": "quantitative", "dependencies": [4]},
            {"id": 6, "tool": "clinical_decider", "action": "Clinical review",
             "action_type": "qualitative", "dependencies": [5]},
        ],
    }

    execution_order = case_executor.resolve_execution_order(plan["steps"])
    print(f"   - Plan: {plan['id']}")
    print(f"   - Execution phases:")
    for i, phase in enumerate(execution_order, 1):
        step_ids = [s["id"] for s in phase]
        actions = [s["action"][:30] for s in phase]
        print(f"     Phase {i}: Step(s) {step_ids} - {actions}")

    print("\n6. Example: OpenRouter Top Models")

    if llm:
        print("   Available top models:")
        top_models = ["hy3-preview", "claude-opus-4.7", "kimi-k2.6",
                      "deepseek-v4-flash", "gemini-3-flash", "minimax-m2.7"]
        for model_id in top_models:
            info = llm.get_model_info(model_id)
            print(f"   - {model_id}: {info['name']} ({info['provider']})")

    print("""
\nIntegration Summary:
====================
BrachyAgent can be extended to use BrainToolBridge by:

1. Replacing BrachyAgent.registry with BrainToolBridge
2. Using LLM Deciders (PlannerDecider, ClinicalDecider, QualityDecider)
   for high-level planning decisions
3. Using CaseExecutor for dependency-resolved execution
4. Using DoseRAG for constraint retrieval

The brain system provides:
- LLM-driven decision making (13 providers including OpenRouter)
- MedAgent-Pro style CaseExecutor with step dependencies
- RAG-powered domain knowledge (dose constraints)
- Unified tool access via BrainToolBridge
""")


def example_direct_tool_usage():
    """
    Example: Direct tool usage via BrainToolBridge.
    """
    print("\n" + "="*60)
    print("Example: Direct Tool Usage via BrainToolBridge")
    print("="*60)

    from brain import initialize_brain_integration, get_bridge

    bridge = initialize_brain_integration()

    print(f"\nRegistered tools in bridge:")
    for name in sorted(bridge._tool_factories.keys()):
        print(f"  - {name}")

    print("""
\nNote: Bridge tools require tool_factory module to be installed.
The bridge connects brain system planning to actual tool execution.
""")


def main():
    """Run integration examples."""
    print("="*60)
    print("BrachyAgent-Brain Integration Examples")
    print("="*60)

    example_llm_driven_planning()
    example_direct_tool_usage()

    print("\n" + "="*60)
    print("Examples completed")
    print("="*60)


if __name__ == "__main__":
    main()