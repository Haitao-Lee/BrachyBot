"""Plan-owned read-only outputs of the five manual steps (not chat previews)."""
from uuid import uuid4

STEPS = ("trajectory_init", "trajectory_refine", "seed_planning", "dose_calc", "dose_eval")
MEMORY_KEY = "manual_step_outputs"


def record_manual_step_output(agent, step, result, planning_id):
    """Called before the pipeline's existing atomic planning snapshot commit.

    Only the two candidate stages need additional world-space geometry. Later
    stages reference the canonical plan, dose and DVH instead of duplicating
    clinical arrays. Re-running an upstream step retires downstream outputs.
    """
    if step not in STEPS:
        return
    memory = agent.memory
    previous = memory.retrieve(MEMORY_KEY) or {}
    stages = previous.get("stages", []) if previous.get("planning_id") == planning_id else []
    stages = [entry for entry in stages if entry.get("step") in STEPS[:STEPS.index(step)]]
    output = {"step": step, "revision": uuid4().hex, "read_only": True}
    if step in STEPS[:2]:
        from tool_factory.seed_plan.planning_pipeline import _preview_trajectory_geometry
        paths = result.data if result.data is not None else []
        close_points = (result.metadata or {}).get("manual_close_points", [])
        geometry = _preview_trajectory_geometry(
            paths, memory.retrieve("resampled_ct"),
            status="safe" if step == STEPS[0] else "refined",
            close_points=close_points if step == STEPS[0] else None,
            trajectory_limit=max(1, len(paths)),
            close_point_limit=max(1, len(close_points)),
        )
        output.update(geometry=geometry, trajectory_count=len(paths),
                      shown_trajectories=len(geometry["trajectories"]),
                      close_point_count=len(geometry["close_points"]))
    output["seed_count"] = int(memory.retrieve("total_seeds") or 0)
    output["has_dose"] = any(memory.retrieve(key) is not None for key in
                             ("dose_distribution", "dose_distribution_gy"))
    output["has_dvh"] = bool(memory.retrieve("dvh_data"))
    catalog = {"planning_id": planning_id, "active_step": step, "stages": stages + [output]}
    # The immediately following publish commits this along with the clinical
    # result; do not schedule a separate half-published checkpoint here.
    from web.planning_runs import _memory_put
    _memory_put(memory, MEMORY_KEY, catalog)
    if isinstance(result.metadata, dict):
        result.metadata.pop("manual_close_points", None)
    return catalog
