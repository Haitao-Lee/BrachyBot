"""
Phase 2 Tests: Review Agents and Quality Gate
==============================================
Tests for PlanReviewer, FactChecker, SafetyGuardian, and QualityGate.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from communication.protocol import (
    AgentRole, AgentMessage, AgentResponse, MessageType,
    ReviewResult, GateResult, Priority
)
from agents.plan_reviewer import PlanReviewer
from agents.fact_checker import FactChecker
from agents.safety_guardian import SafetyGuardian
from quality.quality_gate import QualityGate


async def test_plan_reviewer():
    """Test PlanReviewer agent."""
    print("=" * 60)
    print("TEST 1: Plan Reviewer")
    print("=" * 60)

    reviewer = PlanReviewer()

    # Test with good dose metrics
    good_metrics = {
        "v100": 0.96,
        "v150": 0.45,
        "v200": 0.18,
        "d90": 1.05,
        "d95": 0.98,
        "max_dose": 1.8,
        "mean_dose": 0.95,
        "oar_metrics": {
            "duodenum": {"d2cc": 0.8, "max_dose": 1.1},
            "stomach": {"d2cc": 0.7, "max_dose": 1.0},
        },
    }

    message = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.PLAN_REVIEWER,
        message_type=MessageType.REVIEW,
        content={
            "dose_metrics": good_metrics,
            "plan_info": {"total_seeds": 12, "num_trajectories": 2,
                         "completed_steps": ["ctv_segmentation", "oar_segmentation",
                                           "trajectory_planning", "seed_planning",
                                           "dose_calculation", "dose_evaluation"]},
        },
    )

    response = await reviewer.handle_message(message)

    assert response.success is True
    assert isinstance(response.result, ReviewResult)
    assert response.result.decision in ["pass", "conditional", "reject"]
    assert response.result.score > 0

    print(f"✓ Good plan review: decision={response.result.decision}, "
          f"score={response.result.score:.1f}")
    print(f"  Concerns: {response.result.concerns}")
    print(f"  Suggestions: {response.result.suggestions}")

    # Test with poor dose metrics
    poor_metrics = {
        "v100": 0.75,  # Low coverage
        "v150": 0.65,  # High hot spots
        "v200": 0.35,
        "d90": 0.70,   # Low D90
        "d95": 0.60,
        "max_dose": 3.5,  # Very high
        "oar_metrics": {
            "duodenum": {"d2cc": 1.5, "max_dose": 2.0},  # Exceeds limit
        },
    }

    message2 = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.PLAN_REVIEWER,
        message_type=MessageType.REVIEW,
        content={
            "dose_metrics": poor_metrics,
            "plan_info": {"total_seeds": 8, "num_trajectories": 1},
        },
    )

    response2 = await reviewer.handle_message(message2)

    assert response2.success is True
    assert response2.result.score < response.result.score  # Should be lower
    assert len(response2.result.concerns) > len(response.result.concerns)

    print(f"\n✓ Poor plan review: decision={response2.result.decision}, "
          f"score={response2.result.score:.1f}")
    print(f"  Concerns: {response2.result.concerns}")
    print()

    return True


async def test_fact_checker():
    """Test FactChecker agent."""
    print("=" * 60)
    print("TEST 2: Fact Checker")
    print("=" * 60)

    checker = FactChecker()

    # Test with reliable sources
    message = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.FACT_CHECKER,
        message_type=MessageType.REVIEW,
        content={
            "claims": [
                "I-125 seeds are commonly used in brachytherapy",
                "V100 should be ≥95% for optimal coverage",
                "The AAPM TG-43 protocol is used for dose calculation",
            ],
            "sources": [
                "https://pubmed.ncbi.nlm.nih.gov/12345678",
                "https://www.nccn.org/guidelines/prostate",
                "https://www.aapm.org/pubs/reports/RPT_43",
            ],
        },
    )

    response = await checker.handle_message(message)

    assert response.success is True
    assert isinstance(response.result, ReviewResult)
    assert response.result.decision in ["pass", "conditional", "reject"]

    print(f"✓ Reliable sources check: decision={response.result.decision}, "
          f"score={response.result.score:.1f}")
    print(f"  Confidence: {response.result.confidence:.2f}")

    # Test with suspicious content
    message2 = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.FACT_CHECKER,
        message_type=MessageType.REVIEW,
        content={
            "claims": [
                "According to a study I conducted, this treatment is 100% effective",
                "Dr. Smith from [institution] found that...",
                "Recently published in [journal] shows...",
            ],
            "sources": [],
        },
    )

    response2 = await checker.handle_message(message2)

    assert response2.success is True
    assert len(response2.result.concerns) > 0  # Should flag hallucinations

    print(f"\n✓ Suspicious content check: decision={response2.result.decision}, "
          f"score={response2.result.score:.1f}")
    print(f"  Concerns: {response2.result.concerns}")
    print()

    return True


async def test_safety_guardian():
    """Test SafetyGuardian agent."""
    print("=" * 60)
    print("TEST 3: Safety Guardian")
    print("=" * 60)

    guardian = SafetyGuardian()

    # Test with safe plan
    message = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.SAFETY_GUARDIAN,
        message_type=MessageType.REVIEW,
        content={
            "dose_metrics": {
                "v100": 0.96,
                "max_dose": 1.8,
                "mean_dose": 0.95,
                "oar_metrics": {
                    "duodenum": {"max_dose": 1.1},
                },
            },
            "plan_info": {"total_seeds": 12, "num_trajectories": 2},
            "output_type": "treatment_plan",
        },
    )

    response = await guardian.handle_message(message)

    assert response.success is True
    assert isinstance(response.result, ReviewResult)
    assert response.result.decision in ["pass", "conditional", "reject"]

    print(f"✓ Safe plan check: decision={response.result.decision}, "
          f"score={response.result.score:.1f}")

    # Test with unsafe plan (extreme values)
    message2 = AgentMessage(
        sender=AgentRole.ROUTER,
        receiver=AgentRole.SAFETY_GUARDIAN,
        message_type=MessageType.REVIEW,
        content={
            "dose_metrics": {
                "v100": 0.60,  # Very low coverage
                "max_dose": 5.0,  # Very high dose
                "oar_metrics": {
                    "duodenum": {"max_dose": 3.0},
                    "stomach": {"max_dose": 2.5},
                    "spinal_cord": {"max_dose": 2.0},
                },
            },
            "plan_info": {"total_seeds": 4, "num_trajectories": 1},
            "output_type": "treatment_plan",
        },
    )

    response2 = await guardian.handle_message(message2)

    assert response2.success is True
    assert response2.result.score < response.result.score
    assert response2.result.decision in ["reject", "conditional"]

    print(f"\n✓ Unsafe plan check: decision={response2.result.decision}, "
          f"score={response2.result.score:.1f}")
    print(f"  Concerns: {response2.result.concerns}")
    print()

    return True


async def test_quality_gate():
    """Test QualityGate orchestration."""
    print("=" * 60)
    print("TEST 4: Quality Gate")
    print("=" * 60)

    # Create agents
    plan_reviewer = PlanReviewer()
    fact_checker = FactChecker()
    safety_guardian = SafetyGuardian()

    # Create quality gate
    gate = QualityGate(agents={
        "plan_reviewer": plan_reviewer,
        "fact_checker": fact_checker,
        "safety_guardian": safety_guardian,
    })

    # Test with treatment plan (mandatory review)
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

    gate_result = await gate.review("treatment_plan", good_plan)

    assert isinstance(gate_result, GateResult)
    assert gate_result.passed is True
    assert gate_result.decision in ["pass", "conditional"]
    assert len(gate_result.reviews) > 0

    print(f"✓ Good plan gate: decision={gate_result.decision}, "
          f"passed={gate_result.passed}")
    print(f"  Reviews: {len(gate_result.reviews)}")
    print(f"  Message:\n{gate_result.final_message}")

    # Test with poor plan
    poor_plan = {
        "dose_metrics": {
            "v100": 0.70,
            "d90": 0.65,
            "max_dose": 4.0,
            "oar_metrics": {
                "duodenum": {"d2cc": 1.5},
            },
        },
        "plan_info": {"total_seeds": 5, "num_trajectories": 1},
    }

    gate_result2 = await gate.review("treatment_plan", poor_plan)

    assert gate_result2.passed is False or gate_result2.decision == "conditional"
    assert len(gate_result2.reviews) > 0

    print(f"\n✓ Poor plan gate: decision={gate_result2.decision}, "
          f"passed={gate_result2.passed}")
    print(f"  Requires human review: {gate_result2.requires_human_review}")

    # Test with web search (fact check)
    web_content = {
        "claims": ["I-125 seeds have a half-life of 60 days"],
        "sources": ["https://pubmed.ncbi.nlm.nih.gov/12345"],
    }

    gate_result3 = await gate.review("web_search_medical", web_content)

    print(f"\n✓ Web search gate: decision={gate_result3.decision}, "
          f"passed={gate_result3.passed}")

    # Test stats
    stats = gate.get_stats()
    assert stats["total_reviews"] == 3

    print(f"\n✓ Gate stats: {stats}")
    print()

    return True


async def test_quality_gate_no_review():
    """Test QualityGate with non-reviewable content."""
    print("=" * 60)
    print("TEST 5: Quality Gate - No Review Needed")
    print("=" * 60)

    gate = QualityGate(agents={})

    # Test with non-reviewable content
    gate_result = await gate.review("general_chat", "Hello, how are you?")

    assert gate_result.passed is True
    assert gate_result.decision == "pass"
    assert len(gate_result.reviews) == 0

    print(f"✓ Non-reviewable content: decision={gate_result.decision}, "
          f"passed={gate_result.passed}")
    print()

    return True


async def run_all_tests():
    """Run all Phase 2 tests."""
    print("\n" + "=" * 60)
    print("MULTI-AGENT SYSTEM PHASE 2 TESTS")
    print("=" * 60 + "\n")

    tests = [
        ("Plan Reviewer", test_plan_reviewer),
        ("Fact Checker", test_fact_checker),
        ("Safety Guardian", test_safety_guardian),
        ("Quality Gate", test_quality_gate),
        ("Quality Gate - No Review", test_quality_gate_no_review),
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
