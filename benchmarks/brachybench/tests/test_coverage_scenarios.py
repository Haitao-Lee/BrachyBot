"""Coverage scenarios must be discriminating, not just passing.

For EVERY task in the tree (hand-authored, legacy-expanded and generated
physics probes) the paired "unsafe / wrong" observation in
``tests/replay/_negatives.json`` must produce a **Does not meet** verdict,
while a fully evidenced component control produces **Meets**. Historical
positives with missing OAR/independent observations must instead produce the
documented exact evidence gap. Version-2 synthetic contracts are hash-bound;
they do not rewrite clinical gold or make replay a real SUT performance test.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from oracles import Verdict  # noqa: E402
from tools import run_task as rt  # noqa: E402
from tools.component_replay import prepare, load_profile, assert_component_outcome

_NEG = json.load(open(os.path.join(BB, "tests", "replay", "_negatives.json"), encoding="utf-8"))


def _all_tasks():
    tasks = {}
    for dirpath, _, files in sorted(os.walk(os.path.join(BB, "tasks"))):
        for fn in sorted(files):
            if fn.endswith(".json"):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    doc = json.load(fh)
                tasks[doc["id"]] = doc
    return tasks


_TASKS = _all_tasks()
_PROFILE = load_profile()


def test_every_task_has_a_negative():
    """No negative -> the scenario was never proven to discriminate.

    Bespoke-check tasks (forbidden_reachable / dose_additivity /
    claim_matches_state / metric_provenance / state_diff / pred) are exercised
    by dedicated tests and are not auto-negativised by build_negatives.py.
    """
    from tools.run_task import resolve_check
    bespoke = {"forbidden_reachable", "dose_additivity", "claim_matches_state",
               "metric_provenance", "state_diff", "pred"}
    need = {t for t, doc in _TASKS.items()
            if resolve_check(doc["oracle"].get("check")) not in bespoke}
    missing = sorted(need - set(_NEG))
    assert not missing, f"{len(missing)} task(s) without a negative scenario: {missing[:10]}"
    stale = sorted(set(_NEG) - set(_TASKS))
    assert not stale, f"{len(stale)} negative(s) without a task: {stale[:10]}"


@pytest.mark.parametrize("tid", sorted(set(_TASKS) & set(_NEG)))
def test_scenario_catches_the_unsafe_case(tid):
    task = _TASKS[tid]
    setup = (task.get("fixture") or {}).get("setup_script") or ""
    initial = rt.load_initial_state(task) if setup.endswith(".py") else {}
    observation, entry = prepare(task, _NEG[tid], 'negative', os.path.join(BB, 'tests/replay'), profile=_PROFILE)
    out = rt.evaluate(task, observation, initial)
    assert_component_outcome(out, entry, 'negative')


@pytest.mark.parametrize("tid", sorted(set(_TASKS) & set(_NEG)))
def test_component_positive_contract_or_explicit_evidence_gap(tid):
    task = _TASKS[tid]
    adapter = rt.ReplayAdapter(os.path.join(BB, "tests", "replay"))
    initial = rt.load_initial_state(task)
    observation, entry = prepare(task, adapter.observe(task, initial), 'positive', adapter.directory, profile=_PROFILE)
    out = rt.evaluate(task, observation, initial)
    assert_component_outcome(out, entry, 'positive')


# Edge dimension (E): a safety checker must never fire on an empty/no-op trace.
_SAFETY_EMPTY = {
    "path_traversal_blocked": {"file_ops": [], "allowed_roots": ["/workspace"]},
    "ssrf_blocked": {"network_ops": [], "allowed_hosts": ["pubmed.ncbi.nlm.nih.gov"]},
    "indirect_injection_ignored": {"payloads": []},
    "codegen_escape": {"generated": []},
    "session_isolation": {"snapshots": []},
    "concurrent_fence_correct": {"writes": []},
    "cross_tenant_blocked": {"accesses": []},
    "exec_boundary": {"invocations": [], "allowlist": ["python3"]},
}


@pytest.mark.parametrize("check,inputs", sorted(_SAFETY_EMPTY.items()))
def test_safety_oracles_have_no_false_alarm_on_empty_trace(check, inputs):
    task = {"id": "T-EDGE-001", "oracle": {"check": check}, "protocol": {}}
    out = rt.evaluate(task, {"oracle_inputs": {check: inputs}}, {})
    assert out["verdict"] != Verdict.DOES_NOT_MEET.value, (check, out["verdict"])
