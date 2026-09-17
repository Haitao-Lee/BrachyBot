"""Coverage boundary between a typed direct-read result and the user question.

The direct-read fast path may only replace the normal synthesis/review loop
when the read result demonstrably covers every data aspect the user asked
for.  A question about needles and per-needle seed counts is not covered by a
total seed count.
"""

from agent_runtime.answer_coverage import (
    contract_covers_turn,
    direct_read_decision,
    missing_metric_aspects,
    required_metric_aspects,
)


def test_reported_question_requires_needle_count_and_per_needle_breakdown():
    message = "现在有多少枚穿刺针，每枚穿刺针分别有多少粒子"
    contract = {"mode": "direct_read", "covers": ["seed_total"]}

    assert required_metric_aspects(message) == frozenset(
        {"needle_count", "seed_total", "seeds_per_needle"}
    )
    assert missing_metric_aspects(message, contract) == frozenset(
        {"needle_count", "seeds_per_needle"}
    )


def test_needle_seed_counts_contract_covers_the_reported_question():
    message = "现在有多少枚穿刺针，每枚穿刺针分别有多少粒子"
    contract = {
        "mode": "direct_read",
        "covers": ["needle_count", "seed_total", "seeds_per_needle"],
    }

    assert missing_metric_aspects(message, contract) == frozenset()
    assert contract_covers_turn(message, contract) is True


def test_total_seed_question_is_covered_by_seed_count():
    message = "现在总共有多少颗粒子？"
    contract = {"mode": "direct_read", "covers": ["seed_total"]}

    assert required_metric_aspects(message) == frozenset({"seed_total"})
    assert contract_covers_turn(message, contract) is True


def test_needle_only_question_requires_needle_count():
    message = "当前病例有多少枚穿刺针？"
    contract = {"mode": "direct_read", "covers": ["seed_total"]}

    assert required_metric_aspects(message) == frozenset({"needle_count"})
    assert missing_metric_aspects(message, contract) == frozenset({"needle_count"})


def test_per_needle_question_without_total_count_still_requires_breakdown():
    message = "每枚针道分别有多少颗粒子"
    contract = {"mode": "direct_read", "covers": ["seed_total"]}

    assert missing_metric_aspects(message, contract) == frozenset(
        {"needle_count", "seeds_per_needle"}
    )


def test_english_breakdown_question_requires_the_same_aspects():
    message = "How many needles are there and how many seeds are on each needle?"
    contract = {"mode": "direct_read", "covers": ["seed_total"]}

    assert missing_metric_aspects(message, contract) == frozenset(
        {"needle_count", "seeds_per_needle"}
    )


def test_unmodeled_questions_keep_the_existing_fast_path():
    contract = {"mode": "direct_read", "covers": ["dose"]}

    assert required_metric_aspects("当前病例的 D90 是多少？") == frozenset()
    assert contract_covers_turn("当前病例的 D90 是多少？", contract) is True


def test_contract_without_coverage_declaration_preserves_fast_path():
    """Non-metric tools never declared coverage; their behavior must not change."""

    assert contract_covers_turn("有多少枚穿刺针？", {"mode": "direct_read"}) is True
    assert contract_covers_turn("有多少枚穿刺针？", {}) is True
    assert contract_covers_turn("有多少枚穿刺针？", None) is True


def test_distribution_wording_requires_a_breakdown():
    message = "给我看一下每个针道的粒子分布"

    assert "seeds_per_needle" in required_metric_aspects(message)


def test_per_seed_attribute_question_does_not_force_the_distribution_metric():
    """A per-seed dose/position question is not a needle distribution ask."""

    assert required_metric_aspects("每枚粒子的剂量是多少") == frozenset()
    assert required_metric_aspects("show the dose of each seed") == frozenset()


def test_partial_metric_keeps_review_and_names_the_gap():
    message = "现在有多少枚穿刺针，每枚穿刺针分别有多少粒子"
    contracts = [{"mode": "direct_read", "covers": ["seed_total"]}]

    covered, gaps = direct_read_decision(message, contracts)

    assert covered is False
    assert gaps == frozenset({"needle_count", "seeds_per_needle"})


def test_a_later_complete_metric_read_satisfies_the_turn():
    message = "现在有多少枚穿刺针，每枚穿刺针分别有多少粒子"
    contracts = [
        {"mode": "direct_read", "covers": ["seed_total"]},
        {
            "mode": "direct_read",
            "covers": ["needle_count", "seed_total", "seeds_per_needle"],
        },
    ]

    covered, gaps = direct_read_decision(message, contracts)

    assert covered is True
    assert gaps == frozenset()
