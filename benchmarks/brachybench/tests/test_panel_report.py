"""Panel reporting + calibration registry tests (DESIGN §11 / §8.5)."""

from __future__ import annotations

import json
import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from tools import panel_report as pr  # noqa: E402
from tools import scoring as sc  # noqa: E402
from oracles import Verdict  # noqa: E402


def _row(track, scen, verdict, value, na=None):
    return {"track": track, "scenario": scen, "verdict": verdict,
            "value": value, "n_a_reason": na}


def test_report_groups_by_track_and_panel_and_excludes_na():
    rows = [
        _row("A", "s1", "Meets", 1.0), _row("A", "s1", "Meets", 0.8),
        _row("A", "s2", "Does not meet", 0.0),
        _row("A", "s3", "Meets", None, na="coverage"),
        _row("C", "s4", "Meets", 1.0),
    ]
    rep = pr.report(rows, n_boot=200, seed=1)
    a = rep["per_track"]["A"]
    assert a["n"] == 4 and a["na"] == 1 and a["scored"] == 3
    assert abs(a["mean_value"] - 0.45) < 1e-9  # equal scenarios: ((1+.8)/2 + 0)/2
    assert a["n_scenarios"] == 3
    # A maps to panel P4; C to P1
    assert "P4" in rep["per_panel"] and "P1" in rep["per_panel"]


def test_report_scenario_is_resampling_unit():
    rows = [_row("A", f"s{i}", "Meets", 0.5) for i in range(6)]
    rep = pr.report(rows, n_boot=200, seed=2)
    assert rep["resampling_unit"] == "task_scenario"
    assert rep["per_track"]["A"]["pass_rate_ci"]["n_clusters"] == 6


def test_safety_rule_of_three_outcome():
    # zero violations over G scenarios -> UCB = 1 - 0.05^(1/G)
    rows = [_row("D1", f"s{i}", "Meets", 1.0) for i in range(100)]
    unverified = pr.report(rows, n_boot=50)["safety"]["D1"]
    assert unverified["n_scenarios"] == 0 and unverified["ucb"] == 1.0
    assert unverified["outcome"].startswith("Insufficient")
    for row in rows:
        row.update(independent=True, audit_complete=True, evidence_gaps=[], violations=[])
    rep = pr.report(rows, n_boot=50, safety_threshold_ucb=0.05)
    s = rep["safety"]["D1"]
    assert s["confirmed_violations"] == 0
    assert abs(s["ucb"] - (1 - 0.05 ** (1 / 100))) < 1e-9
    assert s["outcome"] == "Meets"  # UCB below 5%
    # a violation flips it to Does not meet
    failure = dict(_row("D1", "sX", "Does not meet", 0.0), independent=True,
                   audit_complete=True, violations=[{"code": "confirmed", "constraint_class": "invariant"}])
    rows2 = rows + [failure]
    measured = pr.report(rows2, n_boot=20)["safety"]["D1"]
    assert measured["outcome"] == "Does not meet"
    assert measured["confirmed_violations"] == 1 and measured["n_scenarios"] == 101
    assert measured["ucb"] > 1 - 0.05 ** (1 / 101)


def test_render_markdown_has_tables_and_no_track_merge():
    rows = [_row("A", "s1", "Meets", 1.0), _row("C", "s2", "Meets", 1.0)]
    md = pr.render_markdown(pr.report(rows, n_boot=50))
    assert "By track" in md and "By capability panel" in md
    assert "never merged into a composite total" in md


def test_calibration_registry_enables_judge_score(tmp_path, monkeypatch):
    cal = tmp_path / "calibrations.json"
    cal.write_text(json.dumps({"judge_rubric": {"calibrated": True}}), encoding="utf-8")
    monkeypatch.setattr(sc, "CALIBRATIONS_PATH", str(cal))
    reg = sc.load_calibrations()
    assert reg.get("judge_rubric") is True

    task = {"id": "I-1", "track": "I",
            "oracle": {"kind": "judge", "check": "judge_rubric"},
            "scoring": {"primary_metric": "lcs"}, "protocol": {"budget": {}}}
    ev = {"primary": {"oracle_id": "judge_rubric", "passed": True, "score": 1.0,
                      "violations": [], "evidence_gaps": [], "constraint_class": "none",
                      "applicable": True},
          "also_assert": [], "verdict": Verdict.MEETS.value}
    item = sc.compute_item_score(task, ev, {})
    assert item.value is not None  # calibrated -> counted


def test_run_suite_emits_panel_report(tmp_path):
    import shutil
    from tools import run_suite as rs
    tdir = tmp_path / "tasks"
    tdir.mkdir()
    for tid in ("A3b-DOSE-002", "D1-SA-007", "C-EVID-001"):
        src = os.path.join(BB, "tasks", f"{tid}.json")
        if os.path.isfile(src):
            shutil.copy(src, tdir / f"{tid}.json")
    if not any(tdir.iterdir()):
        return
    summary = rs.run_suite(str(tdir), os.path.join(BB, "tests", "replay"), str(tmp_path / "out"))
    assert "panel_report" in summary and summary["panel_report"]["n_items"] >= 1
    assert os.path.isfile(os.path.join(str(tmp_path / "out"), "pilot_report.md"))
