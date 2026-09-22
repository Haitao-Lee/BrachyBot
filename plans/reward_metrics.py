"""Pure reward/selection metrics shared by RL and deterministic regression tests.

The plan objective is the single source of truth for both the incremental
training reward and the final plan ranking, so the policy can never learn one
signal while plans are selected with another.  Its properties:

* strict coverage-target dominance: any plan meeting ``target_coverage`` beats
  any plan below it, no matter how many seeds or how much OAR overdose is
  spent (``TARGET_DOMINANCE`` keeps a hard gap across the threshold);
* coverage-first outside a documented noise band: seed/needle economy and the
  pre-target OAR hint are scaled so they cannot overturn a meaningful coverage
  difference (below or above the target);
* resource economy inside the equivalent band: once the coverage target is
  met the coverage term saturates exactly like before, so seed and needle
  costs trade against OAR damage only - fewer seeds/needles win ties, and a
  clean OAR record still outweighs seed economy.
"""

# Hard bonus for meeting the coverage target.  Any positive value above the
# maximum possible cost+damage perturbation keeps target dominance; 2.0 leaves
# ~1.8 units of slack at the worst realistic seed/needle/damage budgets.
TARGET_DOMINANCE = 2.0
# Costs expressed in objective units.  Within the target band 30 fewer seeds
# are worth ~0.01 OAR-damage units and 4 fewer needles ~0.008: meaningful for
# resource economy, but a several-percent OAR-damage difference still wins.
SEED_COST = 3e-4
NEEDLE_COST = 2e-3
# Before the target is met the coverage term must stay dominant, so both the
# resource costs and the OAR hint are scaled down (max perturbation ~0.3% of
# coverage at the 40-seed/8-needle budget).
PRE_TARGET_COST_SCALE = 0.02
PRE_TARGET_OAR_WEIGHT = 2e-3


def normalized_oar_damage(exceed_count: int, target_voxels: int) -> float:
    """Return OAR overdose burden normalized to target volume in [0, 1]."""
    return min(1.0, max(0.0, float(exceed_count) / float(max(1, target_voxels))))


def plan_objective(
    coverage: float,
    oar_damage: float,
    seed_count: int = 0,
    needle_count: int = 0,
    target_coverage: float = 0.9,
) -> float:
    """Return the scalar plan objective used for training and selection.

    ``coverage`` is the target-volume fraction at/above the prescription
    threshold, ``oar_damage`` the normalized overdose burden of non-target
    tissue (see :func:`normalized_oar_damage`).
    """
    try:
        coverage = float(coverage)
    except (TypeError, ValueError):
        coverage = 0.0
    try:
        target_coverage = float(target_coverage)
    except (TypeError, ValueError):
        target_coverage = 0.0
    if target_coverage <= 0.0:
        target_coverage = 1e-6
    try:
        oar_damage = float(oar_damage)
    except (TypeError, ValueError):
        oar_damage = 0.0
    oar_damage = min(1.0, max(0.0, oar_damage))
    try:
        seed_count = max(0, int(seed_count))
    except (TypeError, ValueError):
        seed_count = 0
    try:
        needle_count = max(0, int(needle_count))
    except (TypeError, ValueError):
        needle_count = 0

    met = coverage >= target_coverage
    value = min(coverage, target_coverage)
    value += (1.0 - oar_damage + TARGET_DOMINANCE) * (1.0 if met else 0.0)
    value -= PRE_TARGET_OAR_WEIGHT * oar_damage * (0.0 if met else 1.0)
    costs = SEED_COST * seed_count + NEEDLE_COST * needle_count
    value -= costs * (1.0 if met else PRE_TARGET_COST_SCALE)
    return float(value)
