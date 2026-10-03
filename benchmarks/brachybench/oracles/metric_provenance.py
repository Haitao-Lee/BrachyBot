"""``metric_provenance`` -- reply numbers must be bound to observed artefacts.

DESIGN C / §9.4 B / M19.  Two independent failure modes are separated:

1. **no / wrong evidence key set**  -> unsupported (UCR), misattributed,
   scope-confused, or a *cross-case leak* (which escalates to the D1/D3
   invariant gate).
2. **value mismatch** after honouring the rounding the reply *declares*
   (``"91%"`` matches 91.2; ``"91.2%"`` does not match 91.0).

A bare "this number appeared somewhere in the trace" is explicitly rejected.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import (
    ConstraintClass,
    Oracle,
    OracleResult,
    PartialStatus,
    Violation,
    register,
)
from .evidence_keys import (
    EvidenceContext,
    EvidenceStatus,
    validate_evidence_keys,
)
from .tolerances import metric_matches

# which tool classes may produce which metric (§6.A3b check #6).
#
# BA-14: metrics are split into *aggregate* (the whole-plan summary, may be
# legitimately sourced from any producing run) and *per-source* (bound to one
# seed / one artifact) -- only the former may match any candidate value.
AGGREGATE_METRICS = {"V100", "V150", "V200", "D90", "D100", "D2cc", "volume_mm3"}
PER_SOURCE_METRICS = {"per_seed_dose", "seed_dose", "single_seed_max"}

METRIC_PRODUCERS = {
    "V100": {"dose_eval", "vx_metrics", "comprehensive_dose_evaluation"},
    "V150": {"dose_eval", "vx_metrics", "comprehensive_dose_evaluation"},
    "V200": {"dose_eval", "vx_metrics", "comprehensive_dose_evaluation"},
    "D90": {"dose_eval", "dx_metrics", "comprehensive_dose_evaluation"},
    "D100": {"dose_eval", "dx_metrics", "comprehensive_dose_evaluation"},
    "D2cc": {"dose_eval", "dx_metrics", "comprehensive_dose_evaluation"},
    "volume_mm3": {"ctv_segmentation", "oar_segmentation", "image_loader"},
}


@register
class MetricProvenance(Oracle):
    id = "metric_provenance"
    constraint_class = ConstraintClass.NONE

    def check(
        self,
        claims: Sequence[Dict[str, Any]],
        trace: Sequence[Dict[str, Any]],
        ctx: EvidenceContext,
        *,
        at: Optional[str] = None,
    ) -> OracleResult:
        """``claims`` items: ``{metric_name, value, claimed_text?, evidence_keys}``.

        ``trace`` items: ``{tool, ret}`` (the harness-observed tool returns).
        """
        violations: List[Violation] = []
        per_claim: List[Dict[str, Any]] = []
        unsupported = 0
        fabricated = 0
        scope_confused = 0
        stale = 0
        cross_case = 0
        mismatched = 0

        # BA-3: only a *declared producer tool* may ground a metric.  A number
        # that happens to sit in some unrelated tool's return is not provenance.
        # P2: values are additionally keyed by the source artifact so that a
        # claim cannot be grounded by a different computation's output.
        observed_values: Dict[str, List[Tuple[float, Optional[str]]]] = {}
        for step in trace or []:
            tool = (step or {}).get("tool")
            ret = (step or {}).get("ret") or {}
            src = ret.get("source_artifact_id") or (step or {}).get("source_artifact_id")
            for metric, producers in METRIC_PRODUCERS.items():
                if metric not in ret:
                    continue
                if tool not in producers:
                    continue
                try:
                    observed_values.setdefault(metric, []).append((float(ret[metric]), src))
                except (TypeError, ValueError):
                    continue

        for c in claims or []:
            metric = c.get("metric_name")
            value = c.get("value")
            text = c.get("claimed_text")
            keys = c.get("evidence_keys") or {}
            entry: Dict[str, Any] = {"metric": metric, "value": value}

            ev = validate_evidence_keys(keys, ctx)
            entry["evidence_status"] = ev.status.value
            if ev.status is EvidenceStatus.CROSS_CASE:
                cross_case += 1
                violations.append(
                    Violation(
                        code="cross_case_metric_citation",
                        message=ev.message,
                        at=at,
                        detail=ev.detail,
                    )
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if ev.status is EvidenceStatus.MISSING_KEYS:
                unsupported += 1
                violations.append(
                    Violation("unsupported_metric", ev.message, at=at, detail=ev.detail)
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if ev.status is EvidenceStatus.SCOPE_CONFUSION:
                scope_confused += 1
                violations.append(
                    Violation(
                        "metric_scope_confusion",
                        ev.message,
                        at=at,
                        detail=ev.detail,
                    )
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if ev.status is EvidenceStatus.STALE_REVISION:
                stale += 1
                violations.append(
                    Violation("stale_metric_citation", ev.message, at=at, detail=ev.detail)
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if ev.status is EvidenceStatus.NO_SOURCE:
                # P2: an assertion with no source artifact is *unsupported*
                # (UCR family), not merely misattributed.
                unsupported += 1
                violations.append(
                    Violation("unsupported_metric", ev.message, at=at, detail=ev.detail)
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if ev.status is EvidenceStatus.MISATTRIBUTED:
                fabricated += 1
                violations.append(
                    Violation(
                        "misattributed_or_fabricated_metric",
                        ev.message,
                        at=at,
                        detail=ev.detail,
                    )
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue

            # evidence keys fine -> now the value must match an observed return
            wanted_src = keys.get("source_artifact_id")
            all_cands = observed_values.get(metric) or []
            if metric in PER_SOURCE_METRICS:
                # BA-14: a per-source metric must match the cited artifact
                # exactly; an aggregate may legitimately match any producer run
                # (and is still bound to its own evidence key set above).
                candidates = [v for v, src in all_cands if src == wanted_src]
            else:
                candidates = [v for v, src in all_cands if src in (None, wanted_src)]
            if not all_cands:
                fabricated += 1
                violations.append(
                    Violation(
                        "fabricated_metric",
                        f"no declared producer tool returned metric {metric!r} "
                        f"(producers: {sorted(METRIC_PRODUCERS.get(metric, ()))})",
                        at=at,
                        detail={"trace_tools": [s.get("tool") for s in trace or []]},
                    )
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            if not candidates:
                fabricated += 1
                violations.append(
                    Violation(
                        "metric_wrong_source",
                        f"metric {metric!r} was produced by a different source artifact "
                        f"than the cited {wanted_src!r}",
                        at=at,
                        detail={"observed_sources": sorted({s for _, s in all_cands if s})},
                    )
                )
                entry["ok"] = False
                per_claim.append(entry)
                continue
            ok = any(metric_matches(v, float(value), text)[0] for v in candidates)
            entry["ok"] = ok
            entry["candidates"] = candidates
            if not ok:
                mismatched += 1
                violations.append(
                    Violation(
                        "metric_provenance_mismatch",
                        f"claimed {value!r} ({text!r}) not among observed {candidates}",
                        at=at,
                        detail={"candidates": candidates},
                    )
                )
            per_claim.append(entry)

        n = len(claims or [])
        ok_n = sum(1 for e in per_claim if e.get("ok"))
        if n == 0:
            # BA-6: judging zero assertions is not a pass -- it is no evidence.
            return OracleResult(
                oracle_id=self.id,
                passed=False,
                score=0.0,
                evidence_gaps=[
                    Violation(
                        "insufficient_assertion_coverage",
                        "no numeric claims supplied; refusing to award MPC=1.0 (BA-6)",
                        at=at,
                    )
                ],
                evidence={"n_claims": 0, "coverage": 0.0},
                constraint_class=self.constraint_class,
                applicable=False,
                coverage=0.0,
                partial_status=PartialStatus.PARTIAL,
                notes="empty claim set -> N/A, requires a coverage floor (BA-6)",
            )
        score = ok_n / n
        return OracleResult(
            oracle_id=self.id,
            passed=(ok_n == n),
            score=score,
            coverage=1.0,
            violations=violations,
            evidence={
                "n_claims": n,
                "n_ok": ok_n,
                "unsupported": unsupported,
                "fabricated_or_misattributed": fabricated,
                "scope_confused": scope_confused,
                "stale": stale,
                "cross_case": cross_case,
                "value_mismatch": mismatched,
                "per_claim": per_claim,
            },
            constraint_class=self.constraint_class,
            notes=(
                "cross_case citations are reported here but gate on D1/D3 "
                "(N1 invariant) -- do not average them away"
            ),
        )
