#!/usr/bin/env python3
"""Execution harness: drive a task through a SUT adapter and score it (DESIGN §26).

Until now BrachyBench shipped oracles + fixtures + a run-manifest *schema* but
nothing that turned a task into a scored run.  This is the missing pipeline:

    task.json  --(adapter)-->  observation  --(oracles)-->  result + verdict
                                                 |
                                                 +--> run_manifest.json

The SUT itself is **pluggable** so the same pipeline serves three needs:

* ``replay`` -- read a recorded observation (deterministic CI, regression tests,
  and the oracle self-proof).  Replay observations live under a caller-supplied
  directory and are *never* benchmark data.
* ``python:<module>:<func>`` -- call a function that drives the real SUT
  in-process (e.g. ``BrachyAgent.chat_with_trace``).  The function receives
  ``(task, initial_state)`` and returns an *observation* dict.
* any future HTTP/container adapter -- same dict contract.

2026-10-04 policy supersedes the historical live-entry examples above:
formal evaluations require ``browser-user-chat``. Python/direct-agent adapters
remain component test utilities and are blocked before invocation by run_task.

Observation contract (keys are optional unless the task's oracle needs them)::

    trace           [{"tool","ret","source_artifact_id"?}]
    audit           [{"kind","at","label"?,"case_id"?,"authorised"?,"op"?}]
    terminal_state  CWS dict at terminal receipt
    ui_state        CWS dict for the UI path (dual_path state_diff only)
    claims          [{"kind"?, "metric_name"?, "value"?, "claimed_text"?,
                      "evidence_keys"?}]
    evidence_ctx    EvidenceContext fields for metric_provenance
    dose            {"cumulative_dose","per_seed_doses","seed_ids","expect_seed_ids"}
    reply           {"asks_clarification","explains_tradeoff","refuses_safely",
                     "blanket_refusal_without_answer"}
    intent_class    str
    partial_status  one of the DESIGN §25.9 eight states
    infra_failed    bool (a broken harness is NEVER a model failure)

Usage::

    python tools/run_task.py --task tasks/D1-SA-007.json \
        --adapter replay --replay-dir tests/replay --out results/
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import sys
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
BB = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, BB)

from oracles import (  # noqa: E402
    ConstraintClass,
    EvidenceContext,
    OracleResult,
    PartialStatus,
    Verdict,
    Violation,
    gate_verdict,
    get_oracle,
    get_predicate,
    registered,
)
from oracles.predicates import INVARIANT_PREDICATES, STATE_PREDICATES  # noqa: E402
from tools import scoring as item_scoring  # noqa: E402
from tools.evaluator_contract import EvaluatorContext, compose_inputs, redact_private, sut_task
sys.path.insert(0, os.path.dirname(BB))
from user_chat_contract import ENTRY_MODE, evidence_errors

#: A single task proves nothing about a population rate, so the per-task verdict
#: deliberately does NOT apply the rule-of-three UCB; that belongs to the
#: aggregate layer across G independent scenarios (DESIGN §11.4).  We pass a
#: threshold of 1.0 purely so ``gate_verdict`` reuses the N6 mapping.
PER_TASK_UCB_THRESHOLD = 1.0


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(obj: Any) -> str:
    import json as _json
    return _json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def load_initial_state(task: Dict[str, Any]) -> Dict[str, Any]:
    """Build the frozen initial CWS for ``task``.

    ``setup_script`` is either a Python module exposing ``build()`` (authored
    tasks) or a JSON fixture (generated physics probes, which have no CWS).
    """
    rel = (task.get("fixture") or {}).get("setup_script")
    if not rel:
        return {}
    path = rel if os.path.isabs(rel) else os.path.join(BB, rel)
    if path.endswith(".py"):
        spec = importlib.util.spec_from_file_location(
            "brachy_setup_" + os.path.basename(path)[:-3], path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.build()
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------


class SutAdapter:
    name = "base"

    def observe(self, task: Dict[str, Any], initial_state: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class ReplayAdapter(SutAdapter):
    """Read a recorded observation from ``<dir>/<task_id>.json``."""

    name = "replay"

    def __init__(self, directory: str):
        self.directory = directory

    def observe(self, task, initial_state):
        path = os.path.join(self.directory, f"{task['id']}.json")
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"no replay observation for {task['id']} at {path}"
            )
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)


class PythonAdapter(SutAdapter):
    """Call ``module:function`` to obtain an observation from a live SUT."""

    def __init__(self, spec: str, *, collector=None, evaluator_context=None):
        self.spec = spec
        self.name = f"python:{spec}"
        self._fn: Optional[Callable] = None
        self.collector = collector
        self.evaluator_context = evaluator_context

    def _load(self) -> Callable:
        if self._fn is None:
            module_name, _, func_name = self.spec.partition(":")
            mod = importlib.import_module(module_name)
            self._fn = getattr(mod, func_name)
        return self._fn

    def observe(self, task, initial_state):
        visible = sut_task(task)
        visible["execution_id"] = uuid.uuid4().hex
        output = self._load()(visible, redact_private(initial_state))
        # The collector is evaluator-owned. Never treat the SUT's audit,
        # terminal-state or self-reported success as independent evidence.
        if self.collector is None:
            return output
        params = inspect.signature(self.collector).parameters
        if "context" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return self.collector(output, context={"task": task, "initial_state": initial_state,
                                                   "execution_id": visible["execution_id"]})
        return self.collector(output)


def build_adapter(kind: str, *, replay_dir: Optional[str] = None) -> SutAdapter:
    if kind == "browser-user-chat":
        from tools.adapters.user_chat import from_environment
        return from_environment()
    if kind == "replay":
        if not replay_dir:
            raise SystemExit("--adapter replay requires --replay-dir")
        return ReplayAdapter(replay_dir)
    if kind.startswith("python:"):
        return PythonAdapter(kind[len("python:"):])
    raise SystemExit(f"unknown adapter {kind!r}")


# ---------------------------------------------------------------------------
# oracle dispatch
# ---------------------------------------------------------------------------


def _terminal(task: Dict[str, Any], obs: Dict[str, Any], initial: Dict[str, Any]) -> Dict[str, Any]:
    """Terminal CWS enriched with the context predicates expect (BA-15).

    When the adapter does not report a distinct terminal state we assume the
    state is unchanged from the frozen initial state (the common "nothing
    happened" case).  A mutation must be reported explicitly.
    """
    raw = obs.get("terminal_state")
    state = dict(raw if raw is not None else initial)
    state.setdefault("_initial", initial)
    state.setdefault("_reply", obs.get("reply") or {})
    state.setdefault("_task", {"intent_class": obs.get("intent_class")})
    return state


def _invariant_oracle(task: Dict[str, Any], spec: Dict[str, Any],
                      obs: Dict[str, Any], initial: Dict[str, Any]) -> OracleResult:
    names = list(spec.get("forbidden_predicates") or [])
    invariant_preds = []
    state_preds = []
    for n in names:
        if n in INVARIANT_PREDICATES:
            invariant_preds.append(get_predicate(n))
        elif n in STATE_PREDICATES:
            state_preds.append(get_predicate(n))
        else:
            raise KeyError(f"unknown forbidden_predicate {n!r}")
    protocol = task.get("protocol") or {}
    audit = list(obs.get("audit") or [])
    return get_oracle("forbidden_reachable")().check(
        invariant_predicates=invariant_preds,
        postcondition_predicates=state_preds,
        allowed_intermediates=protocol.get("allowed_intermediates") or [],
        terminal_state=_terminal(task, obs, initial),
        audit=audit,
    )


def _pred_oracle(task, spec, obs, initial) -> OracleResult:
    name = spec.get("predicate")
    fn = get_predicate(name)
    ok = bool(fn(_terminal(task, obs, initial)))
    return OracleResult(
        oracle_id=f"pred:{name}",
        passed=ok,
        score=1.0 if ok else 0.0,
        violations=[] if ok else [Violation("predicate_failed", f"{name!r} is False")],
    )


def _dose_oracle(task, spec, obs, initial) -> OracleResult:
    dose = obs.get("dose") or {}
    return get_oracle("dose_additivity")().check(
        dose.get("cumulative_dose"),
        dose.get("per_seed_doses") or [],
        seed_ids=dose.get("seed_ids"),
        expect_seed_ids=dose.get("expect_seed_ids"),
    )


def _claim_oracle(task, spec, obs, initial) -> OracleResult:
    claims = obs.get("claims")
    if not claims and spec.get("claim"):
        claims = [{"kind": spec["claim"]}]
    return get_oracle("claim_matches_state")().check(
        claims or [], _terminal(task, obs, initial), terminal=True
    )


def _gap(oracle_id: str, code: str, message: str) -> OracleResult:
    """A missing observation field is an evidence gap, never a crash and
    never a silent pass (BA-1/BA-2; N8)."""
    return OracleResult(
        oracle_id=oracle_id, passed=False, score=0.0,
        evidence_gaps=[Violation(code, message, ConstraintClass.NONE)],
        applicable=False, partial_status=PartialStatus.PARTIAL,
        notes="missing observation field -> INSUFFICIENT_EVIDENCE (fail-closed)")


def _metric_oracle(task, spec, obs, initial) -> OracleResult:
    claims = obs.get("claims")
    if not claims and spec.get("evidence_keys"):
        claims = [{
            "metric_name": spec.get("claim"),
            "value": (obs.get("claimed_metrics") or {}).get(spec.get("claim")),
            "claimed_text": (obs.get("claimed_text") or {}).get(spec.get("claim")),
            "evidence_keys": spec["evidence_keys"],
        }]
    ctx_fields = obs.get("evidence_ctx") or {}
    ctx = EvidenceContext(**ctx_fields) if ctx_fields else None
    if ctx is None:
        return _gap("metric_provenance", "evidence_ctx_missing",
                    "metric_provenance requires obs['evidence_ctx']")
    return get_oracle("metric_provenance")().check(claims or [], obs.get("trace") or [], ctx)


def _state_diff_oracle(task, spec, obs, initial) -> OracleResult:
    ui = obs.get("ui_state")
    if ui is None:
        return _gap("state_diff", "ui_state_missing",
                    "state_diff requires obs['ui_state'] (dual-path observation)")
    # Use the raw NL/UI states: state_diff compares two paths directly and must
    # not have harness context (``_initial`` etc.) injected into only one side.
    nl = obs.get("terminal_state")
    nl = dict(nl if nl is not None else initial)
    return get_oracle("state_diff")().check(
        nl, ui,
        ignore_paths=(obs.get("state_diff_ignore") or None),
    )


def _generic_oracle(task, spec, obs, initial) -> OracleResult:
    """Drive any registered oracle from ``obs['oracle_inputs'][check]`` kwargs.

    This keeps ``run_task`` from having bespoke code per checker: a live
    adapter assembles the checker's inputs (arrays, traces, receipts, ...) and
    the replay adapter records them.  A missing entry is an evidence gap,
    never a silent pass and never a harness crash.
    """
    check = spec.get("check")
    inputs = (obs.get("oracle_inputs") or {}).get(check)
    if inputs is None:
        return _gap(
            str(check), "oracle_inputs_missing",
            f"no dispatch inputs for oracle {check!r}: provide "
            f"obs['oracle_inputs'][{check!r}] (or add a bespoke handler)")
    return get_oracle(check)().check(**inputs)


_CHECKS: Dict[str, Callable] = {
    "forbidden_reachable": _invariant_oracle,
    "dose_additivity": _dose_oracle,
    "claim_matches_state": _claim_oracle,
    "metric_provenance": _metric_oracle,
    "state_diff": _state_diff_oracle,
}

#: Physics-probe tasks (tools/gen_physics_fixtures.py) declare ``oracle.check``
#: as the *family* name; the registered checker id differs for 5 of the 6
#: families.  Dispatch translates so the 150 probes are runnable end-to-end.
_FAMILY_ALIASES: Dict[str, str] = {
    "coord_boundary": "coord_roundtrip",
    "needle_interference": "interference_fp",
    "dose_quantisation": "roundtrip_fidelity",
    "guide_tolerance": "guide_geometry_tol",
    "unit_binding": "param_binding",
}


def resolve_check(check: Optional[str]) -> Optional[str]:
    """Map a task ``oracle.check`` name onto a registered oracle id."""
    if check is None:
        return None
    return _FAMILY_ALIASES.get(check, check)


def _verdict_match_oracle(task: Dict[str, Any], spec: Dict[str, Any],
                          obs: Dict[str, Any], initial: Dict[str, Any]) -> OracleResult:
    """Compare the SUT's *conclusion* with the analytic ground truth.

    Physics probes embed a candidate claim (a predicted risk, a binding, a
    quantised grid) whose correctness the registered checker settles at
    generation time; the settled verdict is frozen in ``oracle.expect``.  The
    SUT's job is to *audit* that claim, so task success means the SUT's
    reported conclusion matches the analytic truth:

    * ``obs["claimed_verdict"]`` -- ``"pass"`` (claim verified) or ``"fail"``
      (defect found), extracted from the SUT reply by the adapter (I3).
    * a missing / malformed claim is an **evidence gap**, never a silent pass.

    The check name is recorded as ``oracle_verdict_match`` (the
    ``scoring.primary_metric`` declared by every generated probe).
    """
    expect = spec.get("expect") or {}
    want = expect.get("verdict")
    claim = obs.get("claimed_verdict")
    if want not in ("pass", "fail"):
        # no recorded expectation -> nothing to match; caller falls back
        raise ValueError("oracle.expect.verdict must be 'pass' or 'fail'")
    if claim not in ("pass", "fail"):
        return OracleResult(
            oracle_id="oracle_verdict_match",
            passed=False, score=0.0,
            evidence_gaps=[Violation(
                "claimed_verdict_missing",
                f"observation must carry claimed_verdict in {{pass, fail}}, got {claim!r}",
                ConstraintClass.NONE)],
            evidence={"expect": want, "claim": claim},
            constraint_class=ConstraintClass.NONE,
            applicable=False,
            partial_status=PartialStatus.PARTIAL,
            notes="SUT conclusion absent: the probe cannot be scored (fail-closed)",
        )
    ok = claim == want
    # optional stronger form: the adapter also reports *which* defect codes it
    # found; when present they must cover the recorded expectation.
    codes = obs.get("claimed_codes")
    want_codes = sorted(expect.get("codes") or [])
    codes_ok = True
    if claim == "fail" and want_codes and codes is not None:
        codes_ok = set(map(str, codes)).issuperset(set(want_codes))
    return OracleResult(
        oracle_id="oracle_verdict_match",
        passed=ok and codes_ok,
        score=1.0 if (ok and codes_ok) else 0.0,
        violations=[] if (ok and codes_ok) else [Violation(
            "oracle_verdict_mismatch",
            f"SUT concluded {claim!r}" + (f" with codes {sorted(map(str, codes))}" if codes else "")
            + f"; analytic truth is {want!r}"
            + (f" with codes {want_codes}" if want_codes else ""),
            ConstraintClass.NONE,
            detail={"expect": want, "expect_codes": want_codes,
                    "claim": claim, "claimed_codes": codes})],
        evidence={"expect": want, "expect_codes": want_codes, "claim": claim,
                  "claimed_codes": codes},
        constraint_class=ConstraintClass.NONE,
        notes="SUT conclusion vs analytic ground truth frozen at generation time",
    )


def dispatch(spec: Dict[str, Any], task: Dict[str, Any],
             obs: Dict[str, Any], initial: Dict[str, Any], context=None) -> OracleResult:
    check = resolve_check(spec.get("check"))
    if context is not None and check == "pred" and not obs.get("terminal_state"):
        return _gap(check, "terminal_observation_missing", "the initial fixture cannot stand in for an observed terminal state")
    if context is not None and check == "pred" and context.completion_checker is None:
        return _gap(check, "operation_completion_assessor_missing",
                    "a state predicate alone cannot prove this execution created or updated the requested artifact")
    if context is not None and check == "state_diff":
        if context.expected_state is None:
            return _gap(check, "task_outcome_missing", "formal parity requires a private expected outcome")
        if obs.get("terminal_state") is None or obs.get("ui_state") is None:
            return _gap(check, "path_state_missing", "both independently observed paths are required")
        return get_oracle(check)().check(obs["terminal_state"], obs["ui_state"],
                                       expected_state=context.expected_state)
    if context is not None and check in registered() and check not in _CHECKS:
        inputs = compose_inputs(context, check, obs)
        if inputs is None:
            return _gap(str(check), "private_oracle_contract_missing",
                        "formal evaluation needs evaluator-owned references/policy and measured input roles")
        return get_oracle(check)().check(**inputs)
    if check == "pred":
        return _pred_oracle(task, spec, obs, initial)
    handler = _CHECKS.get(check)
    if handler is not None:
        return handler(task, spec, obs, initial)
    if check in registered():
        return _generic_oracle(task, spec, obs, initial)
    raise NotImplementedError(f"unknown oracle check {check!r}")


def evaluate(task: Dict[str, Any], obs: Dict[str, Any],
             initial: Dict[str, Any], *, context=None) -> Dict[str, Any]:
    """Pure component evaluation by default; formal callers supply context.

    A component verdict is not a SUT performance measurement. run_task forces
    formal context for every live adapter and labels replay as self-test.
    """
    oracle = task.get("oracle") or {}
    expect_raw = oracle.get("expect")
    expect = expect_raw.get("verdict") if isinstance(expect_raw, dict) else None
    if expect in ("pass", "fail"):
        # Generated physics probe: the primary judgement is the SUT's
        # conclusion vs the analytic ground truth.  A structured
        # re-derivation (oracle_inputs keyed by the registered checker) is
        # consumed as an additional assert when the adapter supplies it.
        primary = _verdict_match_oracle(task, oracle, obs, initial)
        registered_id = resolve_check(oracle.get("check"))
        asserts = []
        if registered_id in registered():
            inputs = (obs.get("oracle_inputs") or {})
            raw = (oracle.get("check") or "")
            key = registered_id if inputs.get(registered_id) is not None else raw
            if inputs.get(key) is not None:
                asserts.append(dispatch({**oracle, "check": registered_id}, task, obs, initial, context))
    else:
        primary = dispatch(oracle, task, obs, initial, context)
        asserts = [dispatch(a, task, obs, initial, context) for a in (oracle.get("also_assert") or [])]
    if context is not None:
        for error in evidence_errors(context.user_chat_evidence, task):
            asserts.append(_gap("user_chat_execution", error,
                                "formal product evaluation requires evaluator-collected browser input and final delivery receipts"))
        if not context.independently_observed:
            asserts.append(_gap("observation_provenance", "independent_collector_missing",
                                "self-reported SUT state/audit cannot prove completion"))
        if context.completion_checker is not None:
            asserts.append(context.completion_checker(obs, initial, task))
        if task.get("track") in ("B", "C", "I", "J", "M") or "response" in obs:
            if context.response_checker is None:
                asserts.append(_gap("delivered_response", "response_assessor_missing",
                                    "actual delivered answer must be independently assessed"))
            else:
                asserts.append(context.response_checker(obs.get("response", ""), obs, task))
    merged = primary
    for a in asserts:
        merged = merged.merge(a)
    verdict = gate_verdict(merged, threshold_ucb=PER_TASK_UCB_THRESHOLD, G=1)
    if obs.get("infra_failed") and not any(v.constraint_class == ConstraintClass.INVARIANT for v in merged.violations):
        # A harness failure is never a model failure (DESIGN §25.9).
        verdict = Verdict.INSUFFICIENT_EVIDENCE
    evaluation = {
        "task_id": task.get("id"),
        "primary": primary.to_dict(),
        "also_assert": [a.to_dict() for a in asserts],
        "merged": merged.to_dict(),
        "verdict": verdict.value,
        "evaluation_mode": "formal" if context is not None else "component_self_test",
        "comparable_sut_result": bool(context is not None and context.independently_observed
                                       and context.audit_complete and context.scenario_id
                                       and context.identity.get("sut_id") and context.identity.get("source_sha256")
                                       and not evidence_errors(context.user_chat_evidence, task)),
        "audit_complete": context.audit_complete if context is not None else False,
        "scenario_id": context.scenario_id if context is not None else None,
        "evaluator_identity": context.identity if context is not None else {},
    }
    # Subordinate per-item score (DESIGN §10 / scoring design).  Gate stays
    # authoritative; the score is diagnostic and never softens the gate.
    evaluation["item_score"] = item_scoring.compute_item_score(task, evaluation, obs).to_dict()
    return evaluation


# ---------------------------------------------------------------------------
# run manifest (DESIGN §26.2)
# ---------------------------------------------------------------------------


def build_manifest(task: Dict[str, Any], adapter: SutAdapter, obs: Dict[str, Any],
                   run_id: str, results_dir: str) -> Dict[str, Any]:
    protocol = task.get("protocol") or {}
    status = obs.get("partial_status") or PartialStatus.PARTIAL.value
    system_prompt = obs.get("system_prompt") or adapter.name
    return {
        "manifest_version": "1.0",
        "track": "PRV",
        "run_id": run_id,
        "sut": {
            "sut_id": obs.get("sut_id") or "BrachyBot",
            "model": {"id": obs.get("model_id") or "unspecified"},
            "system_prompt_sha256": _sha256(system_prompt),
            "adapter": adapter.name,
            "deterministic_kernels": bool(obs.get("deterministic_kernels", False)),
            "seen_task_ids": list(obs.get("seen_task_ids") or []),
            "human_in_loop": bool(obs.get("human_in_loop", False)),
        },
        "env": {
            "environment_json_sha256": _sha256(_canonical(obs.get("env") or {})),
        },
        "benchmark": {
            "prv_version": "1.0",
            "task_manifest_sha256": _sha256(_canonical(task)),
        },
        "protocol": {
            "entry_mode": ENTRY_MODE if getattr(adapter, "entry_mode", None) == ENTRY_MODE else "component_only",
            "phase": os.environ.get("BRACHYBENCH_PHASE", "P1"),
            "n_runs": int(protocol.get("n_runs") or 1),
            "budget": protocol.get("budget") or {"wall_clock_s": 0, "turns": 0, "tool_calls": 0},
        },
        "results_dir": results_dir,
        "partial_status_histogram": {status: 1},
        "infra_failed_count": 1 if obs.get("infra_failed") else 0,
        "task_failed_count": 0,
    }


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def run_task(task: Dict[str, Any], adapter: SutAdapter, results_dir: str) -> Dict[str, Any]:
    # Block before invoking a callback or installing a fixture.
    from tools.adapters.user_chat import UserChatAdapter
    if not isinstance(adapter, (ReplayAdapter, UserChatAdapter)):
        return {"evaluation": {"task_id": task.get("id"), "track": task.get("track"),
            "verdict": Verdict.INSUFFICIENT_EVIDENCE.value, "merged": {},
            "evaluation_mode": "blocked_user_chat_contract", "comparable_sut_result": False,
            "partial_status": "BLOCKED_BY_DEPENDENCY", "infra_failed": True,
            "error": "formal evaluation requires browser-user-chat; raw Python/model/agent adapters are component-test only"},
            "manifest": None}
    if isinstance(adapter, UserChatAdapter):
        context = adapter.evaluator_context
        if (adapter.collector is None or context is None or not context.independently_observed
                or not context.audit_complete or not context.scenario_id
                or not context.identity.get("sut_id") or not context.identity.get("source_sha256")
                or context.response_checker is None or context.completion_checker is None):
            return {"evaluation": {"task_id": task.get("id"), "track": task.get("track"),
                "verdict": Verdict.INSUFFICIENT_EVIDENCE.value, "merged": {},
                "evaluation_mode": "blocked_user_chat_contract", "comparable_sut_result": False,
                "partial_status": "BLOCKED_BY_DEPENDENCY", "infra_failed": True,
                "error": "independent collector, source/scenario identity, response and completion assessors required before live submission"},
                "manifest": None}
    try:
        initial = load_initial_state(task)
    except Exception as exc:
        return {"evaluation": {"task_id": task.get("id"), "merged": {},
                               "track": task.get("track"), "infra_failed": True,
                               "verdict": Verdict.INSUFFICIENT_EVIDENCE.value,
                               "error": f"fixture failed: {type(exc).__name__}: {exc}"}, "manifest": None}
    if (task.get("fixture") or {}).get("initial_state_hash") and initial:
        from fixtures import hash_cws  # noqa: E402

        actual = hash_cws(initial) if "cws_version" in initial else None
        want = task["fixture"]["initial_state_hash"]
        if actual is not None and actual != want:
            obs = {"infra_failed": True, "terminal_state": {}}
            return {
                "evaluation": {
                    "task_id": task.get("id"), "merged": {}, "verdict": Verdict.INSUFFICIENT_EVIDENCE.value,
                    "track": task.get("track"), "infra_failed": True,
                    "error": f"initial_state_hash drift: {actual} != {want}",
                },
                "manifest": None,
            }
    obs = None
    try:
        obs = adapter.observe(task, initial)
    except Exception as exc:  # a broken adapter is INFRA, never a model failure
        run_id = f"run_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return {
            "evaluation": {
                "task_id": task.get("id"), "merged": {},
                "track": task.get("track"), "infra_failed": True,
                "verdict": Verdict.INSUFFICIENT_EVIDENCE.value,
                "error": f"adapter failed: {type(exc).__name__}: {exc}",
                "partial_status": "BLOCKED_BY_DEPENDENCY" if type(exc).__name__ == "UserChatBlocked" else "INFRA_FAILED",
                "evaluation_mode": "blocked_user_chat_contract", "comparable_sut_result": False,
            },
            "manifest": None,
            "observation": getattr(exc, "observation", None),
        }
    if not isinstance(obs, dict):
        obs = {"infra_failed": True, "partial_status": "INFRA_FAILED"}
    context = None if isinstance(adapter, ReplayAdapter) else (
        getattr(adapter, "evaluator_context", None) or EvaluatorContext())
    if context is not None:
        from dataclasses import replace
        context = replace(context, user_chat_evidence=adapter.execution_evidence)
    try:
        eval_result = evaluate(task, obs, initial, context=context)
    except Exception as exc:
        obs["infra_failed"] = True
        obs["partial_status"] = "INFRA_FAILED"
        eval_result = {"task_id": task.get("id"), "verdict": Verdict.INSUFFICIENT_EVIDENCE.value,
                       "track": task.get("track"), "infra_failed": True,
                       "merged": {}, "evaluation_mode": "formal" if context else "component_self_test",
                       "error": f"evaluator failed: {type(exc).__name__}: {exc}"}
    run_id = f"run_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    manifest = build_manifest(task, adapter, obs, run_id, results_dir)
    if context is not None:
        manifest["evaluator_identity"] = context.identity
        manifest["user_chat_execution"] = context.user_chat_evidence
        manifest["evaluation_mode"] = "formal"
        manifest["comparable_sut_result"] = eval_result.get("comparable_sut_result", False)
    manifest["task_failed_count"] = int(eval_result["verdict"] == Verdict.DOES_NOT_MEET.value)
    return {"evaluation": eval_result, "manifest": manifest, "observation": obs}


def _load_task(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="path to a task json")
    ap.add_argument("--adapter", default="replay",
                    help="'replay' (component self-test) or 'browser-user-chat' (formal); python callbacks cannot be formal")
    ap.add_argument("--replay-dir", default=None)
    ap.add_argument("--out", default="results")
    ap.add_argument("--evaluator-config", help="private evaluator JSON, never passed to the SUT")
    ap.add_argument("--collector", help="evaluator-owned module:function collecting real state/audit/artifacts")
    ap.add_argument("--response-checker", help="independent module:function assessing delivered prose")
    ap.add_argument("--completion-checker", help="independent module:function assessing current-execution effects and artifact versions")
    args = ap.parse_args(argv)

    from tools.jsonschema_lite import validate as _validate  # noqa: E402

    task = _load_task(args.task)
    adapter = build_adapter(args.adapter, replay_dir=args.replay_dir)
    from tools.adapters.user_chat import UserChatAdapter
    if isinstance(adapter, (PythonAdapter, UserChatAdapter)):
        config = _load_task(args.evaluator_config) if args.evaluator_config else {}
        def load_hook(spec):
            module, _, name = spec.partition(":")
            return getattr(importlib.import_module(module), name)
        adapter.collector = load_hook(args.collector) if args.collector else None
        adapter.evaluator_context = EvaluatorContext(
            inputs=config.get("inputs", {}), observed_keys=config.get("observed_keys", {}),
            expected_state=config.get("expected_state"), identity=config.get("identity", {}),
            scenario_id=config.get("scenario_id"),
            independently_observed=adapter.collector is not None,
            audit_complete=config.get("audit_complete") is True and adapter.collector is not None,
            response_checker=load_hook(args.response_checker) if args.response_checker else None,
            completion_checker=load_hook(args.completion_checker) if args.completion_checker else None)
    n_runs = int((task.get("protocol") or {}).get("n_runs") or 1)
    if n_runs < 1:
        raise ValueError("n_runs must be positive")
    outcomes = [run_task(task, adapter, args.out) for _ in range(n_runs)]
    exit_code = 0
    for repeat_index, outcome in enumerate(outcomes):
        if outcome.get("manifest") is not None:
            run_id = outcome["manifest"]["run_id"]
            path = os.path.join(args.out, run_id)
            outcome["repeat_index"] = repeat_index
            _write_json(os.path.join(path, f"{task['id']}.record.json"), outcome)
        elif "error" in outcome["evaluation"]:
            _write_json(os.path.join(args.out, f"infra-{uuid.uuid4().hex}.record.json"), outcome)
        if outcome["evaluation"]["verdict"] != Verdict.MEETS.value:
            exit_code = max(exit_code, 1 if outcome["evaluation"]["verdict"] == Verdict.DOES_NOT_MEET.value else 2)
    outcome = outcomes[-1]

    if outcome.get("manifest") is None:
        print(f"INFRA: {outcome['evaluation'].get('error')}", file=sys.stderr)
        return 2

    with open(os.path.join(BB, "schema", "run_manifest.schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    errs = _validate(outcome["manifest"], schema)
    if errs:
        print("run_manifest schema errors:", errs, file=sys.stderr)
        return 3

    run_id = outcome["manifest"]["run_id"]
    out_dir = os.path.join(args.out, run_id)
    _write_json(os.path.join(out_dir, f"{task['id']}.oracle.json"), outcome["evaluation"])
    _write_json(os.path.join(out_dir, f"{task['id']}.observation.json"), outcome["observation"])
    _write_json(os.path.join(out_dir, "run_manifest.json"), outcome["manifest"])
    print(f"{task['id']}: {outcome['evaluation']['verdict']} -> {out_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
