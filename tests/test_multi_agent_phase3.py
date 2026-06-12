"""
Phase 3 Tests: Integration
===========================
Tests for MultiAgentOrchestrator and BrachyAgentMultiAgentWrapper.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.orchestrator import MultiAgentOrchestrator
from agents.brachy_agent_wrapper import BrachyAgentMultiAgentWrapper
from communication.protocol import AgentRole, RoutingDecision


async def test_orchestrator_routing():
    """Test orchestrator routing."""
    print("=" * 60)
    print("TEST 1: Orchestrator Routing")
    print("=" * 60)

    orchestrator = MultiAgentOrchestrator()

    # Test clinical planning routing
    routing = await orchestrator.route_request("Execute pancreatic cancer brachytherapy planning")

    assert isinstance(routing, RoutingDecision)
    assert routing.intent == "clinical_planning"
    assert routing.complexity == "high"
    assert routing.requires_review is True

    print(f"✓ Clinical planning: intent={routing.intent}, "
          f"complexity={routing.complexity}, review={routing.requires_review}")

    # Test segmentation routing
    routing2 = await orchestrator.route_request("Segment CTV and OAR")

    assert routing2.intent == "segmentation"
    assert routing2.complexity == "medium"

    print(f"✓ Segmentation: intent={routing2.intent}, "
          f"complexity={routing2.complexity}")

    # Test knowledge query routing
    routing3 = await orchestrator.route_request("What are the dosimetry standards for brachytherapy?")

    assert routing3.intent == "knowledge_query"
    assert routing3.complexity == "low"

    print(f"✓ Knowledge query: intent={routing3.intent}, "
          f"complexity={routing3.complexity}")
    print()

    return True


async def test_orchestrator_review():
    """Test orchestrator review."""
    print("=" * 60)
    print("TEST 2: Orchestrator Review")
    print("=" * 60)

    orchestrator = MultiAgentOrchestrator()

    # Test with good treatment plan
    good_plan = {
        "dose_metrics": {
            "v100": 0.96,
            "v150": 0.45,
            "v200": 0.18,
            "d90": 1.05,
            "max_dose": 1.8,
            "oar_metrics": {
                "duodenum": {"d2cc": 0.8},
            },
        },
        "plan_info": {
            "total_seeds": 12,
            "num_trajectories": 2,
            "completed_steps": ["ctv_segmentation", "oar_segmentation",
                              "trajectory_planning", "seed_planning",
                              "dose_calculation", "dose_evaluation"],
        },
    }

    gate_result = await orchestrator.review_output("treatment_plan", good_plan)

    assert gate_result.passed is True
    assert gate_result.decision in ["pass", "conditional"]

    print(f"✓ Good plan review: decision={gate_result.decision}, "
          f"passed={gate_result.passed}")

    # Test with poor treatment plan
    poor_plan = {
        "dose_metrics": {
            "v100": 0.70,
            "d90": 0.65,
            "max_dose": 4.0,
            "oar_metrics": {
                "duodenum": {"d2cc": 1.5},
            },
        },
        "plan_info": {
            "total_seeds": 5,
            "num_trajectories": 1,
        },
    }

    gate_result2 = await orchestrator.review_output("treatment_plan", poor_plan)

    assert gate_result2.passed is False or gate_result2.decision == "conditional"

    print(f"✓ Poor plan review: decision={gate_result2.decision}, "
          f"passed={gate_result2.passed}")

    # Test stats
    stats = orchestrator.get_stats()
    assert stats["review_count"] == 2

    print(f"✓ Stats: {stats}")
    print()

    return True


async def test_orchestrator_format():
    """Test orchestrator formatting."""
    print("=" * 60)
    print("TEST 3: Orchestrator Format")
    print("=" * 60)

    orchestrator = MultiAgentOrchestrator()

    # Review a poor plan
    poor_plan = {
        "dose_metrics": {
            "v100": 0.70,
            "d90": 0.65,
            "max_dose": 4.0,
        },
        "plan_info": {"total_seeds": 5},
    }

    gate_result = await orchestrator.review_output("treatment_plan", poor_plan)

    # Format for display
    display_text = orchestrator.format_review_for_display(gate_result)

    if not gate_result.passed:
        assert "Quality Review" in display_text or "QUALITY" in display_text.upper()
        print(f"✓ Format for rejected plan:")
        print(display_text[:200])
    else:
        print(f"✓ Format for passed plan: (empty string is OK)")
    print()

    return True


async def test_wrapper_basic():
    """Test BrachyAgentMultiAgentWrapper basic functionality."""
    print("=" * 60)
    print("TEST 4: Wrapper Basic")
    print("=" * 60)

    wrapper = BrachyAgentMultiAgentWrapper()

    # Test enabled state
    assert wrapper.enabled is True
    wrapper.enabled = False
    assert wrapper.enabled is False
    wrapper.enabled = True

    print("[OK] Enable/disable works")

    # Test process request
    result = await wrapper.process_request("Execute brachytherapy planning")

    assert "routing" in result
    assert "pre_context" in result
    assert result["routing"] is not None
    assert result["routing"].intent == "clinical_planning"

    print(f"[OK] Process request: intent={result['routing'].intent}")
    print(f"  Pre-context: {result['pre_context']}")
    print()

    return True


async def test_wrapper_review():
    """Test wrapper review functionality."""
    print("=" * 60)
    print("TEST 5: Wrapper Review")
    print("=" * 60)

    wrapper = BrachyAgentMultiAgentWrapper()

    # Test treatment plan review
    dose_metrics = {
        "v100": 0.96,
        "d90": 1.05,
        "max_dose": 1.8,
    }
    plan_info = {
        "total_seeds": 12,
        "num_trajectories": 2,
        "completed_steps": ["ctv_segmentation", "oar_segmentation",
                          "trajectory_planning", "seed_planning",
                          "dose_calculation", "dose_evaluation"],
    }

    review = await wrapper.review_treatment_plan(dose_metrics, plan_info)

    assert review is not None
    assert "passed" in review
    assert "decision" in review
    assert "display_text" in review

    print(f"✓ Treatment plan review: decision={review['decision']}, "
          f"passed={review['passed']}")
    print(f"  Display text: {review['display_text'][:100]}...")

    # Test non-reviewable output
    review2 = await wrapper.review_output("general_chat", "Hello")

    assert review2 is None

    print(f"✓ Non-reviewable output: {review2}")
    print()

    return True


async def test_wrapper_web_search():
    """Test wrapper web search review."""
    print("=" * 60)
    print("TEST 6: Wrapper Web Search Review")
    print("=" * 60)

    wrapper = BrachyAgentMultiAgentWrapper()

    # Test with reliable sources
    claims = ["I-125 seeds have a half-life of 60 days"]
    sources = ["https://pubmed.ncbi.nlm.nih.gov/12345"]

    review = await wrapper.review_web_search(claims, sources)

    assert review is not None
    assert "passed" in review
    assert "decision" in review

    print(f"✓ Web search review: decision={review['decision']}, "
          f"passed={review['passed']}")

    # Test with suspicious content
    claims2 = ["According to a study I conducted, this is 100% effective"]
    sources2 = []

    review2 = await wrapper.review_web_search(claims2, sources2)

    assert review2 is not None
    assert review2["passed"] is False or review2["decision"] == "conditional"

    print(f"✓ Suspicious content review: decision={review2['decision']}, "
          f"passed={review2['passed']}")
    print()

    return True


async def test_wrapper_disabled():
    """Test wrapper when disabled."""
    print("=" * 60)
    print("TEST 7: Wrapper Disabled")
    print("=" * 60)

    wrapper = BrachyAgentMultiAgentWrapper()
    wrapper.enabled = False

    # Test process request
    result = await wrapper.process_request("Execute brachytherapy planning")

    assert result["routing"] is None
    assert result["pre_context"] is None

    print(f"[OK] Process request when disabled: {result}")

    # Test review
    review = await wrapper.review_treatment_plan(
        {"v100": 0.96},
        {"total_seeds": 12}
    )

    assert review is None

    print(f"[OK] Review when disabled: {review}")
    print()

    return True


async def test_integration_flow():
    """Test complete integration flow."""
    print("=" * 60)
    print("TEST 8: Integration Flow")
    print("=" * 60)

    wrapper = BrachyAgentMultiAgentWrapper()

    # Simulate a complete flow
    user_input = "Execute pancreatic cancer brachytherapy planning"

    # 1. Process request
    request_result = await wrapper.process_request(user_input)
    assert request_result["routing"] is not None

    print(f"1. Request routing: {request_result['routing'].intent}")

    # 2. Simulate planning execution (would happen in BrachyAgent)
    dose_metrics = {
        "v100": 0.96,
        "v150": 0.45,
        "v200": 0.18,
        "d90": 1.05,
        "max_dose": 1.8,
    }
    plan_info = {
        "total_seeds": 12,
        "num_trajectories": 2,
        "completed_steps": ["ctv_segmentation", "oar_segmentation",
                          "trajectory_planning", "seed_planning",
                          "dose_calculation", "dose_evaluation"],
    }

    # 3. Review the plan
    review = await wrapper.review_treatment_plan(dose_metrics, plan_info)
    assert review is not None

    print(f"2. Plan review: {review['decision']}")
    print(f"   Display: {review['display_text'][:100]}...")

    # 4. Check stats
    stats = wrapper.get_stats()
    assert stats["review_count"] >= 1

    print(f"3. Stats: review_count={stats['review_count']}, "
          f"pass_rate={stats['gate_pass_rate']:.2f}")
    print()

    return True


async def run_all_tests():
    """Run all Phase 3 tests."""
    print("\n" + "=" * 60)
    print("MULTI-AGENT SYSTEM PHASE 3 TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("Orchestrator Routing", test_orchestrator_routing),
        ("Orchestrator Review", test_orchestrator_review),
        ("Orchestrator Format", test_orchestrator_format),
        ("Wrapper Basic", test_wrapper_basic),
        ("Wrapper Review", test_wrapper_review),
        ("Wrapper Web Search", test_wrapper_web_search),
        ("Wrapper Disabled", test_wrapper_disabled),
        ("Integration Flow", test_integration_flow),
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
