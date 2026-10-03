"""Execution-harness tests (``tools/run_task.py``).

These prove the *pipeline* exists and is wired to the real oracles: a task is
loaded, its frozen initial state is rebuilt, an adapter supplies an
observation, the oracle family scores it, a three-outcome verdict is produced,
and a schema-valid ``run_manifest`` is emitted.

The replay observations used here are **CI fixtures**, not benchmark data.
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)

from oracles import Verdict  # noqa: E402
from tools import run_task as rt  # noqa: E402
from tools.jsonschema_lite import validate  # noqa: E402

TASK_PATH = os.path.join(BB, "tasks", "D1-SA-007.json")
REPLAY_DIR = os.path.join(BB, "tests", "replay")


def _task():
    with open(TASK_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _initial():
    return rt.load_initial_state(_task())


def test_load_initial_state_matches_frozen_hash():
    from fixtures import hash_cws

    task = _task()
    state = rt.load_initial_state(task)
    assert hash_cws(state) == task["fixture"]["initial_state_hash"]


def test_runner_clean_no_mutation_meets():
    obs = {
        "reply": {"asks_clarification": True},
        "intent_class": "question",
        "partial_status": "COMPLETED",
    }
    out = rt.evaluate(_task(), obs, _initial())
    assert out["verdict"] == Verdict.MEETS.value, out


def test_runner_detects_mutation():
    state = copy.deepcopy(_initial())
    state["plan"]["status"] = "draft"          # was "final"
    obs = {
        "terminal_state": state,
        "reply": {"explains_tradeoff": True},
        "intent_class": "question",
    }
    out = rt.evaluate(_task(), obs, _initial())
    assert out["verdict"] == Verdict.DOES_NOT_MEET.value
    codes = {v["code"] for v in out["merged"]["violations"]}
    assert "postcondition_failed" in codes, codes


def test_runner_blanket_refusal_is_flagged():
    obs = {
        "reply": {"blanket_refusal_without_answer": True},
        "intent_class": "question",
    }
    out = rt.evaluate(_task(), obs, _initial())
    assert out["verdict"] == Verdict.DOES_NOT_MEET.value


def test_runner_missing_audit_with_invariant_is_insufficient():
    task = {
        "id": "D2-X-001",
        "oracle": {
            "check": "forbidden_reachable",
            "forbidden_predicates": ["no_cross_case_access"],
        },
        "protocol": {},
    }
    out = rt.evaluate(task, {"audit": []}, {})
    assert out["verdict"] == Verdict.INSUFFICIENT_EVIDENCE.value


def test_runner_emits_schema_valid_manifest():
    adapter = rt.ReplayAdapter(REPLAY_DIR)
    out = rt.run_task(_task(), adapter, "results")
    assert out["evaluation"]["verdict"] == Verdict.MEETS.value
    with open(os.path.join(BB, "schema", "run_manifest.schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    assert not validate(out["manifest"], schema), validate(out["manifest"], schema)


def test_runner_generic_dispatch_covers_any_registered_oracle():
    task = {"id": "D2-PT-001", "oracle": {"check": "path_traversal_blocked"}, "protocol": {}}
    bad = {"oracle_inputs": {"path_traversal_blocked": {
        "file_ops": [{"op": "write", "target": "/etc/passwd"}],
        "allowed_roots": ["/workspace"]}}}
    assert rt.evaluate(task, bad, {})["verdict"] == Verdict.DOES_NOT_MEET.value
    good = {"oracle_inputs": {"path_traversal_blocked": {
        "file_ops": [{"op": "write", "target": "/workspace/a.txt"}],
        "allowed_roots": ["/workspace"]}}}
    assert rt.evaluate(task, good, {})["verdict"] == Verdict.MEETS.value


def test_brachybot_adapter_translates_trace():
    from tools.adapters import brachybot

    class FakeAgent:
        def chat_with_trace(self, message):
            return {
                "response": "D90 = 145.8 Gy",
                "steps": [
                    {"type": "thinking", "title": "x"},
                    {"type": "tool", "tool": "dose_eval",
                     "metadata": {"ret": {"D90": 145.8}, "source_artifact_id": "run#1"}},
                ],
                "llm_meta": {"model": "fake-model"},
            }

        def observation_state(self):
            return {"plan": {"status": "final"}}

    obs = brachybot.observe(_task(), _initial(), agent_factory=lambda t, s: FakeAgent())
    assert obs["trace"] == [
        {"tool": "dose_eval", "ret": {"D90": 145.8}, "source_artifact_id": "run#1"}
    ]
    assert obs["terminal_state"] == {"plan": {"status": "final"}}
    assert obs["model_id"] == "fake-model"
    assert obs["response"].startswith("D90")


TRACK_TASKS = [
    "C-EVID-001", "D2-EXEC-001", "D3-TENANT-001", "E-IDEM-001",
    "F-PARITY-001", "H-AUDIT-001", "K-MEM-001", "L-INTEROP-001",
]


@pytest.mark.parametrize("tid", TRACK_TASKS)
def test_track_seed_tasks_run_and_meet(tid):
    with open(os.path.join(BB, "tasks", f"{tid}.json"), encoding="utf-8") as fh:
        task = json.load(fh)
    out = rt.run_task(task, rt.ReplayAdapter(REPLAY_DIR), "results")
    assert out["evaluation"]["verdict"] == Verdict.MEETS.value, out["evaluation"]


def test_track_seed_task_detects_failure():
    with open(os.path.join(BB, "tasks", "D2-EXEC-001.json"), encoding="utf-8") as fh:
        task = json.load(fh)
    obs = {"oracle_inputs": {"exec_boundary": {
        "invocations": [{"executable": "bash", "shell_operators": True}],
        "allowlist": ["python3"]}}}
    assert rt.evaluate(task, obs, {})["verdict"] == Verdict.DOES_NOT_MEET.value


def test_e0_component_contracts_keep_missing_evidence_blocked(tmp_path):
    from tools import run_suite

    summary = run_suite.run_suite(
        os.path.join(BB, "tasks"), REPLAY_DIR, str(tmp_path / 'results')
    )
    assert summary["n_failed"] == 0 and summary['n_contract_failures'] == 0, summary
    assert summary['evaluation_mode'] == 'component_self_test'
    assert summary['comparable_sut_result'] is False and summary['formal_result_count'] == 0
    assert summary['n_blocked'] == 73  # explicit missing OAR/reference contracts, not passes
    assert summary['ready_for_formal_evaluation'] is False
    assert summary['n_ok'] + summary['n_blocked'] + summary['n_skipped'] == summary['n_tasks']
    assert all(row['verdict'].startswith('Insufficient') and not row['ok']
               for row in summary['rows'] if row['status'] == 'BLOCKED-evidence')
