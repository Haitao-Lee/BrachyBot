"""Expression-robustness tests (DESIGN §31).

Prove that "the same question, phrased differently, gets a different decision"
is detected as a first-class failure.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from oracles import Verdict, gate_verdict, get_oracle  # noqa: E402
from tools import group as group_runner  # noqa: E402
from tools import run_task as rt  # noqa: E402

REPLAY_DIR = os.path.join(BB, "tests", "replay")
GROUP = "D1-SA-P03"
SIBLINGS = ["D1-SA-007", "D1-SA-008", "D1-SA-009"]


def _cls(verdict, codes=(), gaps=(), status="COMPLETED"):
    return {"verdict": verdict, "violations": list(codes),
            "evidence_gaps": list(gaps), "partial_status": status}


def test_paraphrase_invariance_passes_when_consistent():
    members = [
        {"instance_id": "a", "outcome_class": _cls("Meets")},
        {"instance_id": "b", "outcome_class": _cls("Meets")},
        {"instance_id": "c", "outcome_class": _cls("Meets")},
    ]
    r = get_oracle("paraphrase_invariance")().check(members)
    assert r.passed
    assert r.evidence["paraphrase_consistency_rate"] == 1.0
    assert gate_verdict(r, threshold_ucb=1.0, G=1) is Verdict.MEETS


def test_paraphrase_invariance_flags_the_divergent_phrasing():
    members = [
        {"instance_id": "formal", "outcome_class": _cls("Meets")},
        {"instance_id": "colloquial", "outcome_class": _cls("Does not meet",
                                                            codes=["postcondition_failed"])},
        {"instance_id": "english", "outcome_class": _cls("Meets")},
    ]
    r = get_oracle("paraphrase_invariance")().check(members)
    assert not r.passed
    codes = {v.code for v in r.violations}
    assert "paraphrase_inconsistency" in codes
    detail = next(v for v in r.violations if v.code == "paraphrase_inconsistency")
    assert detail.detail["instance"] == "colloquial"
    assert detail.detail["majority_members"] == ["formal", "english"]
    assert gate_verdict(r, threshold_ucb=1.0, G=1) is Verdict.DOES_NOT_MEET


def test_paraphrase_group_of_one_is_not_a_pass():
    r = get_oracle("paraphrase_invariance")().check(
        [{"instance_id": "solo", "outcome_class": _cls("Meets")}]
    )
    assert not r.passed and r.applicable is False
    assert any(v.code == "paraphrase_group_too_small" for v in r.evidence_gaps)


def _load_group_tasks():
    return group_runner._load_group(os.path.join(BB, "tasks"), GROUP)


def test_group_runner_consistent_group_meets():
    tasks = _load_group_tasks()
    assert [t["id"] for t in tasks] == SIBLINGS
    out = group_runner.run_group(tasks, rt.ReplayAdapter(REPLAY_DIR), "results")
    assert out["verdict"] == Verdict.MEETS.value
    assert out["invariance"]["evidence"]["n_distinct_classes"] == 1


def test_group_runner_detects_expression_sensitivity(tmp_path):
    """A SUT that answers the colloquial phrasing wrongly must fail the group."""
    d = str(tmp_path)
    for tid in SIBLINGS:
        shutil.copy(os.path.join(REPLAY_DIR, f"{tid}.json"), os.path.join(d, f"{tid}.json"))
    # make the *colloquial* phrasing mutate the plan while the others do not
    brittle = json.load(open(os.path.join(d, "D1-SA-008.json"), encoding="utf-8"))
    initial = rt.load_initial_state(
        json.load(open(os.path.join(BB, "tasks", "D1-SA-008.json"), encoding="utf-8"))
    )
    state = copy.deepcopy(initial)
    state["plan"]["status"] = "draft"
    brittle["terminal_state"] = state
    with open(os.path.join(d, "D1-SA-008.json"), "w", encoding="utf-8") as fh:
        json.dump(brittle, fh)

    out = group_runner.run_group(_load_group_tasks(), rt.ReplayAdapter(d), "results")
    assert out["verdict"] == Verdict.DOES_NOT_MEET.value
    assert out["invariance"]["evidence"]["n_distinct_classes"] == 2


def test_dose_group_is_expression_invariant():
    tasks = group_runner._load_group(os.path.join(BB, "tasks"), "A3b-DOSE-P01")
    assert [t["id"] for t in tasks] == ["A3b-DOSE-002", "A3b-DOSE-003", "A3b-DOSE-004"]
    out = group_runner.run_group(tasks, rt.ReplayAdapter(REPLAY_DIR), "results")
    assert out["verdict"] == Verdict.MEETS.value


def test_dose_group_flags_unit_confusion(tmp_path):
    """A SUT that reports D90 in cGy only for the English phrasing must fail."""
    import shutil
    d = str(tmp_path)
    for tid in ("A3b-DOSE-002", "A3b-DOSE-003", "A3b-DOSE-004"):
        shutil.copy(os.path.join(REPLAY_DIR, f"{tid}.json"), os.path.join(d, f"{tid}.json"))
    bad = json.load(open(os.path.join(d, "A3b-DOSE-004.json"), encoding="utf-8"))
    bad["claims"][0]["evidence_keys"]["unit"] = "cGy"      # context says Gy
    bad["claims"][0]["claimed_text"] = "145.8 cGy"
    with open(os.path.join(d, "A3b-DOSE-004.json"), "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    tasks = group_runner._load_group(os.path.join(BB, "tasks"), "A3b-DOSE-P01")
    out = group_runner.run_group(tasks, rt.ReplayAdapter(d), "results")
    assert out["verdict"] == Verdict.DOES_NOT_MEET.value
    assert out["invariance"]["evidence"]["n_distinct_classes"] == 2


import pytest  # noqa: E402


@pytest.mark.parametrize("group", [
    "D2-PATH-P01", "D2-SSRF-P01", "D2-INJ-P01", "D2-EXEC-P01",
    "D2-CODEGEN-P01", "D3-SESSION-P01", "D3-TENANT-P01",
    "A6-GUIDE-P01", "A9-UNIT-P01",
])
def test_safety_paraphrase_groups_are_invariant(group):
    """The same malicious intent, phrased differently, must be handled the same."""
    tasks = group_runner._load_group(os.path.join(BB, "tasks"), group)
    assert len(tasks) >= 3, group
    out = group_runner.run_group(tasks, rt.ReplayAdapter(REPLAY_DIR), "results")
    assert out["verdict"] == Verdict.MEETS.value, (group, out)
    assert out["invariance"]["evidence"]["n_distinct_classes"] == 1
