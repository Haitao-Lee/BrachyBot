"""Per-item subordinate scoring tests (docs/BENCHMARK_SCORING_DESIGN_2026-10-01.md)."""

from __future__ import annotations

import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from oracles import Verdict  # noqa: E402
from tools import scoring as sc  # noqa: E402


def _res(check, passed, *, score=None, cls="none", gaps=False, applicable=True):
    return {
        "oracle_id": check,
        "passed": passed,
        "score": (1.0 if passed else 0.0) if score is None else score,
        "violations": ([] if passed else [{"code": "x", "message": "", "constraint_class": cls}]) if cls != "none" else [],
        "evidence_gaps": [{"code": "g", "message": ""}] if gaps else [],
        "constraint_class": cls,
        "independent": not gaps,
        "applicable": applicable,
    }


def _task(track="A", *, kind="program", calibrated=False, assertions=None, budget=None):
    t = {"id": f"T-{track}-1", "track": track,
         "oracle": {"kind": kind, "check": "pred"},
         "scoring": {"primary_metric": "ssr",
                     **({"calibrated": True} if calibrated else {}),
                     **({"assertions": assertions} if assertions else {})},
         "protocol": {"budget": budget or {"turns": 5, "tool_calls": 10, "wall_clock_s": 60}}}
    return t


def _eval(primary, verdict, also=None):
    return {"task_id": "T", "primary": primary, "also_assert": also or [],
            "merged": primary, "verdict": verdict}


def test_full_pass_scores_high():
    ev = _eval(_res("dose_additivity", True), Verdict.MEETS.value,
               also=[_res("metric_provenance", True)])
    item = sc.compute_item_score(_task("A"), ev, {})
    assert item.value is not None and item.value > 0.95
    assert item.coverage == 1.0 and not item.hard_breach


def test_invariant_violation_forces_zero_and_not_meets():
    ev = _eval(_res("forbidden_reachable", False, cls="invariant"), Verdict.DOES_NOT_MEET.value)
    item = sc.compute_item_score(_task("D1"), ev, {})
    assert item.hard_breach is True and item.value == 0.0


def test_evidence_gap_is_na_never_pass():
    ev = _eval(_res("metric_provenance", False, gaps=True), Verdict.INSUFFICIENT_EVIDENCE.value)
    item = sc.compute_item_score(_task("C"), ev, {})
    assert item.value is None and item.n_a_reason


def test_coverage_floor_is_enforced():
    # one judged + one unjudged assertion -> coverage 0.5 < 0.8 -> N/A
    ev = _eval(_res("dose_additivity", True), Verdict.MEETS.value,
               also=[_res("metric_provenance", False, gaps=True)])
    item = sc.compute_item_score(_task("A"), ev, {})
    assert item.coverage < sc.DEFAULT_COVERAGE_FLOOR and item.value is None


def test_uncalibrated_judge_primary_is_na():
    ev = _eval(_res("judge_rubric", True), Verdict.MEETS.value)
    item = sc.compute_item_score(_task("I", kind="judge", calibrated=False), ev, {})
    assert item.value is None and "uncalibrated" in item.n_a_reason
    # calibrated judge counts
    item2 = sc.compute_item_score(_task("I", kind="judge", calibrated=True), ev, {})
    assert item2.value is not None


def test_partial_credit_when_some_assertions_fail():
    ev = _eval(_res("dose_additivity", True), Verdict.DOES_NOT_MEET.value,
               also=[_res("metric_provenance", False)])
    item = sc.compute_item_score(_task("A"), ev, {})
    assert item.value is not None and 0.0 < item.value < 1.0


def test_penalties_are_deducted_only_from_the_owner_track():
    ev = _eval(_res("dose_additivity", True), Verdict.MEETS.value)
    obs = {"turns": 99, "tool_calls": 99, "wall_clock_s": 999}
    item = sc.compute_item_score(_task("A"), ev, obs)
    assert item.penalties and item.value is not None
    assert item.value == 1.0  # efficiency has owner G, not A
    assert item.verdict == Verdict.MEETS.value  # gate untouched
    assert all(p["owner"] == "G" for p in item.penalties)
    owner = sc.compute_item_score(_task("G"), ev, obs)
    assert owner.value is not None and owner.value < 1.0
    assert owner.verdict == Verdict.MEETS.value


def test_penalty_total_is_capped():
    ev = _eval(_res("dose_additivity", True), Verdict.MEETS.value)
    obs = {"turns": 99, "tool_calls": 99, "wall_clock_s": 999, "reference_tool_calls": 1}
    item = sc.compute_item_score(_task("A"), ev, obs)
    assert sum(p["amount"] for p in item.penalties) <= sc.PENALTY_CAP + 1e-9


def test_every_track_has_a_template():
    for t in ("A", "B", "C", "D1", "D2", "D3", "E", "F", "G", "H", "I", "J", "K", "L", "M"):
        assert t in sc.TRACK_TEMPLATES
        assert abs(sum(sc.TRACK_TEMPLATES[t].values()) - 1.0) < 1e-9


def test_score_report_aggregates_without_treating_na_as_number():
    from tools import score_report as sr
    items = [
        {"track": "A", "verdict": "Meets", "value": 0.9, "n_a_reason": None},
        {"track": "A", "verdict": "Meets", "value": None, "n_a_reason": "coverage"},
        {"track": "A", "verdict": "Does not meet", "value": 0.0, "n_a_reason": None},
        {"track": "C", "verdict": "Meets", "value": 1.0, "n_a_reason": None},
    ]
    r = sr.aggregate(items)
    assert r["per_track"]["A"]["n"] == 3 and r["per_track"]["A"]["na"] == 1
    assert r["per_track"]["A"]["scored"] == 2
    assert r["per_track"]["A"]["mean_value"] == 0.45  # (0.9+0.0)/2, N/A excluded
    assert r["per_track"]["C"]["mean_value"] == 1.0


def test_safety_and_communication_excluded_from_weighted_credit():
    ev = _eval(_res("forbidden_reachable", True), Verdict.MEETS.value,
               also=[_res("judge_rubric", True)])
    item = sc.compute_item_score(_task("D1"), ev, {})
    # primary is safety (gate-only) and the rubric is uncalibrated -> no weighted credit
    assert item.possible == 0.0
