"""Error-handling / audit / idempotency checkers (DESIGN §8.3, tracks E/H/B).

Implements: ``error_contract``, ``state_invariant``, ``receipt_complete``,
``idempotency``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

from .base import ConstraintClass, Oracle, OracleResult, Violation, register

# DESIGN §6.E: the error envelope a caller may rely on
ERROR_CONTRACT_FIELDS = ("code", "message", "retryable", "op_id")


@register
class ErrorContract(Oracle):
    """§8.3 ``error_contract``: failures surface as a stable, typed envelope.

    A caller must be able to branch on ``retryable`` without parsing prose.
    """

    id = "error_contract"
    constraint_class = ConstraintClass.NONE

    RETRYABLE_CODES = {"TIMEOUT", "UNAVAILABLE", "BUSY", "NETWORK", "OOM_RETRY"}

    def check(
        self,
        errors: Sequence[Dict[str, Any]],
        *,
        allowed_codes: Optional[Sequence[str]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        for e in errors or []:
            missing = [f for f in ERROR_CONTRACT_FIELDS if f not in e]
            if missing:
                violations.append(Violation(
                    "error_contract_incomplete", f"missing {missing}", at=at, detail=e))
                continue
            code = str(e.get("code"))
            if allowed_codes is not None and code not in allowed_codes:
                violations.append(Violation(
                    "error_code_undeclared", f"{code!r} not in the declared set", at=at, detail=e))
            # the code and the retryable hint must agree
            if code in self.RETRYABLE_CODES and not e.get("retryable"):
                violations.append(Violation(
                    "error_retryable_mislabelled",
                    f"{code} should be retryable=True", at=at, detail=e))
            elif code not in self.RETRYABLE_CODES and e.get("retryable"):
                violations.append(Violation(
                    "error_retryable_mislabelled",
                    f"{code} should be retryable=False", at=at, detail=e))
            if not str(e.get("message") or "").strip():
                violations.append(Violation(
                    "error_message_empty", f"{code} has no message", at=at, detail=e))
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations, evidence={"n_errors": len(errors or [])},
            constraint_class=self.constraint_class)


@register
class StateInvariant(Oracle):
    """§8.3 ``state_invariant``: a failure must leave the world state intact.

    DESIGN §6.E "state not corrupted".  A failed tool may leave a tombstone but
    must never leave a half-applied mutation.
    """

    id = "state_invariant"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        *,
        allowed_mutations: Sequence[str] = (),
        at: Optional[str] = None,
    ) -> OracleResult:
        """Compares two CWS-like dicts after stripping declared volatile keys."""
        volatile = {"_initial", "_reply", "_task"}
        a = self._strip(before, volatile | set(allowed_mutations))
        b = self._strip(after, volatile | set(allowed_mutations))
        diffs = self._diff(a, b, "")
        violations = [
            Violation("state_corrupted", f"{k}: {va!r} -> {vb!r}", at=at,
                      detail={"path": k, "before": va, "after": vb})
            for k, va, vb in diffs
        ]
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"n_diffs": len(diffs), "ignored": sorted(volatile | set(allowed_mutations))},
            constraint_class=self.constraint_class)

    @classmethod
    def _strip(cls, node, drop, path=""):
        if isinstance(node, dict):
            return {k: cls._strip(v, drop, f"{path}.{k}" if path else str(k))
                    for k, v in node.items()
                    if (path + "." + k if path else k) not in drop and k not in drop}
        return node

    @classmethod
    def _diff(cls, a, b, path):
        out = []
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                p = f"{path}.{k}" if path else str(k)
                out.extend(cls._diff(a.get(k), b.get(k), p))
        elif a != b:
            out.append((path, a, b))
        return out


@register
class ReceiptComplete(Oracle):
    """§8.3 ``receipt_complete``: every mutation has a receipt with a valid hash
    chain (track H, owner of ``Receipt Coverage``)."""

    id = "receipt_complete"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        mutations: Sequence[Dict[str, Any]],
        receipts: Sequence[Dict[str, Any]],
        *,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``mutations``: ``{"op_id": .., "payload": {...}}``;
        ``receipts``: ``{"op_id": .., "status": .., "hash": .., "prev_hash": ..}``."""
        violations: List[Violation] = []
        by_op = {str(r.get("op_id")): r for r in receipts or []}
        ids = [m.get("op_id") for m in mutations or []]
        if any(op is None for op in ids) or len(set(ids)) != len(ids) or len(by_op) != len(receipts or []):
            violations.append(Violation("receipt_identity_duplicated", "each mutation and receipt needs a unique nonempty operation ID", at=at))
        expected_prev = "0" * 64
        for m in mutations or []:
            op = str(m.get("op_id"))
            r = by_op.get(op)
            if r is None:
                violations.append(Violation(
                    "receipt_missing", f"no receipt for mutation {op}", at=at))
                continue
            want = self._hash(op, m.get("payload"), r.get("prev_hash"))
            if r.get("hash") != want:
                violations.append(Violation(
                    "receipt_hash_invalid", f"{op}: hash does not match payload", at=at,
                    detail={"got": r.get("hash"), "want": want}))
            if r.get("prev_hash") != expected_prev:
                violations.append(Violation(
                    "receipt_chain_broken", f"{op}: prev_hash is not the chain head", at=at))
            expected_prev = str(r.get("hash"))
            for f in ("status", "op_id", "hash"):
                if r.get(f) in (None, ""):
                    violations.append(Violation(
                        "receipt_field_missing", f"{op}: {f} empty", at=at))
        coverage = (sum(str(op) in by_op for op in set(ids)) / len(mutations)) if mutations else 0.0
        passed = not violations and coverage == 1.0
        return OracleResult(
            oracle_id=self.id, passed=passed, score=float(coverage),
            violations=violations,
            evidence={"receipt_coverage": coverage, "n_mutations": len(mutations or []),
                      "n_receipts": len(receipts or [])},
            constraint_class=self.constraint_class)

    @staticmethod
    def _hash(op_id: str, payload: Any, prev: Any) -> str:
        body = json.dumps({"op_id": op_id, "payload": payload, "prev": prev},
                          sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@register
class Idempotency(Oracle):
    """§8.3 ``idempotency``: replaying a request leaves the state unchanged."""

    id = "idempotency"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        states: Sequence[Dict[str, Any]],
        *,
        ignore_paths: Sequence[str] = ("plan.receipts", "ui.version_fence"),
        at: Optional[str] = None,
    ) -> OracleResult:
        """``states``: the CWS after each of >=2 identical submissions."""
        if len(states or []) < 2:
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=[Violation(
                    "idempotency_untested", "need >=2 identical submissions", at=at)],
                constraint_class=self.constraint_class, applicable=False)
        base = StateInvariant._strip(states[0], set(ignore_paths))
        violations: List[Violation] = []
        for i, s in enumerate(states[1:], 2):
            diffs = StateInvariant._diff(base, StateInvariant._strip(s, set(ignore_paths)), "")
            for path, va, vb in diffs:
                violations.append(Violation(
                    "idempotency_violation",
                    f"submission {i} changed {path}: {va!r} -> {vb!r}", at=at))
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=1.0 if passed else 0.0,
            violations=violations,
            evidence={"n_submissions": len(states), "ignored": list(ignore_paths)},
            constraint_class=self.constraint_class)


@register
class ReceiptCoverageOnly(Oracle):
    """Convenience alias exposing just the coverage ratio for track H."""

    id = "receipt_coverage_rate"
    constraint_class = ConstraintClass.NONE

    def check(self, mutations, receipts, *, at=None) -> OracleResult:  # noqa: D102
        sub = ReceiptComplete().check(mutations, receipts, at=at)
        cov = float(sub.evidence.get("receipt_coverage", 0.0))
        return OracleResult(
            oracle_id=self.id, passed=cov == 1.0, score=cov,
            violations=list(sub.violations), evidence=sub.evidence,
            constraint_class=self.constraint_class)
