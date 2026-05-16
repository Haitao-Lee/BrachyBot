"""
BrachyBot 使用示例
=================
演示如何使用 BrachyAgent 进行近距离放射治疗规划。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def example_basic_agent():
    """基本 Agent 使用示例."""
    print("\n" + "="*60)
    print("示例1: 基本 BrachyAgent 使用")
    print("="*60)

    from AgenticSys import BrachyAgent

    agent = BrachyAgent(session_id="example_001")

    print(f"\nAgent 初始化成功!")
    print(f"  - Session: {agent.memory.session_id}")
    print(f"  - Brain系统: {'可用' if agent.brain_available else '不可用'}")
    print(f"  - 工具数量: {len(agent.registry.tool_names)}")
    print(f"  - 可用工具: {', '.join(agent.registry.tool_names)}")

    status = agent.get_status()
    print(f"\n状态:")
    print(f"  - 阶段: {status['phase']}")
    print(f"  - 对话数: {status['messages']}")

    response = agent.chat("工具列表")
    print(f"\n用户: 工具列表")
    print(f"助手: {response[:200]}...")


def example_chat_interface():
    """对话接口示例."""
    print("\n" + "="*60)
    print("示例2: 对话接口")
    print("="*60)

    from AgenticSys import BrachyAgent

    agent = BrachyAgent(session_id="chat_example")

    commands = [
        "分割CTV",
        "生成治疗计划",
        "评估剂量",
        "帮助",
    ]

    for cmd in commands:
        print(f"\n用户: {cmd}")
        response = agent.chat(cmd)
        print(f"助手: {response[:150]}..." if len(response) > 150 else f"助手: {response}")


def example_brain_system():
    """Brain系统示例."""
    print("\n" + "="*60)
    print("示例3: Brain系统")
    print("="*60)

    from brain import (
        LLMRouter, CaseExecutor, DoseRAG,
        ToolRegistry, BrainToolBridge
    )

    print("\n3.1 ToolRegistry")
    registry = ToolRegistry()
    print(f"  - 工具数量: {len(registry.list_all())}")

    print("\n3.2 DoseRAG (剂量约束)")
    rag = DoseRAG()
    pancreas_constraints = rag.get_constraints("pancreas")
    print(f"  - 胰腺OAR约束: {list(pancreas_constraints.keys())}")

    prostate_constraints = rag.get_constraints("prostate")
    print(f"  - 前列腺OAR约束: {list(prostate_constraints.keys())}")

    print("\n3.3 CaseExecutor")
    executor = CaseExecutor()
    plan = [
        {"id": 1, "tool": "pancreatic_ctv", "action": "分割CTV", "dependencies": []},
        {"id": 2, "tool": "totalsegmentator_oar", "action": "分割OAR", "dependencies": []},
        {"id": 3, "tool": "trajectory_init", "action": "生成轨迹", "dependencies": [1, 2]},
        {"id": 4, "tool": "unified_seed", "action": "种子规划", "dependencies": [3]},
        {"id": 5, "tool": "comprehensive_dose_evaluation", "action": "评估剂量", "dependencies": [4]},
    ]
    execution_order = executor.resolve_execution_order(plan)
    print(f"  - 执行阶段数: {len(execution_order)}")
    for i, phase in enumerate(execution_order, 1):
        print(f"    阶段{i}: {[s['id'] for s in phase]}")


def example_rag_query():
    """RAG查询示例."""
    print("\n" + "="*60)
    print("示例4: RAG知识检索")
    print("="*60)

    from brain.knowledge.rag import DoseRAG

    rag = DoseRAG()

    queries = [
        "胰腺癌 OAR 剂量限制",
        "前列腺癌靶区覆盖率",
        "直肠剂量约束",
    ]

    for query in queries:
        print(f"\n查询: '{query}'")
        results = rag.retrieve(query)
        print(f"  结果数: {len(results)}")
        for r in results[:2]:
            print(f"  - {r[:80]}...")


def main():
    print("="*60)
    print("BrachyBot 使用示例")
    print("="*60)

    try:
        example_basic_agent()
    except Exception as e:
        print(f"\n示例1失败: {e}")

    try:
        example_chat_interface()
    except Exception as e:
        print(f"\n示例2失败: {e}")

    try:
        example_brain_system()
    except Exception as e:
        print(f"\n示例3失败: {e}")

    try:
        example_rag_query()
    except Exception as e:
        print(f"\n示例4失败: {e}")

    print("\n" + "="*60)
    print("示例完成")
    print("="*60)


if __name__ == "__main__":
    main()