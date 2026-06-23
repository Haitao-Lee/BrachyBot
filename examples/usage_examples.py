"""
BrachyBot Usage Examples
========================
Demonstrates how to use BrachyAgent for brachytherapy treatment planning.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def example_basic_agent():
    """Basic agent usage example."""
    print("\n" + "="*60)
    print("Example 1: Basic BrachyAgent Usage")
    print("="*60)

    from AgenticSys import BrachyAgent

    agent = BrachyAgent(session_id="example_001")

    print(f"\nAgent initialized successfully!")
    print(f"  - Session: {agent.memory.session_id}")
    print(f"  - Brain system: {'available' if agent.brain_available else 'unavailable'}")
    print(f"  - Tool count: {len(agent.registry.tool_names)}")
    print(f"  - Available tools: {', '.join(agent.registry.tool_names)}")

    status = agent.get_status()
    print(f"\nStatus:")
    print(f"  - Phase: {status['phase']}")
    print(f"  - Messages: {status['messages']}")

    response = agent.chat("list tools")
    print(f"\nUser: list tools")
    print(f"Assistant: {response[:200]}...")


def example_chat_interface():
    """Chat interface example."""
    print("\n" + "="*60)
    print("Example 2: Chat Interface")
    print("="*60)

    from AgenticSys import BrachyAgent

    agent = BrachyAgent(session_id="chat_example")

    commands = [
        "segment CTV",
        "generate treatment plan",
        "evaluate dose",
        "help",
    ]

    for cmd in commands:
        print(f"\nUser: {cmd}")
        response = agent.chat(cmd)
        print(f"Assistant: {response[:150]}..." if len(response) > 150 else f"Assistant: {response}")


def example_brain_system():
    """Brain system example."""
    print("\n" + "="*60)
    print("Example 3: Brain System")
    print("="*60)

    from brain import (
        LLMRouter, CaseExecutor, DoseRAG,
        ToolRegistry, BrainToolBridge
    )

    print("\n3.1 ToolRegistry")
    registry = ToolRegistry()
    print(f"  - Tool count: {len(registry.list_all())}")

    print("\n3.2 DoseRAG (dose constraints)")
    rag = DoseRAG()
    pancreas_constraints = rag.get_constraints("pancreas")
    print(f"  - Pancreas OAR constraints: {list(pancreas_constraints.keys())}")

    prostate_constraints = rag.get_constraints("prostate")
    print(f"  - Prostate OAR constraints: {list(prostate_constraints.keys())}")

    print("\n3.3 CaseExecutor")
    executor = CaseExecutor()
    plan = [
        {"id": 1, "tool": "pancreatic_ctv", "action": "Segment CTV", "dependencies": []},
        {"id": 2, "tool": "totalsegmentator_oar", "action": "Segment OAR", "dependencies": []},
        {"id": 3, "tool": "trajectory_init", "action": "Generate trajectories", "dependencies": [1, 2]},
        {"id": 4, "tool": "unified_seed", "action": "Seed planning", "dependencies": [3]},
        {"id": 5, "tool": "comprehensive_dose_evaluation", "action": "Evaluate dose", "dependencies": [4]},
    ]
    execution_order = executor.resolve_execution_order(plan)
    print(f"  - Execution phases: {len(execution_order)}")
    for i, phase in enumerate(execution_order, 1):
        print(f"    Phase {i}: {[s['id'] for s in phase]}")


def example_rag_query():
    """RAG query example."""
    print("\n" + "="*60)
    print("Example 4: RAG Knowledge Retrieval")
    print("="*60)

    from brain.knowledge.rag import DoseRAG

    rag = DoseRAG()

    queries = [
        "pancreatic cancer OAR dose limits",
        "prostate cancer target coverage",
        "rectum dose constraints",
    ]

    for query in queries:
        print(f"\nQuery: '{query}'")
        results = rag.retrieve(query)
        print(f"  Results: {len(results)}")
        for r in results[:2]:
            print(f"  - {r[:80]}...")


def main():
    print("="*60)
    print("BrachyBot Usage Examples")
    print("="*60)

    try:
        example_basic_agent()
    except Exception as e:
        print(f"\nExample 1 failed: {e}")

    try:
        example_chat_interface()
    except Exception as e:
        print(f"\nExample 2 failed: {e}")

    try:
        example_brain_system()
    except Exception as e:
        print(f"\nExample 3 failed: {e}")

    try:
        example_rag_query()
    except Exception as e:
        print(f"\nExample 4 failed: {e}")

    print("\n" + "="*60)
    print("Examples completed")
    print("="*60)


if __name__ == "__main__":
    main()
