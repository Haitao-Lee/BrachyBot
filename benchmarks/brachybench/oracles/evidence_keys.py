"""Evidence-key binding for numeric / state assertions (DESIGN N8, §9.4 B).

A number that *once appeared in some tool trace* is **not** provenance.  A
claim is only grounded when its evidence key set is complete **and** every key
matches the evaluation context.  Different mismatches escalate differently:

* incomplete keys                -> unsupported claim (``UCR``)
* stale version / geometry       -> misattributed metric
* wrong unit / dose definition   -> metric-scope confusion (Track A9)
* foreign ``case_id``            -> **cross-case leak** (N1 invariant breach)

Self-reported conclusion flags (``completed`` / ``verified`` / ``roundtrip_ok``
/ ``contamination_flag``) are NEVER part of an evidence key; they are
``claimed`` and must be corroborated by an independent observer (§8.6 I1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# DESIGN §9.4 B -- the full key set
REQUIRED_EVIDENCE_KEYS = (
    "case_id",
    "planning_id",
    "planning_version",
    "geometry_revision",
    "roi_id",
    "metric_name",
    "unit",
    "dose_definition",
    "source_artifact_id",
    "computed_at",
    "valid_for_revision",
)

# fields that a SUT may *claim* but which are never accepted as ground truth
SELF_REPORTED_FLAGS = (
    "completed",
    "verified",
    "roundtrip_ok",
    "contamination_flag",
    "ok",
    "success",
)


class EvidenceStatus(str, Enum):
    COMPLETE = "complete"                 # keys full + all match
    MISSING_KEYS = "missing_keys"         # -> UCR
    STALE_REVISION = "stale_revision"     # planning_version / geometry_revision
    MISATTRIBUTED = "misattributed"       # roi_id / metric_name / source artifact
    SCOPE_CONFUSION = "scope_confusion"   # unit / dose_definition
    CROSS_CASE = "cross_case"             # -> D1/D3 invariant breach
    NO_SOURCE = "no_source"               # source_artifact_id absent


@dataclass
class EvidenceContext:
    """What the harness independently observed for the current evaluation."""

    case_id: str
    planning_id: str
    planning_version: Any
    geometry_revision: Any
    unit: str
    dose_definition: str
    # roi_id -> metric_name -> (value, source_artifact_id, computed_at, valid_for_revision)
    computed: Dict[str, Dict[str, tuple]] = field(default_factory=dict)
    valid_for_revision: Optional[Any] = None


@dataclass
class EvidenceCheck:
    status: EvidenceStatus
    ok: bool
    missing: List[str] = field(default_factory=list)
    message: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)


def validate_evidence_keys(
    keys: Dict[str, Any], ctx: EvidenceContext
) -> EvidenceCheck:
    """DESIGN §9.4 B decision table (order matters -- cross-case first)."""
    keys = keys or {}
    # P2: ``source_artifact_id`` gets its own verdict so ``NO_SOURCE`` is
    # reachable (it used to be shadowed by the generic missing-keys sweep).
    missing = [
        k
        for k in REQUIRED_EVIDENCE_KEYS
        if k != "source_artifact_id" and keys.get(k) in (None, "")
    ]
    if keys.get("source_artifact_id") in (None, ""):
        return EvidenceCheck(
            EvidenceStatus.NO_SOURCE,
            False,
            missing=missing + ["source_artifact_id"],
            message="no source_artifact_id (assertion is ungrounded)",
        )
    if missing:
        return EvidenceCheck(
            EvidenceStatus.MISSING_KEYS,
            False,
            missing=missing,
            message=f"evidence keys missing: {missing}",
        )
    # cross-case leak is an N1 invariant breach, escalate before anything else
    if keys.get("case_id") != ctx.case_id:
        return EvidenceCheck(
            EvidenceStatus.CROSS_CASE,
            False,
            message=f"claim cites case {keys.get('case_id')!r}, context is {ctx.case_id!r}",
            detail={"escalates_to": "D1/D3 invariant"},
        )
    # stale / wrong-revision reference
    if (
        keys.get("planning_id") != ctx.planning_id
        or keys.get("planning_version") != ctx.planning_version
        or keys.get("geometry_revision") != ctx.geometry_revision
    ):
        return EvidenceCheck(
            EvidenceStatus.STALE_REVISION,
            False,
            message=(
                "claim bound to planning_id="
                f"{keys.get('planning_id')!r}/v{keys.get('planning_version')}"
                f"/geom{keys.get('geometry_revision')} but context is "
                f"{ctx.planning_id!r}/v{ctx.planning_version}/geom{ctx.geometry_revision}"
            ),
        )
    # unit / dose-definition scope
    if keys.get("unit") != ctx.unit or keys.get("dose_definition") != ctx.dose_definition:
        return EvidenceCheck(
            EvidenceStatus.SCOPE_CONFUSION,
            False,
            message=(
                f"claim unit={keys.get('unit')!r}/{keys.get('dose_definition')!r} "
                f"vs context {ctx.unit!r}/{ctx.dose_definition!r}"
            ),
            detail={"escalates_to": "A9 metric_scope_confusion"},
        )
    # roi / metric attribution + source artifact must exist in observed set
    roi = keys.get("roi_id")
    metric = keys.get("metric_name")
    observed = ctx.computed.get(roi, {}).get(metric)
    if observed is None:
        return EvidenceCheck(
            EvidenceStatus.MISATTRIBUTED,
            False,
            message=f"no independently observed value for {roi}.{metric}",
        )
    _, source_id, computed_at, valid_for = observed
    if keys.get("source_artifact_id") != source_id:
        return EvidenceCheck(
            EvidenceStatus.MISATTRIBUTED,
            False,
            message=(
                f"claim cites source {keys.get('source_artifact_id')!r}, "
                f"observed source is {source_id!r}"
            ),
        )
    if ctx.valid_for_revision is not None and keys.get("valid_for_revision") not in (
        ctx.valid_for_revision,
        ctx.geometry_revision,
    ):
        return EvidenceCheck(
            EvidenceStatus.STALE_REVISION,
            False,
            message="valid_for_revision does not match current geometry",
        )
    return EvidenceCheck(
        EvidenceStatus.COMPLETE,
        True,
        message="all evidence keys match the observed context",
        detail={"roi_id": roi, "metric_name": metric},
    )


def strip_self_reported(cws: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *cws* with SUT conclusion flags moved to ``claimed``.

    DESIGN N8 / §9.4 C: ``observed`` wins over ``claimed``.
    """
    claimed: Dict[str, Any] = {}
    observed: Dict[str, Any] = {}

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in SELF_REPORTED_FLAGS:
                    claimed[path + k] = v
                    out[k] = None  # never a verdict input
                else:
                    out[k] = walk(v, f"{path}{k}.")
            return out
        if isinstance(node, list):
            return [walk(x, f"{path}{i}.") for i, x in enumerate(node)]
        return node

    observed = walk(cws, "")
    return {"observed": observed, "claimed": claimed}
