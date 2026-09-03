"""Structured execution telemetry for bounded reinforcement-learning planning.

The RL planner is deliberately bounded because it runs inside an interactive
clinical workflow.  A single ``best_reward`` value is not enough to explain a
run that did not reach its target: the run may have been interrupted by the
wall-clock or DoseUNet deadline, exhausted its episode/action budget, or
failed before a dense candidate existed.  This module keeps the diagnostic
contract small, JSON-safe, and independent from NumPy/PyTorch so it can be
persisted with a planning snapshot and rendered after a server restart.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional


RL_EXECUTIONS = frozenset({"completed", "interrupted", "failed"})
RL_STOP_REASONS = frozenset(
    {
        "target_reached",
        "wall_clock_budget",
        "dose_inference_deadline",
        "episode_budget_exhausted",
        "no_valid_dense_trajectory",
        "no_available_action",
        "internal_exception",
        "completed_without_target",
    }
)


def new_rl_status(target_coverage: Any) -> Dict[str, Any]:
    """Create the stable, JSON-safe status object for one RL invocation."""
    try:
        target = float(target_coverage)
    except (TypeError, ValueError):
        target = 0.0
    if not math.isfinite(target):
        target = 0.0
    return {
        "schema_version": 1,
        "execution": "completed",
        "stop_reason": "completed_without_target",
        "target_coverage": target,
        "best_coverage": 0.0,
        "best_reward": None,
        "episodes_completed": 0,
        "high_level_episodes": 0,
        "low_level_episodes": 0,
        "actions_taken": 0,
        "dense_trajectories_completed": 0,
        "dense_seed_candidates": 0,
        "elapsed_seconds": 0.0,
        "dose_cache_hits": 0,
        "dose_cache_misses": 0,
    }


def update_best(status: Optional[Dict[str, Any]], coverage: Any, reward: Any) -> None:
    """Update best coverage/reward without allowing NaN into persistence."""
    if not isinstance(status, dict):
        return
    try:
        cov = float(coverage)
    except (TypeError, ValueError):
        cov = None
    if cov is not None and math.isfinite(cov):
        status["best_coverage"] = max(float(status.get("best_coverage") or 0.0), cov)
    try:
        value = float(reward)
    except (TypeError, ValueError):
        value = None
    if value is not None and math.isfinite(value):
        previous = status.get("best_reward")
        if previous is None:
            status["best_reward"] = value
        else:
            try:
                status["best_reward"] = max(float(previous), value)
            except (TypeError, ValueError):
                status["best_reward"] = value


def set_outcome(
    status: Optional[Dict[str, Any]],
    *,
    execution: Optional[str] = None,
    stop_reason: Optional[str] = None,
) -> None:
    """Set a provisional outcome while nested RL stages are still running."""
    if not isinstance(status, dict):
        return
    if execution in RL_EXECUTIONS:
        status["_execution"] = execution
    if stop_reason in RL_STOP_REASONS:
        status["_stop_reason"] = stop_reason


def finish_rl_status(
    status: Optional[Dict[str, Any]],
    started_at: float,
    *,
    execution: Optional[str] = None,
    stop_reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Finalize status and validate the public execution vocabulary."""
    if not isinstance(status, dict):
        return None
    execution = execution or status.pop("_execution", None) or status.get("execution")
    stop_reason = stop_reason or status.pop("_stop_reason", None) or status.get("stop_reason")
    status["execution"] = execution if execution in RL_EXECUTIONS else "failed"
    status["stop_reason"] = (
        stop_reason if stop_reason in RL_STOP_REASONS else "internal_exception"
    )
    try:
        elapsed = time.monotonic() - float(started_at)
    except (TypeError, ValueError):
        elapsed = 0.0
    status["elapsed_seconds"] = round(max(0.0, elapsed), 3)
    # Ensure counters are ordinary integers even when an implementation path
    # received a NumPy scalar or a mock value.
    for key in (
        "episodes_completed",
        "high_level_episodes",
        "low_level_episodes",
        "actions_taken",
        "dense_trajectories_completed",
        "dense_seed_candidates",
        "dose_cache_hits",
        "dose_cache_misses",
    ):
        try:
            status[key] = max(0, int(status.get(key) or 0))
        except (TypeError, ValueError):
            status[key] = 0
    return status
