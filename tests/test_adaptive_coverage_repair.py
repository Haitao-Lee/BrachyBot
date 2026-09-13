from tool_factory.seed_plan.planning_pipeline import _coverage_repair_adaptive_policy


def test_promising_repair_gets_one_bounded_extension():
    policy = _coverage_repair_adaptive_policy(
        {
            "coverage_repair_seconds": 60,
            "coverage_repair_extension_seconds": 120,
            "coverage_repair_max_seconds": 180,
        },
        0.9,
        {
            "initial_coverage": 0.393,
            "final_coverage": 0.455,
            "added_needles": 3,
            "added_seeds": 0,
            "generated": 0,
            "stop_reason": "time_budget",
        },
    )
    assert policy["should_extend"] is True
    assert policy["base_seconds"] == 60.0
    assert policy["extension_seconds"] == 120.0
    assert policy["max_seconds"] == 180.0


def test_stagnant_repair_keeps_original_budget():
    policy = _coverage_repair_adaptive_policy(
        {},
        0.9,
        {
            "initial_coverage": 0.20,
            "final_coverage": 0.20,
            "added_needles": 0,
            "added_seeds": 0,
            "generated": 0,
            "stop_reason": "time_budget",
        },
    )
    assert policy["should_extend"] is False
    assert policy["decision_reason"] == "no_actionable_candidate"


def test_no_safe_positive_gain_never_gets_extension():
    policy = _coverage_repair_adaptive_policy(
        {},
        0.9,
        {
            "initial_coverage": 0.72,
            "final_coverage": 0.72,
            "added_needles": 0,
            "added_seeds": 0,
            "generated": 4,
            "stop_reason": "no_safe_positive_gain",
        },
    )
    assert policy["should_extend"] is False
    assert policy["decision_reason"] == "terminal_status:no_safe_positive_gain"


def test_target_reached_does_not_extend():
    policy = _coverage_repair_adaptive_policy(
        {},
        0.9,
        {
            "initial_coverage": 0.88,
            "final_coverage": 0.90,
            "added_needles": 1,
            "stop_reason": "target_reached",
        },
    )
    assert policy["should_extend"] is False
    assert policy["decision_reason"] == "target_reached"


def test_max_seconds_caps_the_extension():
    policy = _coverage_repair_adaptive_policy(
        {
            "coverage_repair_seconds": 60,
            "coverage_repair_extension_seconds": 120,
            "coverage_repair_max_seconds": 90,
        },
        0.9,
        {
            "initial_coverage": 0.4,
            "final_coverage": 0.5,
            "added_seeds": 2,
            "stop_reason": "round_budget",
        },
    )
    assert policy["should_extend"] is True
    assert policy["max_seconds"] == 90.0
    assert policy["extension_seconds"] == 30.0
