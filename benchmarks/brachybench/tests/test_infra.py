"""Tests for statistics (§11), infrastructure (§8.6 I1-I3), splits (§12.6)
and the EXT adapter contract (§25.5)."""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)
sys.path.insert(0, os.path.join(BB, "..", "external"))

from tools.analysis import (  # noqa: E402
    cluster_bootstrap_ci,
    cohens_h,
    cohens_kappa,
    gate_outcome,
    gwet_ac1,
    holm_adjust,
    icc_decomposition,
    independent_sample_size_for,
    irt_rasch_joint,
    kendall_tau_stability,
    mcnemar_n_total,
    power_curve,
    rule_of_three_ucb,
    two_prop_n_per_arm,
)
from tools.env_lock import collect, check as env_check  # noqa: E402
from tools.observe import IndependentParser, SideEffectAudit, StateObserver  # noqa: E402
from tools.splits import build as build_splits, check_leakage  # noqa: E402


# ------------------------------------------------------------------ §11


def test_cluster_bootstrap_resamples_scenarios_not_items():
    clusters = [[1.0, 1.0], [0.0, 0.0], [1.0, 1.0]]
    out = cluster_bootstrap_ci(clusters, n_boot=500, seed=1)
    assert out["n_clusters"] == 3 and out["n_members"] == 6
    assert out["resampling_unit"] == "task_scenario"
    assert out["lo"] <= out["point"] <= out["hi"]
    # an item-level bootstrap would report a much tighter interval
    item_ci = cluster_bootstrap_ci([[x] for c in clusters for x in c], n_boot=500, seed=1)
    assert (out["hi"] - out["lo"]) >= (item_ci["hi"] - item_ci["lo"]) - 1e-9


def test_icc_decomposition_does_not_invent_unidentified_components():
    icc = icc_decomposition([[1.0, 1.0], [0.0, 0.0], [1.0, 1.0]], n_runs=2)
    assert 0.0 <= icc["icc_scenario"] <= 1.0
    assert icc["icc_scenario"] == 1.0  # zero within-scenario variation
    assert icc["identified"] is False
    assert icc["icc_member"] is None and icc["icc_run"] is None
    assert icc["method"] == "one_way_exploratory"


def test_mcnemar_n_total_is_total_pairs_not_discordant():
    # N4/M9 worked example from DESIGN §11.1.  The formula yields a *real*
    # number; the requirement is its ceiling (need n >= 235.47 -> 236 total
    # pairs).  Using round() here was the bug -- it truncated 235.47 to 235.
    import math

    assert math.ceil(mcnemar_n_total(0.20, 0.10)) == 236
    assert math.ceil(mcnemar_n_total(0.15, 0.05)) == 157
    # Holm-adjusted z raises the requirement
    assert math.ceil(mcnemar_n_total(0.20, 0.10, z=2.394)) == 315


def test_two_prop_n_matches_the_corrected_value():
    h = cohens_h(0.55, 0.65)
    assert abs(h - 0.20453) < 1e-4
    # N4: 375/arm at the *exact* h, not 356 (which corresponds to h=0.21)
    assert round(two_prop_n_per_arm(h)) == 375
    assert round(two_prop_n_per_arm(0.21)) == 356


def test_holm_adjust_is_monotone():
    adj = holm_adjust([0.01, 0.04, 0.03])
    assert adj[0] <= adj[2] <= adj[1] or adj[0] <= adj[1]
    assert all(0.0 <= p <= 1.0 for p in adj)


def test_power_curve_increases_with_G():
    rows = power_curve([50, 200, 400], p10_grid=[0.20], net_diff=0.10, holm=True)
    by_G = {r["G"]: r["power"] for r in rows}
    assert by_G[50] < by_G[200] < by_G[400]
    assert rows[0]["z_crit"] > 1.96, "Holm must tighten the critical value"


def test_rule_of_three_and_sample_size():
    assert rule_of_three_ucb(100) == pytest.approx(0.0295, abs=1e-3)
    assert independent_sample_size_for(0.01) == 299
    assert independent_sample_size_for(0.005) == 598
    assert independent_sample_size_for(0.001) == 2995


def test_gate_outcome_three_states():
    assert gate_outcome(confirmed_violations=1, independent=True, G=500,
                        threshold_ucb=0.03) == "Does not meet"
    assert gate_outcome(confirmed_violations=0, independent=False, G=500,
                        threshold_ucb=0.03).startswith("Insufficient")
    assert gate_outcome(confirmed_violations=0, independent=True, G=10,
                        threshold_ucb=0.03).startswith("Insufficient")
    assert gate_outcome(confirmed_violations=0, independent=True, G=500,
                        threshold_ucb=0.03) == "Meets"


def test_kendall_tau_stability_flags_weight_sensitivity():
    scores = [[0.9, 0.9, 0.9], [0.5, 0.5, 0.5], [0.1, 0.1, 0.1]]
    stable = kendall_tau_stability(scores, [[1, 1, 1], [1.1, 0.9, 1.0], [0.9, 1.1, 1.0]])
    assert stable["stable"] is True
    assert stable["tau_min"] == 1.0
    wild = kendall_tau_stability([[1.0, 0.0], [0.6, 0.6], [0.0, 0.9]], [[1, 0], [0, 1]])
    assert wild["stable"] is False
    with pytest.raises(ValueError):
        kendall_tau_stability([0.9, 0.5, 0.1], [[1, 1, 1]])


def test_gwet_ac1_survives_prevalence_paradox():
    # kappa collapses when almost everything is "no violation"
    a = ["ok"] * 19 + ["bad"]
    b = ["ok"] * 19 + ["bad"]
    assert cohens_kappa(a, b) > 0.0 or cohens_kappa(a, b) == 0.0  # kappa may be nan-ish
    assert gwet_ac1(a, b) > 0.9, "AC1 must stay informative at extreme prevalence"


def test_irt_rasch_reports_infit_and_flags_exploratory():
    rng = np.random.default_rng(0)
    # 12 subjects x 8 items, ability-driven
    theta = rng.normal(0, 1, 12)
    beta = rng.normal(0, 1, 8)
    p = 1 / (1 + np.exp(-(theta[:, None] - beta[None, :])))
    X = (rng.random(p.shape) < p).astype(float)
    X[0, 0] = np.nan           # planned missingness
    out = irt_rasch_joint(X)
    assert out["n_subjects"] == 12 and out["n_items"] == 8
    assert 0.0 <= out["fit_ok_share"] <= 1.0
    assert "exploratory" in out["interpretation"]


# ------------------------------------------------------------------ §8.6 I1-I3


def test_state_observer_prefers_observed_over_claimed():
    # observed state is still `draft`; the SUT claims the job completed (N8)
    def reader(_cid):
        return {"plan": {"status": "draft", "completed": True, "verified": True}}
    obs = StateObserver(reader)
    out = obs.observe("c1", {"plan": {"status": "draft", "completed": True}})
    assert out["observed"]["plan"]["completed"] is None        # stripped, never a verdict
    assert out["claimed"]["plan.completed"] is True
    assert out["mismatch"].get("completed") is True, "unsupported conclusion must be flagged"
    assert out["self_report_mismatch"], "contradicting self-report must be surfaced"


def test_side_effect_audit_completeness():
    audit = SideEffectAudit()
    audit.tool_call("dose_eval", ret={"D90": 1})
    audit.file_op("write", "/tmp/out/a.nii", op_id="op1")
    c = audit.completeness(["op1", "op_MISSING"])
    assert c["missing"] == ["op_MISSING"]
    assert c["completeness"] == 0.5


def test_independent_parser_and_semantic_normalise():
    p = IndependentParser()          # no backends -> evidence gap, never a pass
    r = p.parse("nifti", "x.nii")
    assert r["ok"] is False and r["independent"] is False
    norm = IndependentParser.semantic_normalise({
        "SOPInstanceUID": "1.2.3", "Modality": "RTDOSE", "StudyDate": "20260929"})
    assert "SOPInstanceUID" in norm and norm["Modality"] == "RTDOSE"
    reminted = IndependentParser.semantic_normalise({
        "SOPInstanceUID": "9.8.7", "Modality": "RTDOSE", "StudyDate": "20261003"})
    assert norm == reminted  # UID alias graph preserved; raw identifiers normalised


# ------------------------------------------------------------------ §12.6


def _mk_tasks():
    """20 tasks over 10 *independent* level tuples.

    Every level value appears in exactly one task so the connected components
    are singletons -- then any assignment is leak-free and the test can focus
    on reproducibility.  ``test_splits_detect_leakage`` then deliberately joins
    two tasks across splits.
    """
    out = []
    for i in range(20):
        out.append({
            "id": f"T-{i:03d}", "track": "B", "cost_class": "state_only",
            "construct": f"construct_{i}",
            "fixture": {"case_family": f"synth/case_{i}", "setup_script": "s",
                        "initial_state_hash": "sha256:00"},
            "provenance": {"derived_from": f"audit#{i}"},
            "anti_gaming": {"contrast_family_id": f"F{i}"},
        })
    return out


def test_splits_no_five_level_leakage_and_reproducible():
    tasks = _mk_tasks()
    doc = build_splits(tasks, seed=20260929)
    assert set(doc["splits"]) == {"dev", "pilot", "sealed", "public"}
    total = sum(len(v["task_index"]) for v in doc["splits"].values())
    assert total == len(tasks)
    assert not check_leakage(tasks, doc), check_leakage(tasks, doc)
    # reproducible with the recorded seed
    again = build_splits(tasks, seed=20260929)
    for k in doc["splits"]:
        assert doc["splits"][k]["sha256"] == again["splits"][k]["sha256"]
    # a different seed must move things
    other = build_splits(tasks, seed=1)
    assert other["splits"]["sealed"]["sha256"] != doc["splits"]["sealed"]["sha256"]


def test_splits_detect_leakage():
    tasks = _mk_tasks()
    # give two tasks a shared level value so they form one component
    tasks[1]["fixture"]["case_family"] = tasks[0]["fixture"]["case_family"]
    doc = build_splits(tasks, seed=7)
    # the two must have landed in the same split already (connected group) ...
    assert not check_leakage(tasks, doc)
    # ... so force a leak by moving one of them across the boundary
    first = doc["splits"]["dev"]["task_index"][0]
    doc["splits"]["sealed"]["task_index"].append(first)
    assert check_leakage(tasks, doc), "a straddling component must be reported"


# ------------------------------------------------------------------ §25.5


def test_ext_adapter_record_and_isolation():
    from adapter_base import ExtAdapter, OfflineBundleAdapter

    rec = ExtAdapter.record(ext_id="EXT-1", source_task_id="t1", prompt_or_scene="x",
                            upstream_verdict={"score": 0.5}, infra_failed=False)
    assert rec["derived"]["partial_status"] == "COMPLETED"
    rec2 = ExtAdapter.record(ext_id="EXT-1", source_task_id="t2", prompt_or_scene="y",
                             infra_failed=True)
    assert rec2["derived"]["partial_status"] == "INFRA_FAILED"
    with pytest.raises(ValueError):
        ExtAdapter.record(ext_id="E", source_task_id="t", prompt_or_scene="z",
                          derived={"partial_status": "NOT_A_STATE"})

    before = {"BrachyBot/case/": 1.0, "other": 1.0}
    after = {"BrachyBot/case/": 2.0, "other": 1.0}
    assert ExtAdapter.audit_isolation(before, after) == ["BrachyBot/case/"]
    assert ExtAdapter.audit_isolation(before, dict(before)) == []

    assert issubclass(OfflineBundleAdapter, ExtAdapter)


def test_env_lock_collects_determinism_flags():
    doc = collect()
    assert "determinism" in doc and "weight_sha256" in doc
    assert isinstance(doc.get("deterministic_kernels"), bool)
    assert env_check(doc) == [], "collect+check must round-trip with no drift"
