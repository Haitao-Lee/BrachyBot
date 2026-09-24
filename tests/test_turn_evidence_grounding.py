"""The final reply must stay grounded in the tool evidence of the same turn.

Regression (2026-09-22): query_metrics(needle_seed_counts) returned "24
needles / 181 seeds" in the same turn, yet the final reply claimed "本轮没有
返回针道计数" and attributed the numbers to earlier conversation history.

Root causes:
1. The tool loop summed each read's per-contract coverage gaps into a
   turn-level "still missing" set. A spacing read declares only ["spacing"],
   so its gap poisoned the needle/seed aspects that a needle_seed_counts read
   had already answered.
2. coverage_followup_instruction then told the model "still missing:
   needle_count, seed_total, seeds_per_needle — Do NOT answer with that
   partial result", i.e. it actively denied the visible evidence.
3. Nothing grounded the final answer round in the turn's fresh tool facts,
   so a weak model over 240k tokens of history believed the instruction.
"""

from agent_runtime.answer_coverage import (
    ASPECT_OAR_DOSE,
    coverage_followup_instruction,
    direct_read_decision,
    required_metric_aspects,
    uncovered_metric_aspects,
)
from agent_runtime.llm_runtime import (
    _scrub_false_search_absence,
    same_turn_evidence_digest,
)


_QUESTION = "当前有多少枚穿刺针，每枚针有多少粒子，粒子之间有干涉吗"
_OAR_QUESTION = "那从每个器官受到的辐射来看呢"

# Mirrors tool_factory/viewer_command/query_metrics._METRIC_COVERAGE.
_INCIDENT_CONTRACTS = [
    {"covers": ["needle_count", "seed_total", "seeds_per_needle"]},
    {"covers": ["seed_total"]},
    {"covers": ["spacing"]},
    {"covers": ["dose", "ctv_volume", "oar_volume", "seed_total", "hu", "spacing"]},
]


def test_turn_level_gaps_use_the_union_of_all_reads():
    assert uncovered_metric_aspects(_QUESTION, _INCIDENT_CONTRACTS) == frozenset()
    covered, gaps = direct_read_decision(_QUESTION, _INCIDENT_CONTRACTS)
    assert covered is True
    assert gaps == frozenset()


def test_complementary_partial_reads_union_their_coverage():
    contracts = [
        {"covers": ["needle_count"]},
        {"covers": ["seed_total"]},
        {"covers": ["seeds_per_needle"]},
    ]
    covered, gaps = direct_read_decision(_QUESTION, contracts)
    assert covered is True
    assert gaps == frozenset()
    assert uncovered_metric_aspects(_QUESTION, contracts) == frozenset()


def test_only_partial_reads_leave_the_real_gaps():
    contracts = [{"covers": ["seed_total"]}, {"covers": ["spacing"]}]
    assert uncovered_metric_aspects(_QUESTION, contracts) == frozenset(
        {"needle_count", "seeds_per_needle"}
    )


def test_no_typed_reads_make_no_coverage_claims():
    assert uncovered_metric_aspects(_QUESTION, []) == frozenset()
    assert uncovered_metric_aspects(_QUESTION, None) == frozenset()


def test_oar_dose_questions_require_dose_not_organ_volume_evidence():
    assert required_metric_aspects(_OAR_QUESTION) == frozenset({ASPECT_OAR_DOSE})
    assert required_metric_aspects("What dose did each organ receive?") == frozenset({ASPECT_OAR_DOSE})
    assert required_metric_aspects(
        "What dose did each organ receive, and how many seeds are in the plan?"
    ) == frozenset({ASPECT_OAR_DOSE, "seed_total"})
    covered, gaps = direct_read_decision(
        _OAR_QUESTION,
        [{"covers": ["oar_volume", "dose"]}],
    )
    assert covered is False
    assert gaps == frozenset({ASPECT_OAR_DOSE})
    assert uncovered_metric_aspects(
        _OAR_QUESTION,
        [{"covers": ["oar_dose"]}],
    ) == frozenset()
    # Boundary-aware English matching must not treat "board" as "oar".
    assert required_metric_aspects("What dose is on the planning board?") == frozenset()


def test_oar_dose_coverage_gap_requests_the_typed_oar_dose_read():
    instruction = coverage_followup_instruction({ASPECT_OAR_DOSE})
    assert 'metric_type="oar_dose_metrics"' in instruction
    assert "organ volume" not in instruction.lower()


def test_coverage_instruction_never_denies_returned_evidence():
    text = coverage_followup_instruction(
        {"needle_count"}, covered={"seed_total", "seeds_per_needle"}
    )
    low = text.lower()
    assert "do not answer with that partial result" not in low
    assert "never claim they were not returned" in low
    assert "seed_total" in text
    assert "needle_count" in text
    assert "needle_seed_counts" in text


def test_coverage_instruction_is_silent_when_nothing_is_missing():
    assert coverage_followup_instruction(frozenset()) == ""


def test_evidence_digest_surfaces_this_turn_facts():
    digest = same_turn_evidence_digest(
        [
            (
                "query_metrics",
                "## 穿刺针与粒子分布 共 24 枚穿刺针，181 颗粒子。 | 针道 | 粒子数 | | 针道 1 | 13 |",
            )
        ]
    )
    assert "THIS TURN" in digest
    assert "query_metrics" in digest
    assert "24" in digest and "181" in digest
    assert "Never claim" in digest


def test_evidence_digest_is_empty_without_evidence():
    assert same_turn_evidence_digest([]) == ""
    assert same_turn_evidence_digest(None) == ""


_INCIDENT_DENIAL = (
    "结论先说：你问的三项里，只有「干涉」相关的部分能得到间接线索，而「穿刺针数量」和"
    "「每枚针的粒子数」本轮没有返回可核实结果。\n"
    "1. 有多少枚穿刺针 —— 未获得 本轮没有返回针道计数。\n"
    "2. 每枚针有多少粒子 —— 未获得 本轮没有返回按针分组的粒子列表，只有总量/分针数这类字段都没出现在结果里。\n"
    "会话历史里出现过互相矛盾的数字（导板信息显示 22 条计划针道，早期规划输出里出现过 24 条针道 / "
    "181 枚粒子），这些都不是本轮工具返回的，所以不能作为当前规划的确切计数引用。\n"
    "剂量学叠加：V150=62.41% 说明靶区内有较大体积处于高剂量区。\n"
)

_NEEDLE_STEPS = [
    {
        "type": "tool",
        "tool": "query_metrics",
        "status": "done",
        "result": (
            "## 穿刺针与粒子分布 共 24 枚穿刺针，181 颗粒子。 "
            "| 针道 | 粒子数 | | 针道 1 | 13 |"
        ),
    }
]


def test_false_metric_absence_claims_are_scrubbed_when_data_present():
    out = _scrub_false_search_absence(_INCIDENT_DENIAL, _NEEDLE_STEPS)
    assert "没有返回针道计数" not in out
    assert "没有返回按针分组的粒子列表" not in out
    assert "都不是本轮工具返回" not in out
    assert "本轮没有返回可核实结果" not in out
    assert "都没有出现在结果里" not in out
    assert "V150=62.41%" in out


def test_honest_gap_claims_survive():
    text = (
        "物理/几何干涉：判断依据是源间距和针间距，本轮没有返回，所以无法判断。\n"
        "剂量学叠加：V150=62.41% 说明靶区内有较大体积处于高剂量区。\n"
    )
    out = _scrub_false_search_absence(text, _NEEDLE_STEPS)
    assert "本轮没有返回" in out
    assert "V150=62.41%" in out


def test_absence_claims_survive_when_the_data_was_really_missing():
    text = "1. 有多少枚穿刺针 —— 未获得 本轮没有返回针道计数。"
    steps = [
        {
            "type": "tool",
            "tool": "query_metrics",
            "status": "done",
            "result": "## 当前病例剂量指标 | V100 | 90.54% |",
        }
    ]
    out = _scrub_false_search_absence(text, steps)
    assert "没有返回针道计数" in out
