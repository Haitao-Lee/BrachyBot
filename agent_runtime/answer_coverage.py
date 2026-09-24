"""Coverage boundary between a typed direct-read result and the user question.

A direct-read metric may only replace the normal synthesis/review path when
the returned payload demonstrably answers every data aspect the user asked
for. For example, a total seed count does not answer a per-needle question,
and an OAR volume does not answer an OAR dose question.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, FrozenSet, Optional

ASPECT_NEEDLE_COUNT = "needle_count"
ASPECT_SEED_TOTAL = "seed_total"
ASPECT_SEEDS_PER_NEEDLE = "seeds_per_needle"
ASPECT_OAR_DOSE = "oar_dose"

_NEEDLE_TERMS = (
    "穿刺针", "针道", "进针",
    "needle", "trajectory", "trajectories",
)
_SEED_TERMS = (
    "粒子", "放射源",
    "seed", "seeds",
)
_OAR_DOSE_TERMS = (
    "剂量", "受照", "受量", "辐射", "照射", "剂量学", "dmax", "dmean",
    "d0.1cc", "d1cc", "d2cc", "v100", "v150", "gy", "dose",
    "radiation", "irradiat", "received dose", "organ dose",
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

    Needle/seed questions require count or per-item wording. OAR dose
    questions are modeled independently, so an organ-only request can be
    recognized without mentioning needles or seeds.
    """
    text = _normalized(message)
    if not text:
        return frozenset()
    has_needle = any(term in text for term in _NEEDLE_TERMS)
    has_seed = any(term in text for term in _SEED_TERMS)
    has_oar = any(term in text for term in ("危及器官", "器官")) or bool(
        re.search(r"\b(?:organs?|oars?)\b", text)
    )
    asks_oar_dose = any(term in text for term in _OAR_DOSE_TERMS)
    required = set()
    if has_oar and asks_oar_dose:
        required.add(ASPECT_OAR_DOSE)
    if not (has_needle or has_seed):
        return frozenset(required)
    wants_count = bool(_COUNT_PATTERN.search(text))
    wants_breakdown = any(term in text for term in _BREAKDOWN_TERMS)
    # Only questions about seed counts or seed-per-needle quantities are
    # modeled. A per-seed attribute such as "dose of each seed" must not
    # force the distribution metric.
    if wants_count or (wants_breakdown and has_needle):
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


def uncovered_metric_aspects(message: str, contracts: Any) -> FrozenSet[str]:
    """Return asked aspects that no read result in this turn answered.

    Coverage is computed over the UNION of every contract's ``covers`` set: a
    per-contract gap is not a turn-level gap (2026-09-22 regression: a spacing
    read declares only ``["spacing"]``, so its gap poisoned the needle/seed
    aspects that a ``needle_seed_counts`` read had already answered, and the
    model then denied the returned needle/seed table).

    Turns without any typed read return an empty set so free-text tool turns
    never gain coverage claims.
    """
    required = required_metric_aspects(message)
    if not required:
        return frozenset()
    covered = set()
    saw_contract = False
    for contract in contracts or ():
        saw_contract = True
        declared = _declared_covers(contract)
        if declared is None:
            # Undeclared contract: treated as covering the whole turn.
            return frozenset()
        covered |= set(declared)
    if not saw_contract:
        return frozenset()
    return frozenset(required - covered)


def direct_read_decision(message: str, contracts: Any) -> tuple:
    """Resolve (covered, uncovered_aspects) for this turn's read contracts.

    Covered means the union of the typed reads answered every asked aspect;
    the uncovered set names the aspects no read answered, so the final
    completeness check can name exactly what is missing.
    """
    gaps = uncovered_metric_aspects(message, contracts)
    if gaps:
        return False, gaps
    if not contracts:
        # No typed read at all: keep the previous (False, empty) contract so
        # callers do not treat an evidence-synthesis turn as a direct read.
        return False, frozenset()
    return True, frozenset()


def coverage_followup_instruction(missing: Any, covered: Any = ()) -> str:
    """Build the follow-up instruction that completes an uncovered read.

    The metric tool is the data authority; the runtime only tells the model
    which typed read closes the remaining aspects of the question.  Aspects
    the reads DID answer are named as returned evidence — the instruction
    must never deny data the tool results contain (2026-09-22 regression).
    """
    missing = {str(item) for item in missing or ()}
    if not missing:
        return ""
    aspects = ", ".join(sorted(missing))
    if ASPECT_OAR_DOSE in missing:
        metric_hint = "oar_dose_metrics"
    elif {ASPECT_NEEDLE_COUNT, ASPECT_SEEDS_PER_NEEDLE} & missing:
        metric_hint = "needle_seed_counts"
    else:
        metric_hint = "seed_count"
    covered_line = ""
    covered_set = {str(item) for item in covered or ()}
    if covered_set:
        covered_list = ", ".join(sorted(covered_set))
        covered_line = (
            "\nAlready returned by this turn's metric reads (answer these parts "
            f"directly from the tool results; never claim they were not "
            f"returned): {covered_list}."
        )
    return (
        "\nIMPORTANT — coverage of the user's question by this turn's metric reads:"
        f"{covered_line}\n"
        f"Still NOT in the tool results: {aspects}.\n"
        "For the returned parts, answer directly from the tool results above and "
        "never deny or omit them. For the missing parts only, either call "
        f"query_metrics with metric_type=\"{metric_hint}\" if another round is "
        "available, or state plainly that this turn's tool results do not contain "
        "that specific data. Never invent it."
    )
