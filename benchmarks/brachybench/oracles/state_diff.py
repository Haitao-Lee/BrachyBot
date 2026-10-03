"""``state_diff`` -- dual-path terminal-state equivalence (DESIGN Track F, N11).

The NL path and the UI path of the same intent must reach the same terminal
world state (``state_after(NL) ⊟ state_after(UI) == ∅``).  Numeric fields
carry field-class tolerances (dose / coord / volume), integers, booleans and
enums compare strictly (§6.F, M19).

Self-reported conclusion flags are stripped first (N8).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import ConstraintClass, Oracle, OracleResult, PartialStatus, Violation, register
from .evidence_keys import strip_self_reported
from .tolerances import state_diff_field_class, values_equal


def _flatten(node: Any, path: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(node, dict):
        if not node:
            out[path] = {"__empty_container__": "dict"}
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            out.update(_flatten(v, p))
    elif isinstance(node, (list, tuple)):
        if not node:
            out[path] = {"__empty_container__": "list"}
        # lists compare element-wise on their flattened leaves
        for i, v in enumerate(node):
            out.update(_flatten(v, f"{path}[{i}]"))
    else:
        out[path] = node
    return out


@register
class StateDiff(Oracle):
    id = "state_diff"
    constraint_class = ConstraintClass.POSTCONDITION

    def check(
        self,
        nl_state: Dict[str, Any],
        ui_state: Dict[str, Any],
        *,
        ignore_paths: Optional[Sequence[str]] = None,
        at: Optional[str] = None,
        expected_state: Optional[Dict[str, Any]] = None,
    ) -> OracleResult:
        if not nl_state or not ui_state:
            return OracleResult(oracle_id=self.id, passed=False, score=0.0, applicable=False,
                                partial_status=PartialStatus.PARTIAL,
                                evidence_gaps=[Violation("path_state_empty", "empty paths do not prove parity")])
        a = _flatten(strip_self_reported(nl_state or {})["observed"])
        b = _flatten(strip_self_reported(ui_state or {})["observed"])
        ignore = tuple(ignore_paths or ())

        keys = sorted(set(a) | set(b))
        violations: List[Violation] = []
        mismatches: List[Dict[str, Any]] = []
        compared = 0

        for k in keys:
            # P2: exact match or dotted-prefix only ("ui" ignores "ui.opacity"
            # but must NOT ignore "build.ui").  The old substring test silently
            # dropped unrelated leaves.
            if any(k == p or k.startswith(p + ".") or k.startswith(p + "[") for p in ignore):
                continue
            compared += 1
            if k not in a:
                mismatches.append({"path": k, "nl": None, "ui": b[k], "why": "only_in_ui"})
                violations.append(
                    Violation("state_diff_missing_in_nl", f"{k} only in UI path", at=at)
                )
                continue
            if k not in b:
                mismatches.append({"path": k, "nl": a[k], "ui": None, "why": "only_in_nl"})
                violations.append(
                    Violation("state_diff_missing_in_ui", f"{k} only in NL path", at=at)
                )
                continue
            fc = state_diff_field_class(k)
            ok, why = values_equal(a[k], b[k], fc)
            if not ok:
                mismatches.append(
                    {"path": k, "nl": a[k], "ui": b[k], "class": fc, "why": why}
                )
                violations.append(
                    Violation(
                        "state_diff_mismatch",
                        f"{k}: NL={a[k]!r} vs UI={b[k]!r} ({fc}, {why})",
                        at=at,
                        detail={"path": k, "class": fc},
                    )
                )

        passed = not mismatches
        if expected_state is not None:
            for label, state in (("NL", nl_state), ("UI", ui_state)):
                result = self.check(state, expected_state, ignore_paths=ignore_paths, at=at)
                if not result.passed:
                    passed = False
                    violations.append(Violation("task_outcome_not_reached",
                                                f"{label} path did not reach the evaluator-owned outcome", at=at,
                                                detail=result.evidence))
        return OracleResult(
            oracle_id=self.id,
            passed=passed,
            score=(1.0 if passed else 0.0) if expected_state is not None else max(0.0, 1 - len(mismatches) / max(compared, 1)),
            violations=violations,
            evidence={
                "compared_leaves": compared,
                "n_mismatch": len(mismatches),
                "mismatches": mismatches[:50],
                "ignored": list(ignore),
                "tolerance_table": "oracles.tolerances.STATE_DIFF_TOLERANCES",
            },
            constraint_class=self.constraint_class,
            notes=("parity plus task completion" if expected_state is not None else
                   "parity only; NOT evidence of task completion; float classes per §7.4"),
        )

