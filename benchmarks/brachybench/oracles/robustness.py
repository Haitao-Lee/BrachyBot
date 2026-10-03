"""``paraphrase_invariance`` -- expression robustness (DESIGN §31).

A benchmark that asks each intent **once** cannot see the failure the user
described: *the same question, phrased differently, gets a different answer*.
This group-level checker makes that failure a first-class verdict.

Input is one **G-EQ group**: several instances that express the *same* intent
(different wording, language, terseness, typos).  Each instance has already
been scored independently; this checker compares their **outcome classes**
(verdict + violation/evidence codes + partial status).  A group passes only if
every member lands in the **same outcome class** -- action, abstention and
refusal must all be expression-invariant.

It deliberately does **not** require identical wording: the reply text is free
to vary; only the *decision* must not.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .base import ConstraintClass, Oracle, OracleResult, Violation, register


def normalize_outcome_class(outcome: Any) -> tuple:
    """Canonical, hashable form of an outcome class.

    Accepts either a mapping (``{"verdict":..,"violations":[..],..}``) or an
    already-normalised tuple.  Fixing the *decision* surface (not the prose)
    is what makes the comparison meaningful.
    """
    if isinstance(outcome, tuple):
        return outcome
    if not isinstance(outcome, dict):
        return (str(outcome),)
    return (
        str(outcome.get("verdict")),
        tuple(sorted(outcome.get("violations") or [])),
        tuple(sorted(outcome.get("evidence_gaps") or [])),
        str(outcome.get("partial_status") or ""),
    )


@register
class ParaphraseInvariance(Oracle):
    id = "paraphrase_invariance"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        members: Sequence[Dict[str, Any]],
        *,
        expected_outcome: Optional[Any] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``members`` items: ``{"instance_id", "expression_profile"?, "outcome_class"}``."""
        members = list(members or [])
        violations: List[Violation] = []
        gaps: List[Violation] = []

        if len(members) < 2:
            # A "group" of one proves nothing about expression robustness.
            gaps.append(Violation(
                "paraphrase_group_too_small",
                "expression robustness needs >=2 members",
                at=at,
            ))
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                evidence_gaps=gaps, applicable=False, coverage=0.0,
                constraint_class=self.constraint_class,
                notes="group of <2 cannot test paraphrase invariance",
            )

        by_instance = {str(m.get("instance_id")): normalize_outcome_class(m.get("outcome_class"))
                       for m in members}
        distinct = {}
        for iid, cls in by_instance.items():
            distinct.setdefault(cls, []).append(iid)

        # majority = the class the largest number of phrasings agree on
        majority_cls, majority_ids = max(distinct.items(), key=lambda kv: len(kv[1]))

        if len(distinct) > 1:
            for cls, ids in distinct.items():
                if cls == majority_cls:
                    continue
                for iid in ids:
                    violations.append(Violation(
                        "paraphrase_inconsistency",
                        f"{iid} landed in a different outcome class than the "
                        f"{len(majority_ids)} phrasing(s) {majority_ids} for the same intent",
                        at=at,
                        detail={
                            "instance": iid,
                            "outcome_class": list(cls),
                            "majority_class": list(majority_cls),
                            "majority_members": majority_ids,
                        },
                    ))

        if expected_outcome is not None:
            exp = normalize_outcome_class(expected_outcome)
            if majority_cls != exp:
                violations.append(Violation(
                    "paraphrase_agrees_but_wrong",
                    "all phrasings agreed, but on the wrong outcome class",
                    at=at,
                    detail={"agreed": list(majority_cls), "expected": list(exp)},
                ))

        n = len(by_instance)
        consistent = len(distinct) == 1
        return OracleResult(
            oracle_id=self.id,
            passed=not violations and not gaps,
            score=1.0 if (not violations and not gaps) else 0.0,
            violations=violations,
            evidence_gaps=gaps,
            evidence={
                "n_members": n,
                "n_distinct_classes": len(distinct),
                "paraphrase_consistency_rate": (max(len(v) for v in distinct.values()) / n) if n else 0.0,
                "majority_members": majority_ids,
                "classes": {str(k): v for k, v in distinct.items()},
            },
            constraint_class=self.constraint_class,
            applicable=n >= 2,
            notes=("group passes only if every phrasing yields the same decision "
                   "(action/abstention/refusal); reply wording may vary"),
        )
