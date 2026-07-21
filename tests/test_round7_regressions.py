from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_replan_reverses_current_ui_direction_and_reuses_masks():
    from AgenticSys import BrachyAgent

    class Memory:
        def __init__(self):
            self.ui = {"planning": {"reference_direc": [1, 0, 0]}}

        def retrieve(self, key, default=None):
            if key == "ctv_array":
                return [1]
            if key == "oar_array":
                return [1]
            if key == "oar_is_full":
                return True
            return default

        def get_ui_state(self):
            return self.ui

    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {"reference_direc": [0, -1, 0]}
    agent._has_completed_planning = lambda *_args, **_kwargs: True
    agent._current_ct_path = lambda *_args, **_kwargs: "/tmp/case.nii.gz"

    calls = [{"tool": "planning_pipeline", "params": {"step": "full"}}]
    routed = agent._normalize_clinical_tool_calls(calls, "请把 reference direction 反向再规划一遍")

    assert [call["tool"] for call in routed] == ["planning_pipeline"]
    assert routed[0]["params"]["ref_direc"] == [-1.0, 0.0, 0.0]
    assert agent._is_replan_request("请重新规划") is True
    assert agent._is_replan_request("介绍放射性粒子植入的好处") is False

    injected = agent._normalize_clinical_tool_calls(
        [{"tool": "completeness_checker", "params": {}}], "请重新规划"
    )
    assert injected[0]["tool"] == "planning_pipeline"


def test_chat_renders_only_reviewed_response_event():
    source = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    assert "let finalResponseReceived = false;" in source
    assert "if (!finalResponseReceived)" in source
    assert "finalResponseReceived = true;" in source
    assert "const finalText = finalResponseReceived" in source
    assert "readLoop: while (true)" in source
    assert "break readLoop;" in source


def test_review_feedback_stays_internal_and_needle_overlay_is_entry_clipped():
    workflows = (ROOT / "agent_runtime/chat_workflows.py").read_text(encoding="utf-8")
    overlay = (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    assert "review_feedback = []" in workflows
    assert 'self.memory.store("last_review_feedback", review_feedback)' in workflows
    assert "response += \"\\n\\n---\\n\"" not in workflows
    assert "function _needleSliceSegment" in overlay
    assert "seedsByTrajectory" in overlay
    assert "const segmentStart = segment.start" in overlay
    assert "const segmentEnd = segment.end" in overlay
    assert "ctx.arc(hit.x" not in overlay


def test_dose_contour_redraw_keeps_level_in_scope_and_uses_data_tree_color():
    """Changing an ISO color must not fail before the 2D contour is redrawn."""
    source = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    draw_block = source.split("function renderDoseContourOnCanvas", 1)[1].split(
        "// Trigger contour rendering", 1
    )[0]
    assert "visibleContours.forEach(contour =>" in draw_block
    assert "const level = contour.level ?? contour.level_rel;" in draw_block
    assert "Number(d.thresholdGy) - Number(level)" in draw_block
    assert "const numericLevel = Number(level);" in draw_block


def test_search_fact_check_is_visible_as_a_pending_trace_phase():
    """Search completion must not hide synchronous source verification work."""
    runtime = (ROOT / "agent_runtime/llm_runtime.py").read_text(encoding="utf-8")
    workflows = (ROOT / "agent_runtime/chat_workflows.py").read_text(encoding="utf-8")
    ui = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")

    # Both streaming and direct-tool paths must expose the same internal
    # phase; otherwise a search step can show N/N while its fact-check LLM is
    # still running.
    assert runtime.count('"tool": "fact_checker"') >= 1
    assert workflows.count('tool="fact_checker"') >= 1
    assert 'step.tool === \'fact_checker\'' in ui


def test_reference_direction_mode_is_explicit_and_auto_wins_stale_vectors():
    core = (ROOT / "agent_runtime/core.py").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    routes = (ROOT / "web/routes/planning_routes.py").read_text(encoding="utf-8")
    assert "def resolve_reference_direction_input" in core
    assert "ref_direc_auto: refAuto" in (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    assert "reference_direc_mode" in ui_api
    assert "resolve_reference_direction_input(" in routes


def test_planning_pipeline_reads_live_ui_direction_before_provider_vector():
    from tool_factory.seed_plan.planning_pipeline import _ui_reference_direction_input

    class Memory:
        def __init__(self, state):
            self.state = state

        def get_ui_state(self):
            return self.state

    class Agent:
        def __init__(self, state):
            self.memory = Memory(state)

    assert _ui_reference_direction_input(Agent({
        "planning": {
            "ref_direc_auto": True,
            "reference_direc": [0, -1, 0],
            "reference_direc_mode": "auto",
        }
    })) == "auto"
    assert _ui_reference_direction_input(Agent({
        "planning": {
            "ref_direc_auto": False,
            "reference_direc": [0, -1, 0],
            "reference_direc_mode": "manual",
        }
    })) == [0.0, -1.0, 0.0]
    assert _ui_reference_direction_input(Agent({})) is None


def test_reference_direction_schema_accepts_auto_and_numeric_vectors():
    source = (ROOT / "tool_factory/seed_plan/planning_pipeline.py").read_text(encoding="utf-8")
    assert '"oneOf": [' in source
    assert '"enum": ["auto", "auto_detect"]' in source
    assert "_reference_direction_user_override" in source
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    assert "referenceDirectionSyncBound" in ui_api


def test_viewer_and_data_tree_regressions_are_explicitly_covered():
    index = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    viewer = (ROOT / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    manual_3d = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    dvh = (ROOT / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")

    assert '<html lang="en" data-theme="dark">' in index
    assert "reference_direc:" in ui_api
    assert "state.viewerSettings.threshold = null" in viewer
    assert "const raw = document.getElementById('viewerThreshold')?.value?.trim() || ''" in viewer
    assert "category === 'planning'" in viewer
    assert "category === 'planning_trajectories'" in viewer
    assert "async function loadLabelVolumes()" in viewer
    assert "opts.allOAR" in manual_3d
    assert "const doseFraction" not in dvh
    assert "const cursorDose =" in dvh
    assert "_interpolateDvhAtDose(best.traceX, best.traceY, displayDose)" in dvh


def test_needle_drag_requires_explicit_replan_confirmation():
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")

    # A drag must not call the expensive dose endpoint until the user chooses
    # Replan. Repeated edits share one prompt and the latest geometry wins.
    assert "_confirmNeedleReplan" in manual
    assert "manualPlanningState.needleReplanPrompt" in manual
    assert "Needle ${needleId} position kept. Replanning skipped." in manual
    assert "await recomputeManualDose('needle_drag'" in manual
    assert "lastDoseNeedles = _cloneNeedleGeometry" in manual
    assert "function _confirmAction(msgZh, msgEn, options = {})" in ui_api
    assert "options.yesEn" in ui_api and "options.noEn" in ui_api
    # Manual mesh updates must use the active plan's physical seed geometry.
    assert "state?.seedsOverlay?.geometry" in layout


def test_position_only_needle_edit_has_a_safe_persistence_endpoint():
    routes = (ROOT / "web/routes/planning_routes.py").read_text(encoding="utf-8")
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    assert '@app.route("/api/manual_planning/update_geometry", methods=["POST"])' in routes
    assert "_validate_manual_needle_safety" in routes
    assert 'memory.store("manual_needles", normalized_needles)' in routes
    assert 'memory.store("manual_seeds", current_seeds)' in routes
    assert '"dose_recomputed": False' in routes
    assert "_persistNeedleGeometryOnly" in manual
    assert "manual_planning/update_geometry" in manual
    assert "await _persistNeedleGeometryOnly()" in manual
