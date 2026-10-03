"""``judge_rubric`` -- rubric-based assist scoring (O5 assist only).

DESIGN §8.5.  Open-ended intents (greeting / reasoning / communication /
multilingual) have no deterministic program oracle and must **not** be scored by
keywords (§12.4 forbids the ``keyword`` kind).  They are scored by a judge
against an explicit rubric, and the judge is **assist-only**: its verdict must
be corroborated by human spot-checks at the rate set in §8.5.  This oracle is
the *structural* half -- it validates that the judge's structured output is
complete and that human corroboration happened.

It deliberately cannot confirm the answer is *correct*; that is the human
corroborator's job.  It confirms the *process* is sound.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .base import (
    ConstraintClass,
    Oracle,
    OracleResult,
    PartialStatus,
    Violation,
    register,
)


@register
class JudgeRubric(Oracle):
    id = "judge_rubric"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        judgments: Sequence[Dict[str, Any]],
        *,
        rubric: Dict[str, Any],
        human_reviewed: Optional[Dict[str, bool]] = None,
        human_rate_min: float = 0.05,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``judgments`` items::

            {"item_id": .., "criteria_scores": {"answers_question": 1, ...},
             "judge_id": "model-x"}

        ``rubric``::

            {"criteria": ["answers_question", "no_hallucination", ...],
             "min_criteria_met": 3}

        ``human_reviewed``: {"item_id": True/False} -- spot-check results.
        """
        crit = list(rubric.get("criteria") or [])
        need = int(rubric.get("min_criteria_met") or len(crit))
        violations: List[Violation] = []
        gaps: List[Violation] = []

        if not crit:
            gaps.append(Violation("rubric_empty", "no criteria in rubric", at=at))
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                evidence_gaps=gaps, applicable=False, coverage=0.0,
                constraint_class=self.constraint_class,
                notes="assist-only (O5); requires a rubric",
            )

        n = len(judgments or [])
        if n == 0:
            gaps.append(Violation(
                "no_judgments", "nothing judged; assist verdict is empty", at=at))
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                evidence_gaps=gaps, applicable=False, coverage=0.0,
                constraint_class=self.constraint_class,
            )

        passed_items = 0
        reviewed = 0
        per: List[Dict[str, Any]] = []
        for j in judgments or []:
            iid = str(j.get("item_id"))
            scores = j.get("criteria_scores") or {}
            missing = [c for c in crit if c not in scores]
            entry: Dict[str, Any] = {"item_id": iid, "missing": missing, "met": 0}
            if missing:
                violations.append(Violation(
                    "rubric_criteria_not_scored",
                    f"{iid}: judge left {missing} un-scored", at=at))
            invalid = [c for c in crit if c in scores and type(scores[c]) not in (bool, int, float)]
            if invalid or any(scores.get(c) not in (False, True, 0, 1) for c in crit if c not in missing):
                violations.append(Violation("rubric_score_invalid", f"{iid}: criteria require explicit binary values", at=at))
            met = sum(1 for c in crit if type(scores.get(c)) in (bool, int, float) and scores.get(c) == 1)
            entry["met"] = met
            entry["ok"] = (not missing) and not invalid and met >= need
            if not entry["ok"] and not missing:
                violations.append(Violation(
                    "rubric_below_threshold",
                    f"{iid}: met {met}/{need} criteria", at=at))
            if entry["ok"]:
                passed_items += 1
            if human_reviewed is not None and iid in human_reviewed:
                reviewed += 1
                entry["human_ok"] = human_reviewed[iid] is True
                if human_reviewed[iid] is not True:
                    violations.append(Violation(
                        "human_rejected_judge_verdict",
                        f"{iid}: human corroboration disagreed with judge", at=at))
            per.append(entry)

        # human spot-check rate (§8.5) -- only enforced when a rate is declared
        if human_rate_min > 0:
            rate = (reviewed / n) if n else 0.0
            if rate < human_rate_min:
                gaps.append(Violation(
                    "insufficient_human_corroboration",
                    f"{reviewed}/{n} = {rate:.2f} < required {human_rate_min:.2f} "
                    "(assist-only judge needs human spot-checks, §8.5)",
                    at=at))

        applicable = n > 0 and not any(v.code == "no_judgments" for v in gaps)
        # independence (§8.6 I3): an assist-only judge becomes independent only
        # when every item was human-corroborated and the human agreed.
        independent = (
            human_reviewed is not None
            and reviewed == n
            and all(e.get("human_ok") for e in per)
        )
        passed = applicable and not violations and not gaps
        return OracleResult(
            oracle_id=self.id,
            passed=passed,
            score=(passed_items / n) if n else 0.0,
            violations=violations,
            evidence_gaps=gaps,
            evidence={"criteria": crit, "need": need, "n": n,
                      "passed_items": passed_items, "human_reviewed": reviewed,
                      "per_item": per},
            constraint_class=self.constraint_class,
            independent=independent,
            applicable=applicable,
            coverage=1.0 if applicable else 0.0,
            partial_status=(PartialStatus.COMPLETED if passed
                            else PartialStatus.PARTIAL),
            notes=("ASSIST ONLY (O5): never the sole judge; the human "
                   "corroborator is the ground truth for open-ended items"),
        )
