"""Regression contracts for report capture and truthful response progress."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_figure_one_detail_view_keeps_the_complete_ctv_in_frame():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "const padding = mode === 'detail' ? 1.05 : 1.08;" in source
    assert "complete CTV and its peripheral seeds" in source


def test_figure_two_rejects_black_webgl_capture_and_retries():
    source = _read("web/app/static/js/brachybot-report-editor.js")

    assert "async function captureDoseSurface3D(label)" in source
    assert "3D dose-surface capture is black" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('primary');" in source
    assert "doseSurfaceDataUrl = await captureDoseSurface3D('retry');" in source
    assert "_isDoseTexturableMesh(id, mesh)" in source


def test_response_trace_exposes_synthesis_and_final_delivery_phases():
    source = _read("agent_runtime/chat_workflows.py")

    assert '"Response Synthesis"' in source
    assert '"Final Response"' in source
    assert 'yield yield_event("step", _synthesis_step)' in source
    assert 'yield yield_event("response", payload)' in source
    assert 'final_step["status"] = "done"' in source


def test_single_needle_replan_uses_changed_trajectory_incremental_dose_path():
    source = _read("web/server_support.py")
    assert "changed_trajectories = set()" in source
    assert "trajectory_id not in changed_trajectories" in source
    assert "incremental needle replan" in source
    assert 'baseline_dose_key = "dose_distribution" if agent.memory.retrieve("manual_ai_dose") else "algorithm_plan_dose_distribution"' in source


def test_manual_needle_refresh_does_not_rebuild_the_whole_planning_scene():
    source = _read("web/app/static/js/brachybot-3d-manual.js")
    refresh_body = source.split("async function _refreshManualDoseViews", 1)[1].split("function _manualUiPosition", 1)[0]
    assert "loadDoseOverlay" in refresh_body
    assert "loadAllSlices" in refresh_body
    assert "refreshPlanningUI" not in refresh_body
    assert "data?.needles" in refresh_body


def test_manual_replan_has_stable_id_change_detection_and_deadline_guard():
    source = _read("web/server_support.py")
    assert "stable needle id first" in source
    assert "BRACHYBOT_MANUAL_REPLAN_TIMEOUT_S" in source
    assert "seed_plan[trajectory][2]" in source
    assert "deadline=interactive_deadline" in source
    # The trajectory-only fallback is valid only when no stable ids matched;
    # an unconditional second occurrence would reintroduce full-plan reruns
    # after a workspace restore.
    assert source.count("changed.update(set(old_by_trajectory).symmetric_difference(new_by_trajectory))") == 1
