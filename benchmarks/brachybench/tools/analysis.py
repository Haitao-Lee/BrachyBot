"""Statistical analysis for BrachyBench (DESIGN §11).

Pure-stdlib + numpy/scipy where available.  Implements the protocol of §11
rather than a general stats library:

* :func:`cluster_bootstrap_ci` -- **scenario-level** cluster bootstrap (N3/R13:
  the independent unit is a Task Scenario, never an item, never a rerun)
* :func:`power_curve` / :func:`mcnemar_n_total` -- power simulation inputs,
  Holm-aware (N4: closed-form alone is not sufficient)
* :func:`holm_adjust` -- multiplicity for the confirmatory hypotheses
* :func:`kendall_tau_stability` -- composite-weight sensitivity (R18)
* :func:`rule_of_three_ucb` / :func:`independent_sample_size_for` -- §11.4
* :func:`gate_outcome` -- the three-outcome mapping (N6)
* :func:`irt_rasch_joint` -- per-track Rasch calibration (M7/N20: exploratory)
* :func:`gwet_ac1` -- chance-corrected agreement robust to prevalence (§11.10)
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# §11.2 cluster bootstrap -- the resampling unit is the Task Scenario
# ---------------------------------------------------------------------------


def cluster_bootstrap_ci(
    cluster_values: Sequence[Sequence[float]],
    *,
    n_boot: int = 10_000,
    alpha: float = 0.05,
    statistic: str = "mean",
    seed: int = 0,
) -> Dict[str, float]:
    """Bootstrap CI over *clusters* (task scenarios), keeping members whole.

    ``cluster_values[i]`` is scenario ``i``'s vector of member-level outcomes
    (its G-EQ / G-CT members, or its N reruns).  Resampling clusters and
    averaging the scenario summaries gives every independent scenario equal
    weight. Expression variants and repeats never inflate the sample size.
    """
    cluster_values = [list(v) for v in cluster_values if len(v)]
    if not 0 < alpha < 1 or n_boot < 1 or statistic not in ("mean", "max"):
        raise ValueError("invalid bootstrap configuration")
    if any(not np.isfinite(v).all() for v in cluster_values):
        raise ValueError("nonfinite cluster outcomes")
    if not cluster_values:
        return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "n_clusters": 0, "n_members": 0}

    def stat(vectors):
        summaries = [np.mean(vec) if statistic == "mean" else np.max(vec) for vec in vectors]
        return float(np.mean(summaries))

    point = stat(cluster_values)
    rng = np.random.default_rng(seed)
    idx = np.arange(len(cluster_values))
    draws = np.empty(n_boot)
    for b in range(n_boot):
        take = rng.choice(idx, size=len(idx), replace=True)
        draws[b] = stat([cluster_values[i] for i in take])
    lo, hi = np.percentile(draws, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "point": point, "lo": float(lo), "hi": float(hi),
        "n_clusters": len(cluster_values),
        "n_members": sum(len(v) for v in cluster_values),
        "resampling_unit": "task_scenario",
        "estimand": "equal_weight_scenario_mean",
        "degenerate": bool(np.ptp(draws) == 0),
    }


def icc_decomposition(
    cluster_values: Sequence[Sequence[float]],
    *,
    n_runs: Optional[int] = None,
) -> Dict[str, float]:
    """Exploratory one-way scenario ICC, not a three-level decomposition.

    Flat vectors do not identify member and run variance. Do not invent them
    from n_runs; structured repeated observations need a separate mixed model.
    """
    arrs = [np.asarray(v, dtype=float) for v in cluster_values if len(v)]
    if not arrs:
        return {"icc_scenario": None, "icc_member": None, "icc_run": None,
                "identified": False, "method": "one_way_exploratory"}
    k = np.mean([a.size for a in arrs])
    grand = np.mean(np.concatenate(arrs))
    ms_between = k * np.mean([(a.mean() - grand) ** 2 for a in arrs])
    ms_within = np.mean([np.mean((a - a.mean()) ** 2) for a in arrs])
    var_between = max((ms_between - ms_within) / k, 0.0)
    var_within = ms_within
    total = var_between + var_within
    icc = (var_between / total) if total > 0 else 0.0
    return {
        "icc_scenario": float(icc),
        "icc_member": None, "icc_run": None,
        "identified": False, "method": "one_way_exploratory",
        "limitation": "member/run components require separately indexed repeated observations",
    }


# ---------------------------------------------------------------------------
# §11.1 power (N4): Holm-aware, paired; simulation over the planned analysis
# ---------------------------------------------------------------------------


def mcnemar_n_total(p10: float, p01: float, z: float = 1.959964,
                    z_beta: float = 0.8416212) -> float:
    """DESIGN §11.1 / M9: required **total pairs**.

    ``p10``/``p01`` are proportions of *all* pairs (not conditional on being
    discordant), so the result is a total group count.  With Holm the caller
    passes the adjusted ``z``.
    """
    if p10 + p01 <= 0 or abs(p10 - p01) <= 0:
        return float("inf")
    return (z + z_beta) ** 2 * (p10 + p01) / (p10 - p01) ** 2


def two_prop_n_per_arm(h: float, z: float = 1.959964,
                       z_beta: float = 0.8416212) -> float:
    """Cohen's-h arcsine form (N4: 375/arm at h=0.20453, not 356)."""
    return 2.0 * (z + z_beta) ** 2 / (h * h)


def cohens_h(p1: float, p2: float) -> float:
    return 2.0 * math.asin(math.sqrt(p2)) - 2.0 * math.asin(math.sqrt(p1))


def holm_adjust(pvalues: Sequence[float]) -> List[float]:
    """Holm-Bonferroni step-down (§11.8)."""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    out = [0.0] * n
    running = 0.0
    for rank, i in enumerate(order):
        adj = min(1.0, (n - rank) * pvalues[i])
        running = max(running, adj)
        out[i] = running
    return out


def power_curve(
    scenario_counts: Sequence[int],
    *,
    p10_grid: Sequence[float] = (0.10, 0.20, 0.30),
    net_diff: float = 0.10,
    z_beta: float = 0.8416212,
    alpha: float = 0.05,
    n_hypotheses: int = 3,
    holm: bool = True,
) -> List[Dict[str, float]]:
    """DESIGN §11.1 S5: sample size x discordance x power.

    Under the paired normal approximation the non-centrality is
    ``delta = |p10-p01| * sqrt(G / (p10+p01))`` and power is
    ``Phi(delta - z_crit)``.  With Holm the most stringent hypothesis uses
    ``alpha/n_hypotheses``; the others are easier.  We report the
    *conservative* (most stringent) power so a plan sized on this curve keeps
    its promise after correction (N4).
    """
    from math import erf, sqrt

    def phi(x: float) -> float:
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))

    if not 0 < alpha < 1 or n_hypotheses < 1:
        raise ValueError("invalid alpha or hypothesis count")
    z_crit = _z_from_alpha(alpha / n_hypotheses if holm else alpha)
    rows = []
    for G in scenario_counts:
        for pd in p10_grid:
            p10, p01 = (pd + net_diff) / 2.0, (pd - net_diff) / 2.0
            p10, p01 = max(p10, 0.0), max(p01, 0.0)
            disc = p10 + p01
            if disc <= 0:
                continue
            delta = abs(p10 - p01) * sqrt(G / disc)
            power = phi(delta - z_crit)
            rows.append({
                "G": G, "discordant_rate": disc, "net_diff": abs(p10 - p01),
                "z_crit": z_crit, "power": power,
                "n_total_required": mcnemar_n_total(p10, p01, z=z_crit, z_beta=z_beta),
                "method": "paired_normal_approximation_not_mixed_model_simulation",
            })
    return rows


def _z_from_alpha(alpha_two_sided: float) -> float:
    """Inverse normal CDF of ``1 - alpha/2`` (Acklam rational approximation)."""
    a = alpha_two_sided / 2.0
    # bisection is plenty here and keeps the file dependency-free
    lo, hi = -10.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        cdf = 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0)))
        if cdf < 1.0 - a:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# §11.4 rule of three (N6/M6: denominator is independent scenarios)
# ---------------------------------------------------------------------------


def rule_of_three_ucb(G: int) -> float:
    if G <= 0:
        return 1.0
    return 1.0 - 0.05 ** (1.0 / G)


def binomial_upper_bound(events: int, n: int, alpha: float = .05) -> float:
    """Exact one-sided Clopper-Pearson upper bound, including nonzero events.

    Invert the binomial CDF in log space; no optional library is needed.
    """
    if not isinstance(events, int) or not isinstance(n, int) or not 0 <= events <= n:
        raise ValueError("events and n must be valid integer counts")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if n == 0 or events == n:
        return 1.0
    if events == 0:
        return 1 - alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(64):
        p = (lo + hi) / 2
        logs = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                + k * math.log(p) + (n - k) * math.log1p(-p) for k in range(events + 1)]
        peak = max(logs)
        log_cdf = peak + math.log(sum(math.exp(v - peak) for v in logs))
        if log_cdf > math.log(alpha):
            lo = p
        else:
            hi = p
    return (lo + hi) / 2


def binomial_interval(events: int, n: int, alpha: float = .05) -> Dict[str, float]:
    if n <= 0:
        return {"point": None, "lo": None, "hi": None, "n_clusters": 0}
    return {"point": events / n,
            "lo": 0.0 if events == 0 else 1 - binomial_upper_bound(n - events, n, alpha / 2),
            "hi": 1.0 if events == n else binomial_upper_bound(events, n, alpha / 2),
            "n_clusters": n, "method": "exact_binomial_scenario_interval"}


def independent_sample_size_for(target_ucb: float) -> int:
    """5% -> 59 ; 3% -> 99 ; 1% -> 299 ; 0.5% -> 598 ; 0.1% -> 2995 (ceil)."""
    if not 0.0 < target_ucb < 1.0:
        raise ValueError("target_ucb must be in (0, 1)")
    return int(math.ceil(math.log(0.05) / math.log(1.0 - target_ucb)))


def gate_outcome(
    *,
    confirmed_violations: int,
    independent: bool,
    G: Optional[int],
    threshold_ucb: float,
    applicable: bool = True,
) -> str:
    """DESIGN §11.4 / N6 three outcomes.

    ``Does not meet`` dominates; thin evidence is ``Insufficient evidence``,
    never ``Meets`` and never a confirmed violation.
    """
    if confirmed_violations > 0:
        return "Does not meet"
    if not independent or not applicable:
        return "Insufficient evidence for the benchmark criterion"
    if G is None or rule_of_three_ucb(G) > threshold_ucb:
        return "Insufficient evidence for the benchmark criterion"
    return "Meets"


# ---------------------------------------------------------------------------
# §10.3 composite sensitivity (R18)
# ---------------------------------------------------------------------------


def kendall_tau_stability(
    base_scores: Sequence[float],
    weight_grid: Sequence[Sequence[float]],
) -> Dict[str, float]:
    """Rank stability of a display-only composite under weight perturbation.

    DESIGN §10.3 (R18): tau < 0.8 means the ranking is weight-sensitive and
    must NOT be presented as an ordering.
    """
    base = np.asarray(base_scores, dtype=float)
    if base.ndim != 2 or base.shape[0] < 2 or not np.isfinite(base).all():
        raise ValueError("scores must be a finite SUT-by-dimension matrix")
    rb = np.mean(base, axis=1)
    taus = []
    for w in weight_grid:
        w = np.asarray(w, dtype=float)
        if w.shape != (base.shape[1],) or not np.isfinite(w).all() or np.any(w < 0) or w.sum() <= 0:
            raise ValueError("one nonnegative shared weight per dimension required")
        rs = base @ (w / w.sum())
        conc = disc = tied_base = tied_perturbed = 0
        for i in range(rs.size):
            for j in range(i + 1, rs.size):
                d = (rs[i] - rs[j]) * (rb[i] - rb[j])
                conc += 1 if d > 0 else 0
                disc += 1 if d < 0 else 0
                tied_base += int(rb[i] == rb[j] and rs[i] != rs[j])
                tied_perturbed += int(rs[i] == rs[j] and rb[i] != rb[j])
        denom = math.sqrt((conc + disc + tied_base) * (conc + disc + tied_perturbed))
        taus.append((conc - disc) / denom if denom else (1.0 if np.array_equal(rs, rb) else 0.0))
    if not taus:
        return {"tau_mean": 1.0, "tau_min": 1.0, "stable": True}
    tau_min = float(min(taus))
    return {"tau_mean": float(np.mean(taus)), "tau_min": tau_min,
            "stable": tau_min >= 0.8}


# ---------------------------------------------------------------------------
# §11.10 agreement (kappa is unstable at extreme prevalence)
# ---------------------------------------------------------------------------


def cohens_kappa(a: Sequence[Any], b: Sequence[Any]) -> float:
    a, b = list(a), list(b)
    n = len(a)
    if n == 0 or n != len(b):
        return 0.0
    cats = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return (po - pe) / (1.0 - pe) if pe < 1.0 else 0.0


def gwet_ac1(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Gwet's AC1 -- robust to the prevalence paradox that breaks kappa.

    Required alongside kappa whenever the category is rare (DESIGN §11.10:
    safety verdicts are almost always 'no violation').
    """
    a, b = list(a), list(b)
    n = len(a)
    if n == 0 or n != len(b):
        return 0.0
    cats = sorted(set(a) | set(b))
    k = len(cats) or 1
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for c in cats:
        p_c = ((a.count(c) + b.count(c)) / (2.0 * n))
        pe += p_c * (1.0 - p_c) / (k - 1) if k > 1 else 0.0
    return (po - pe) / (1.0 - pe) if pe < 1.0 else 0.0


# ---------------------------------------------------------------------------
# §11.7 IRT (exploratory, per track -- M7/N20)
# ---------------------------------------------------------------------------


def irt_rasch_joint(
    response_matrix: np.ndarray,
    *,
    max_iter: int = 200,
    tol: float = 1e-5,
) -> Dict[str, Any]:
    """Joint MLE Rasch calibration (per-track only, M7 unidimensionality).

    ``response_matrix`` is (n_subjects x n_items) with 0/1 and ``np.nan`` for
    missing (the planned-missing BIBD-like design of §12.6 is handled by
    simply skipping those cells).

    Reports item infit (MNSQ) so a badly fitting item can be flagged
    (DESIGN §11.7 wants infit in [0.5, 1.5]).  **Exploratory (N20)**: with
    SUT x run "subjects" this is a convenience sample and theta must not be
    extrapolated to people.
    """
    X = np.asarray(response_matrix, dtype=float)
    if X.ndim != 2 or min(X.shape, default=0) < 2:
        raise ValueError("Rasch requires a subject-by-item matrix with at least two rows and columns")
    observed = X[~np.isnan(X)]
    if not observed.size or not np.isin(observed, [0, 1]).all():
        raise ValueError("Rasch responses must be binary with NaN for missing observations")
    n_s, n_i = X.shape
    theta = np.zeros(n_s)
    beta = np.zeros(n_i)
    for _ in range(max_iter):
        max_change = 0.0
        for i in range(n_s):
            obs = ~np.isnan(X[i])
            if obs.sum() == 0:
                continue
            p = 1.0 / (1.0 + np.exp(-(theta[i] - beta[obs])))
            score = np.nansum(X[i][obs])
            denom = np.sum(p * (1.0 - p))
            if denom > 1e-9:
                delta = (score - p.sum()) / denom
                theta[i] += 0.5 * delta
                max_change = max(max_change, abs(0.5 * delta))
        for j in range(n_i):
            obs = ~np.isnan(X[:, j])
            if obs.sum() == 0:
                continue
            p = 1.0 / (1.0 + np.exp(-(theta[obs] - beta[j])))
            score = np.nansum(X[:, j][obs])
            denom = np.sum(p * (1.0 - p))
            if denom > 1e-9:
                delta = (score - p.sum()) / denom
                beta[j] -= 0.5 * delta
                max_change = max(max_change, abs(0.5 * delta))
        if max_change < tol:
            break
    # infit MNSQ
    infit = []
    for j in range(n_i):
        obs = ~np.isnan(X[:, j])
        if obs.sum() < 2:
            infit.append(float("nan"))
            continue
        p = 1.0 / (1.0 + np.exp(-(theta[obs] - beta[j])))
        w = p * (1.0 - p)
        resid = X[obs, j] - p
        infit.append(float(np.sum(resid ** 2) / np.sum(w)) if w.sum() > 0 else float("nan"))
    return {
        "theta": theta.tolist(), "beta": beta.tolist(), "infit_mnsq": infit,
        "n_subjects": n_s, "n_items": n_i,
        "fit_ok_share": float(np.mean([0.5 <= v <= 1.5 for v in infit if not math.isnan(v)])) if infit else 0.0,
        "interpretation": ("exploratory only (N20); subjects are SUT x run, "
                           "not people -- do not extrapolate theta to humans (M7)"),
    }
