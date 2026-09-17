"""Coverage boundary between a typed direct-read result and the user question.

A direct-read metric may only replace the normal synthesis/review path when
the returned payload demonstrably answers every data aspect the user asked
for.  "How many needles, and how many seeds on each needle?" is not answered
by a total seed count, so the runtime must keep the normal answer path (and
its final completeness check) instead of returning a truncated table.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, FrozenSet, Optional

ASPECT_NEEDLE_COUNT = "needle_count"
ASPECT_SEED_TOTAL = "seed_total"
ASPECT_SEEDS_PER_NEEDLE = "seeds_per_needle"

_NEEDLE_TERMS = (
    "穿刺针", "针道", "进针",
    "needle", "trajectory", "trajectories",
)
_SEED_TERMS = (
    "粒子", "放射源",
    "seed", "seeds",
)
_COUNT_PATTERN = re.compile(
    r"有多少|共有多少|总数|共计|数量|几个|几颗|几粒|几枚|几根|几支|"
    r"how many|number of|\bcount\b|\btotal\b"
)
_BREAKDOWN_TERMS = (
    "分别", "每枚", "每条", "每个", "各个", "逐一", "分布",
    "breakdown", "distribution", "per needle", "per trajectory",
    "per-needle", "each needle", "each trajectory", "each ", "per ",
)
_COVERAGE_ASPECTS = (
    ASPECT_NEEDLE_COUNT,
    ASPECT_SEED_TOTAL,
    ASPECT_SEEDS_PER_NEEDLE,
)


def _normalized(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def required_metric_aspects(message: str) -> FrozenSet[str]:
    """Return the metric aspects a question explicitly asks about.

    Only questions that name needles/seeds (and a count or per-item wording)
    return aspects.  Everything else returns an empty set so existing
    fast-path behavior is untouched.
    """
    text = _normalized(message)
    if not text:
        return frozenset()
    has_needle = any(term in text for term in _NEEDLE_TERMS)
    has_seed = any(term in text for term in _SEED_TERMS)
    if not (has_needle or has_seed):
        return frozenset()
    wants_count = bool(_COUNT_PATTERN.search(text))
    wants_breakdown = any(term in text for term in _BREAKDOWN_TERMS)
    # Only questions about seed counts or seed-per-needle quantities are
    # modeled. A per-seed attribute such as "dose of each seed" must not
    # force the distribution metric.
    if not (wants_count or (wants_breakdown and has_needle)):
        return frozenset()
    required = set()
    if has_seed:
        required.add(ASPECT_SEED_TOTAL)
    if has_needle:
        required.add(ASPECT_NEEDLE_COUNT)
    if wants_breakdown and has_seed and has_needle:
        required.add(ASPECT_SEEDS_PER_NEEDLE)
    return frozenset(required)


def _declared_covers(contract: Any) -> Optional[FrozenSet[str]]:
    if not isinstance(contract, Mapping):
        return None
    covers = contract.get("covers")
    if not isinstance(covers, (list, tuple, set, frozenset)):
        return None
    return frozenset(str(item) for item in covers)


def missing_metric_aspects(message: str, contract: Any) -> FrozenSet[str]:
    """Return the asked aspects a read result does not answer.

    Contracts without an explicit ``covers`` declaration keep the previous
    behavior (treated as covering the turn): coverage is opt-in so no
    unrelated direct-read tool is unexpectedly routed through review.
    """
    required = required_metric_aspects(message)
    if not required:
        return frozenset()
    covered = _declared_covers(contract)
    if covered is None:
        return frozenset()
    return frozenset(required - covered)


def contract_covers_turn(message: str, contract: Any) -> bool:
    return not missing_metric_aspects(message, contract)


def direct_read_decision(message: str, contracts: Any) -> tuple:
    """Resolve (covered, uncovered_aspects) for this turn's read contracts.

    Covered means at least one typed read answered every asked aspect; the
    uncovered set accumulates aspects that no read answered, so the final
    completeness check can name exactly what is missing.
    """
    covered = False
    uncovered = set()
    for contract in contracts or ():
        missing = missing_metric_aspects(message, contract)
        if missing:
            uncovered.update(missing)
        else:
            covered = True
    if covered:
        return True, frozenset()
    return False, frozenset(uncovered)


def coverage_followup_instruction(missing: Any) -> str:
    """Build the follow-up instruction that completes an uncovered read.

    The metric tool is the data authority; the runtime only tells the model
    which typed read closes the remaining aspects of the question.
    """
    aspects = ", ".join(sorted(str(item) for item in missing or ()))
    if not aspects:
        return ""
    if {ASPECT_NEEDLE_COUNT, ASPECT_SEEDS_PER_NEEDLE} & set(missing or ()):
        metric_hint = "needle_seed_counts"
    else:
        metric_hint = "seed_count"
    return (
        "\nIMPORTANT: the direct metric read above did not cover every part of the "
        f"user's question (still missing: {aspects}). Do NOT answer with that partial "
        f"result. Call query_metrics again with metric_type=\"{metric_hint}\" and then "
        "answer the complete question in the user's language."
    )
