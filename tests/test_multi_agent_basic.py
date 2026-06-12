"""
Basic tests for Multi-Agent System
===================================
Tests for communication protocol, message bus, and router agent.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType, Priority,
    RoutingDecision
)
from communication.message_bus import MessageBus
from agents.router_agent import RouterAgent


async def test_protocol():
    """Test communication protocol classes."""
    print("=" * 60)
    print("TEST 1: Communication Protocol")
    print("=" * 60)

    # Test AgentMessage creation
    msg = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="Execute pancreatic cancer brachytherapy planning",
        priority=Priority.HIGH,
    )

    assert msg.sender == AgentRole.USER
    assert msg.receiver == AgentRole.ROUTER
    assert msg.message_type == MessageType.REQUEST
    assert msg.content == "Execute pancreatic cancer brachytherapy planning"
    assert msg.priority == Priority.HIGH
    assert msg.message_id is not None
    assert msg.timestamp > 0

    # Test to_dict
    msg_dict = msg.to_dict()
    assert msg_dict["sender"] == "user"
    assert msg_dict["receiver"] == "router"
    assert msg_dict["message_type"] == "request"

    print("✓ AgentMessage creation and serialization OK")

    # Test AgentResponse
    response = AgentResponse(
        agent_role=AgentRole.ROUTER,
        success=True,
        result={"intent": "clinical_planning"},
        confidence=0.9,
        reasoning="Pattern match",
    )

    assert response.agent_role == AgentRole.ROUTER
    assert response.success is True
    assert response.confidence == 0.9

    print("✓ AgentResponse creation OK")

    # Test RoutingDecision
    routing = RoutingDecision(
        intent="clinical_planning",
        complexity="high",
        agents_needed=[AgentRole.CLINICAL_EXECUTOR],
        requires_review=True,
    )

    assert routing.intent == "clinical_planning"
    assert routing.complexity == "high"
    assert AgentRole.CLINICAL_EXECUTOR in routing.agents_needed

    print("✓ RoutingDecision creation OK")
    print()

    return True


async def test_message_bus():
    """Test message bus functionality."""
    print("=" * 60)
    print("TEST 2: Message Bus")
    print("=" * 60)

    bus = MessageBus()

    # Test subscription
    received_messages = []

    async def handler(message: AgentMessage):
        received_messages.append(message)
        return "handled"

    bus.subscribe("request", handler)

    assert "request" in bus._subscribers
    assert len(bus._subscribers["request"]) == 1

    print("✓ Subscription OK")

    # Test publishing
    msg = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="Test message",
    )

    results = await bus.publish(msg)

    assert len(received_messages) == 1
    assert received_messages[0].content == "Test message"
    assert "handled" in results

    print("[OK] Publishing OK")

    # Test history
    history = bus.get_history()
    assert len(history) == 1
    assert history[0].message_id == msg.message_id

    print("[OK] History tracking OK")

    # Test stats
    stats = bus.get_stats()
    assert stats["total_messages"] == 1
    assert stats["history_size"] == 1

    print("[OK] Statistics OK")

    # Test role-based subscription
    role_messages = []

    async def role_handler(message: AgentMessage):
        role_messages.append(message)

    bus.subscribe("router", role_handler)

    msg2 = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.RESPONSE,
        content="Role test",
    )

    await bus.publish(msg2)

    assert len(role_messages) == 1

    print("✓ Role-based subscription OK")
    print()

    return True


async def test_router_agent():
    """Test router agent functionality."""
    print("=" * 60)
    print("TEST 3: Router Agent")
    print("=" * 60)

    router = RouterAgent()

    # Test pattern matching - clinical planning
    msg1 = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="Execute pancreatic cancer brachytherapy planning",
    )

    response1 = await router.handle_message(msg1)

    assert response1.success is True
    assert response1.agent_role == AgentRole.ROUTER

    routing1 = response1.result
    assert routing1.intent == "clinical_planning"
    assert routing1.complexity == "high"
    assert AgentRole.CLINICAL_EXECUTOR in routing1.agents_needed
    assert routing1.requires_review is True

    print(f"✓ Clinical planning routing: intent={routing1.intent}, "
          f"complexity={routing1.complexity}, confidence={routing1.confidence:.2f}")

    # Test pattern matching - segmentation
    msg2 = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="Segment CTV and OAR",
    )

    response2 = await router.handle_message(msg2)
    routing2 = response2.result

    assert routing2.intent == "segmentation"
    assert routing2.complexity == "medium"

    print(f"✓ Segmentation routing: intent={routing2.intent}, "
          f"complexity={routing2.complexity}, confidence={routing2.confidence:.2f}")

    # Test pattern matching - knowledge query (use pure knowledge query)
    msg3 = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="What are the dosimetry standards for brachytherapy? Explain the QUANTEC guidelines.",
    )

    response3 = await router.handle_message(msg3)
    routing3 = response3.result

    # This should match knowledge_query since it has more knowledge keywords
    assert routing3.intent == "knowledge_query"
    assert routing3.complexity == "low"

    print(f"✓ Knowledge query routing: intent={routing3.intent}, "
          f"complexity={routing3.complexity}, confidence={routing3.confidence:.2f}")

    # Test agent stats
    stats = router.get_stats()
    assert stats["processed_count"] == 3
    assert stats["error_count"] == 0

    print(f"✓ Agent stats: processed={stats['processed_count']}, "
          f"success_rate={stats['success_rate']:.2f}")
    print()

    return True


async def test_router_with_message_bus():
    """Test router agent integration with message bus."""
    print("=" * 60)
    print("TEST 4: Router + Message Bus Integration")
    print("=" * 60)

    bus = MessageBus()
    router = RouterAgent()

    # Subscribe router to request messages
    async def route_handler(message: AgentMessage):
        return await router.handle_message(message)

    bus.subscribe("request", route_handler)

    # Send a message through the bus
    msg = AgentMessage(
        sender=AgentRole.USER,
        receiver=AgentRole.ROUTER,
        message_type=MessageType.REQUEST,
        content="Execute dose evaluation",
    )

    results = await bus.publish(msg)

    assert len(results) == 1
    response = results[0]
    assert response.success is True
    assert response.result.intent == "dose_evaluation"

    print(f"[OK] Message bus routing: intent={response.result.intent}, "
          f"confidence={response.confidence:.2f}")

    # Check message history
    history = bus.get_history(AgentRole.ROUTER)
    assert len(history) == 1

    print(f"[OK] Message history: {len(history)} messages")
    print()

    return True


async def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("MULTI-AGENT SYSTEM BASIC TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("Communication Protocol", test_protocol),
        ("Message Bus", test_message_bus),
        ("Router Agent", test_router_agent),
        ("Router + Message Bus", test_router_with_message_bus),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("ALL TESTS PASSED! ✓")
    else:
        print("SOME TESTS FAILED! ✗")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
