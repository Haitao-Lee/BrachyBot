"""Evaluator-owned inputs; these must never cross the SUT input boundary.

Component replay is explicitly a checker self-test. Formal runs require a
private evaluation context and an independent observation collector. Python
in-process separation is an API contract, not an OS security sandbox.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


PRIVATE_KEYS = frozenset({
    "oracle", "gold", "expect", "expected", "expected_state", "reference_answer",
    "correct_answer", "correct_diagnosis", "ground_truth", "clinical_intent",
    "scoring", "anti_gaming", "reviewer", "review", "provenance", "unit",
    "initial_state_hash", "setup_script", "guideline_ref", "allowed_intermediates",
    "evaluation", "evaluator_inputs", "human_reviewed", "criteria_booleans",
})


def redact_private(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_private(val) for key, val in value.items() if key not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [redact_private(val) for val in value]
    return copy.deepcopy(value)


def sut_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Allow only task-visible protocol, budget and opaque identity."""
    opaque = hashlib.sha256(str(task.get("id", "")).encode()).hexdigest()[:24]
    protocol = task.get("protocol") or {}
    return {"id": opaque, "protocol": {
        key: redact_private(protocol[key]) for key in ("turns", "events", "budget") if key in protocol
    }}


@dataclass(frozen=True)
class EvaluatorContext:
    """Provided by the evaluator, NOT read from a SUT response.

    inputs[checker] is a private complete policy/reference specification.
    observed_keys[checker] identifies which measured kwargs may come from the
    collector; overlapping fields always use the evaluator's private value.
    response_checker independently judges the actual delivered response.
    """
    inputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    observed_keys: Dict[str, tuple] = field(default_factory=dict)
    independently_observed: bool = False
    audit_complete: bool = False
    expected_state: Optional[Dict[str, Any]] = None
    response_checker: Any = None
    completion_checker: Any = None
    scenario_id: Optional[str] = None
    identity: Dict[str, Any] = field(default_factory=dict)
    mode: str = "formal"
    # Harness-owned browser receipts, never copied from a model response.
    user_chat_evidence: Optional[Dict[str, Any]] = None


def compose_inputs(context: EvaluatorContext, check: str, observation: Dict[str, Any]):
    if check not in context.inputs or check not in context.observed_keys:
        return None
    required = {
        "hard_constraint": ("limits",), "acceptable_set_hit": ("acceptable_families", "limits"),
        "coord_roundtrip": ("expected_physical",), "retrieval_at_k": ("gold", "k"),
        "tool_call_boundary": ("expected_decision", "allowed_tools", "authorised_effects"),
        "seed_geometry_fidelity": ("cws_seeds",), "dice_and_hd95": ("gold", "spacing_mm"),
        "guide_geometry_tol": ("designed",), "judge_rubric": ("rubric", "human_reviewed"),
        "path_traversal_blocked": ("allowed_roots",), "exec_boundary": ("allowlist",),
        "interference_fp": ("geometry",),
    }.get(check, ())
    if any(key not in context.inputs[check] for key in required):
        return None
    measured = (observation.get("oracle_inputs") or {}).get(check) or {}
    kwargs = {key: copy.deepcopy(measured[key]) for key in context.observed_keys[check] if key in measured}
    kwargs.update(copy.deepcopy(context.inputs[check]))
    return kwargs
