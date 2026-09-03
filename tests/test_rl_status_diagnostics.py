from plans.rl_status import (
    RL_EXECUTIONS,
    RL_STOP_REASONS,
    finish_rl_status,
    new_rl_status,
    set_outcome,
    update_best,
)


def test_rl_status_has_stable_public_schema_and_json_safe_values():
    status = new_rl_status("0.90")

    expected = {
        "schema_version",
        "execution",
        "stop_reason",
        "target_coverage",
        "best_coverage",
        "best_reward",
        "episodes_completed",
        "high_level_episodes",
        "low_level_episodes",
        "actions_taken",
        "dense_trajectories_completed",
        "dense_seed_candidates",
        "elapsed_seconds",
        "dose_cache_hits",
        "dose_cache_misses",
    }
    assert expected <= set(status)
    assert status["target_coverage"] == 0.9
    assert status["execution"] in RL_EXECUTIONS
    assert status["stop_reason"] in RL_STOP_REASONS

    update_best(status, 0.394, 0.72)
    update_best(status, 0.25, 0.10)
    assert status["best_coverage"] == 0.394
    assert status["best_reward"] == 0.72


def test_rl_status_finalization_exposes_stop_reason_and_removes_internal_markers():
    status = new_rl_status(0.90)
    set_outcome(
        status,
        execution="interrupted",
        stop_reason="dose_inference_deadline",
    )
    status["_execution"] = "failed"
    status["_stop_reason"] = "dose_inference_deadline"
    status["episodes_completed"] = "2"
    status["actions_taken"] = "24"

    finished = finish_rl_status(status, 1e12)

    assert finished is status
    assert status["execution"] == "failed"
    assert status["stop_reason"] == "dose_inference_deadline"
    assert status["episodes_completed"] == 2
    assert status["actions_taken"] == 24
    assert status["elapsed_seconds"] == 0.0
    assert "_execution" not in status
    assert "_stop_reason" not in status
