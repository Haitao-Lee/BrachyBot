"""Pure reward metrics shared by RL and deterministic regression tests."""


def normalized_oar_damage(exceed_count: int, target_voxels: int) -> float:
    """Return OAR overdose burden normalized to target volume in [0, 1]."""
    return min(1.0, max(0.0, float(exceed_count) / float(max(1, target_voxels))))
