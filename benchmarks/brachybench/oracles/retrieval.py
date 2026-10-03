"""Retrieval / citation grounding checkers (DESIGN §8.3, tracks A5b/C).

Implements: ``retrieval_at_k``, ``citation_existence``, ``passage_support``.

R8: a number or a claim is only grounded when its source really exists and the
cited passage actually supports it.  Existence and Recall@k are pure O1;
``passage_support`` is ``O1 structural + O5(assist) + human spot check`` and is
labelled as such (M12).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from .base import ConstraintClass, Oracle, OracleResult, PartialStatus, Violation, register

PMID_RE = re.compile(r"PMID[:\s]*(\d{4,9})", re.I)
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


@register
class RetrievalAtK(Oracle):
    """§8.3 ``retrieval_at_k``: P@k / R@k / MRR against a gold passage set."""

    id = "retrieval_at_k"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        retrieved: Sequence[Sequence[str]],
        gold: Sequence[Sequence[str]],
        *,
        k: int = 5,
        recall_min: Optional[float] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``retrieved``/``gold`` are per-query ranked id lists."""
        if len(retrieved) != len(gold):
            return OracleResult(
                oracle_id=self.id, passed=False, score=0.0,
                violations=[Violation(
                    "query_count_mismatch", f"{len(retrieved)} vs {len(gold)}", at=at)],
                constraint_class=self.constraint_class)
        p_sum = r_sum = mrr_sum = 0.0
        per: List[Dict[str, Any]] = []
        for i, (ret, g) in enumerate(zip(retrieved, gold)):
            gs: Set[str] = set(map(str, g or []))
            top = [str(x) for x in (ret or [])[:k]]
            hits = set(top) & gs
            p = len(hits) / k if k else 0.0
            r = (len(set(hits) & gs) / len(gs)) if gs else 1.0
            mrr = 0.0
            for rank, x in enumerate(top, 1):
                if x in gs:
                    mrr = 1.0 / rank
                    break
            p_sum += p
            r_sum += r
            mrr_sum += mrr
            per.append({"query": i, "p_at_k": p, "r_at_k": r, "mrr": mrr, "n_gold": len(gs)})
        n = max(len(retrieved), 1)
        mean_p, mean_r, mean_mrr = p_sum / n, r_sum / n, mrr_sum / n
        violations: List[Violation] = []
        if recall_min is not None and mean_r < recall_min:
            violations.append(Violation(
                "recall_below_threshold", f"R@{k} = {mean_r:.3f} < {recall_min}", at=at))
        passed = not violations
        return OracleResult(
            oracle_id=self.id, passed=passed, score=float(mean_r),
            violations=violations,
            evidence={"k": k, "p_at_k": mean_p, "r_at_k": mean_r, "mrr": mean_mrr,
                      "per_query": per},
            constraint_class=self.constraint_class)


@register
class CitationExistence(Oracle):
    """§8.3 ``citation_existence``: every cited PMID / DOI / URL / guideline
    clause resolves to something real (target rate 1.0).

    ``resolver`` is injected so tests can stub the network; production must
    supply a resolver that actually checks (§8.6 I3).
    """

    id = "citation_existence"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        citations: Sequence[Dict[str, Any]],
        *,
        resolver: Optional[Callable[[str, str], bool]] = None,
        guideline_clauses: Optional[Dict[str, Sequence[str]]] = None,
        at: Optional[str] = None,
    ) -> OracleResult:
        violations: List[Violation] = []
        per: List[Dict[str, Any]] = []
        gaps: List[Violation] = []
        for c in citations or []:
            text = c.get("text") or c.get("raw") or ""
            kinds = []
            entry: Dict[str, Any] = {"raw": text[:80], "checked": []}
            m = PMID_RE.search(text)
            if m:
                kinds.append(("pmid", m.group(1)))
            m = DOI_RE.search(text)
            if m:
                kinds.append(("doi", m.group(1).rstrip(".,;)")))
            m = URL_RE.search(text)
            if m:
                kinds.append(("url", m.group(0).rstrip(".,;)")))
            if c.get("guideline_ref"):
                kinds.append(("clause", c["guideline_ref"]))
            if not kinds:
                violations.append(Violation(
                    "citation_not_identifiable",
                    f"no PMID/DOI/URL/clause recognisable in {text[:60]!r}", at=at))
                entry["ok"] = False
                per.append(entry)
                continue
            ok_all = True
            for kind, val in kinds:
                if kind == "clause":
                    doc, _, clause = val.partition("#")
                    allowed = (guideline_clauses or {}).get(doc)
                    if allowed is None:
                        gaps.append(Violation("guideline_source_unavailable", f"no independently registered clauses for {doc}", at=at))
                        ok_all = False
                        continue
                    ok = clause in allowed
                elif resolver is None:
                    # without a resolver we cannot assert existence (I3)
                    entry["checked"].append((kind, val, "no-resolver"))
                    gaps.append(Violation("citation_resolver_unavailable", f"cannot verify {kind}={val}", at=at))
                    ok_all = False
                    continue
                else:
                    ok = resolver(kind, val) is True
                entry["checked"].append((kind, val, ok))
                if not ok:
                    ok_all = False
                    violations.append(Violation(
                        "citation_not_resolvable", f"{kind}={val!r} does not resolve", at=at))
            entry["ok"] = ok_all
            per.append(entry)
        n = len(citations or [])
        passed = not violations and not gaps and n > 0
        return OracleResult(
            oracle_id=self.id, passed=passed,
            score=(sum(1 for e in per if e.get("ok")) / n) if n else 0.0,
            violations=violations + ([] if n else [Violation(
                "no_citations", "no citations to check", at=at)]),
            evidence={"per_citation": per, "n": n,
                      "resolver_supplied": resolver is not None},
            evidence_gaps=gaps,
            constraint_class=self.constraint_class,
            applicable=n > 0 and not gaps,
            notes="existence only; supporting-evidence is PassageSupport (M12: O1+O5+human)",
        )


@register
class PassageSupport(Oracle):
    """§8.3 ``passage_support``: does the cited passage actually support the
    claim?

    **M12: this is ``O1 structural + O5(assist) + human spot check``, never
    pure O1.**  The structural half is checkable: the claim's key entities and
    numbers must appear in the passage.  The entailment half is delegated to an
    ``assessor`` (the O5 judge) whose output is *assist only* and must be
    corroborated by human review at the rate set in §8.5.
    """

    id = "passage_support"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        assessor: Optional[Callable[[str, str], Dict[str, Any]]] = None,
        human_reviewed: Optional[Dict[str, bool]] = None,
        support_min: float = 0.8,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``items``: ``{"claim": str, "passage": str, "numbers": [...], "entities": [...]}``."""
        violations: List[Violation] = []
        gaps: List[Violation] = []
        per: List[Dict[str, Any]] = []
        for i, it in enumerate(items or []):
            claim, passage = it.get("claim") or "", it.get("passage") or ""
            entry: Dict[str, Any] = {"i": i}
            # O1 structural half: every cited number/entity must appear
            missing = []
            for num in it.get("numbers") or []:
                if str(num) not in passage:
                    missing.append(("number", num))
            for ent in it.get("entities") or []:
                if str(ent).lower() not in passage.lower():
                    missing.append(("entity", ent))
            structurally_ok = not missing
            entry["structural_ok"] = structurally_ok
            entry["missing"] = missing
            if not structurally_ok:
                violations.append(Violation(
                    "passage_lacks_claim_content",
                    f"item {i}: passage does not contain {missing}", at=at))
            # O5 assist half
            if assessor is not None:
                verdict = assessor(claim, passage) or {}
                entry["assessor"] = verdict
                if not verdict.get("supports", False):
                    violations.append(Violation(
                        "passage_does_not_support_claim",
                        f"item {i}: assessor says passage does not entail the claim",
                        at=at, detail=verdict))
            else:
                gaps.append(Violation(
                    "no_entailment_assessor",
                    "only the structural half was checked; entailment needs an "
                    "O5 assessor + human spot check (M12)",
                    at=at))
            # human corroboration
            if human_reviewed is not None:
                entry["human_ok"] = human_reviewed.get(str(i))
                if entry["human_ok"] is False:
                    violations.append(Violation("human_rejected_support", f"item {i}: human rejected entailment", at=at))
            per.append(entry)
        n = len(items or [])
        support_rate = (sum(1 for e in per if e.get("structural_ok") and
                            (e.get("assessor") or {}).get("supports") is True
                            and e.get("human_ok") is not False) / n) if n else 0.0
        applicable = assessor is not None
        passed = applicable and not violations and support_rate >= support_min
        return OracleResult(
            oracle_id=self.id, passed=passed, score=float(support_rate),
            violations=violations, evidence_gaps=gaps,
            evidence={"per_item": per, "n": n, "support_rate": support_rate,
                      "oracle_level": "O1 + O5(assist) + human spot check (M12)",
                      "human_reviewed": human_reviewed is not None},
            constraint_class=self.constraint_class,
            applicable=applicable,
            coverage=1.0 if n else 0.0,
            partial_status=PartialStatus.PARTIAL if not applicable else PartialStatus.COMPLETED,
        )
