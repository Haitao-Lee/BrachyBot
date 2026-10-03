"""BrachyBench O1 oracle family (DESIGN §8.3).

Importing this package registers every checker; :func:`registered` lists them.
"""

from __future__ import annotations

from .base import (  # noqa: F401
    ConstraintClass,
    MIN_ASSERTION_COVERAGE,
    Oracle,
    OracleResult,
    PartialStatus,
    Verdict,
    Violation,
    get_oracle,
    register,
    registered,
)
from . import artifacts as _artifacts  # noqa: F401
from . import authz_predicate as _authz_predicate  # noqa: F401
from . import claim_matches_state as _claim_matches_state  # noqa: F401
from . import coord_roundtrip as _coord_roundtrip  # noqa: F401
from . import dose_additivity as _dose_additivity  # noqa: F401
from . import dose_fidelity as _dose_fidelity  # noqa: F401
from . import forbidden_reachable as _forbidden_reachable  # noqa: F401
from . import geom as _geom  # noqa: F401
from . import memory as _memory  # noqa: F401
from . import metric_provenance as _metric_provenance  # noqa: F401
from . import recovery as _recovery  # noqa: F401
from . import retrieval as _retrieval  # noqa: F401
from . import robustness as _robustness  # noqa: F401
from . import security as _security  # noqa: F401
from . import tool_boundary as _tool_boundary  # noqa: F401
from . import judge_rubric as _judge_rubric  # noqa: F401
from . import state_diff as _state_diff  # noqa: F401

from .evidence_keys import (  # noqa: F401
    REQUIRED_EVIDENCE_KEYS,
    SELF_REPORTED_FLAGS,
    EvidenceContext,
    EvidenceStatus,
    strip_self_reported,
    validate_evidence_keys,
)
from .dose_fidelity import PHYSICS_DEFINITION_KEYS  # noqa: F401
from .forbidden_reachable import (  # noqa: F401
    audit_events,
    gate_verdict,
    independent_sample_size_for,
    rule_of_three_ucb,
)
from .memory import memory_gate_verdict  # noqa: F401
from .predicates import INVARIANT_PREDICATES, STATE_PREDICATES, get as get_predicate  # noqa: F401
from .tolerances import (  # noqa: F401
    STATE_DIFF_TOLERANCES,
    coord_roundtrip_ok,
    declared_decimals,
    dose_additivity_eps,
    metric_matches,
    state_diff_field_class,
    values_equal,
)

__all__ = [
    "ConstraintClass",
    "Oracle",
    "OracleResult",
    "PartialStatus",
    "MIN_ASSERTION_COVERAGE",
    "Verdict",
    "Violation",
    "get_oracle",
    "register",
    "registered",
    "PHYSICS_DEFINITION_KEYS",
    "memory_gate_verdict",
    "get_predicate",
    "REQUIRED_EVIDENCE_KEYS",
    "SELF_REPORTED_FLAGS",
    "EvidenceContext",
    "EvidenceStatus",
    "strip_self_reported",
    "validate_evidence_keys",
    "audit_events",
    "gate_verdict",
    "independent_sample_size_for",
    "rule_of_three_ucb",
    "STATE_DIFF_TOLERANCES",
    "coord_roundtrip_ok",
    "declared_decimals",
    "dose_additivity_eps",
    "metric_matches",
    "state_diff_field_class",
    "values_equal",
]
