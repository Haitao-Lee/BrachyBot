"""Shared cumulative-DVH construction helpers.

The application exposes both scalar dose metrics (for example ``V100``) and
sampled cumulative DVH curves.  A histogram's bin centres are only an
approximation of a requested dose threshold, so a curve that does not contain
the exact threshold can disagree with the scalar metric by one or more
voxels.  This module keeps the two representations on the same contract by
allowing clinically meaningful thresholds to be emitted as exact curve
anchors.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import numpy as np


def build_cumulative_dvh(
    structure_doses: Any,
    *,
    dose_min: Optional[float] = None,
    dose_max: Optional[float] = None,
    num_bins: int = 600,
    anchor_doses: Optional[Iterable[float]] = None,
) -> Dict[str, List[float]]:
    """Build a cumulative DVH with exact values at requested dose anchors.

    ``volume_pcts`` is defined as the percentage of finite structure voxels
    whose dose is greater than or equal to the corresponding dose in
    ``dose_bins``.  The regular samples remain useful for plotting, while
    every finite value in ``anchor_doses`` is inserted verbatim and evaluated
    by the same direct ``>=`` count used by scalar Vx metrics.

    ``dose_min``/``dose_max`` describe the plotting range of the regular
    samples.  Anchor doses extend the upper range when necessary so a zero
    coverage threshold is still represented rather than silently clipped.
    """

    doses = np.asarray(structure_doses, dtype=np.float64).reshape(-1)
    doses = doses[np.isfinite(doses)]
    if doses.size == 0:
        return {"dose_bins": [], "volume_pcts": []}

    anchors: List[float] = []
    for value in anchor_doses or ():
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(parsed):
            anchors.append(parsed)

    lower = float(np.min(doses)) if dose_min is None else float(dose_min)
    upper = float(np.max(doses)) if dose_max is None else float(dose_max)
    if anchors:
        # Do not discard an exact requested threshold just because an old
        # caller supplied a plotting range that ended below it.  Extending the
        # range preserves the scalar Vx=0% result and makes the curve honest.
        lower = min(lower, min(anchors))
        upper = max(upper, max(anchors))
    if not np.isfinite(lower) or not np.isfinite(upper):
        return {"dose_bins": [], "volume_pcts": []}
    if upper <= lower:
        upper = lower + 1.0

    try:
        bins = max(2, int(num_bins))
    except (TypeError, ValueError):
        bins = 600
    regular_edges = np.linspace(lower, upper, bins + 1, dtype=np.float64)
    regular_centers = (regular_edges[:-1] + regular_edges[1:]) / 2.0

    if anchors:
        dose_points = np.unique(np.concatenate((regular_centers, np.asarray(anchors))))
    else:
        dose_points = regular_centers

    volume_pcts = [
        float(np.count_nonzero(doses >= threshold) / doses.size * 100.0)
        for threshold in dose_points
    ]
    return {
        "dose_bins": dose_points.tolist(),
        "volume_pcts": volume_pcts,
    }


__all__ = ["build_cumulative_dvh"]
