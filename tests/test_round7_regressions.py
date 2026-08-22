from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _needle_geometry(needles):
    return [
        {
            "id": n["id"],
            "trajectory_id": n["trajectory_id"],
            "points": [list(p) for p in n["points"]],
        }
        for n in needles
    ]


def test_authoritative_previous_needles_recovers_baseline_after_restart():
    """The incremental replan diff must not collapse to a full run.

    After a server restart the browser's previous_needles cache is lost and it
    submits the current (already edited) geometry as the baseline, which made
    the diff empty and triggered a full-plan DoseUNet inference (~minutes)."""
    from web.server_support import _authoritative_previous_needles

    old_needle = {"id": "n1", "trajectory_id": "t1", "points": [[10.0, 10.0, 10.0], [10.0, 30.0, 10.0]]}
    new_needle = {"id": "n1", "trajectory_id": "t1", "points": [[12.0, 10.0, 10.0], [12.0, 30.0, 10.0]]}

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key):
            return self.values.get(key)

    # 1. Submitted baseline is stale (== current): fall back to stored manual needles.
    stored = [dict(old_needle)]
    agent = object.__new__(type("A", (), {}))
    agent.memory = Memory({"manual_needles": stored})
    result = _authoritative_previous_needles(agent, _needle_geometry([new_needle]), _needle_geometry([new_needle]))
    assert result == _needle_geometry(stored)
    assert result[0]["points"][0][0] == 10.0

    # 2. Submitted baseline differs: use it directly.
    agent = object.__new__(type("A", (), {}))
    agent.memory = Memory({})
    result = _authoritative_previous_needles(agent, _needle_geometry([old_needle]), _needle_geometry([new_needle]))
    assert result[0]["points"][0][0] == 10.0

    # 3. No stored baseline: fall back to the algorithm plan snapshot.
    agent = object.__new__(type("A", (), {}))
    agent.memory = Memory({
        "algorithm_plan_snapshot": {"needles": _needle_geometry([old_needle])},
    })
    result = _authoritative_previous_needles(agent, _needle_geometry([new_needle]), _needle_geometry([new_needle]))
    assert result[0]["points"][0][0] == 10.0

    # 4. Nothing available: return the submitted (empty diff) gracefully.
    agent = object.__new__(type("A", (), {}))
    agent.memory = Memory({})
    result = _authoritative_previous_needles(agent, _needle_geometry([new_needle]), _needle_geometry([new_needle]))
    assert result == _needle_geometry([new_needle])


def test_replan_reverses_current_ui_direction_and_reuses_masks():
    from AgenticSys import BrachyAgent
    from agent_runtime.execution_authorization import TurnExecutionAuthorization

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
    agent._active_turn_token = 1
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    agent._turn_execution_authorization.grant_tools(
        ["planning_pipeline", "surgical_guide"],
        source="legacy_fast_path_test",
    )
    agent._has_completed_planning = lambda *_args, **_kwargs: True
    agent._current_ct_path = lambda *_args, **_kwargs: "/tmp/case.nii.gz"

    calls = [{"tool": "planning_pipeline", "params": {"step": "full"}}]
    routed = agent._normalize_clinical_tool_calls(calls, "请把 reference direction 反向再规划一遍")

    assert [call["tool"] for call in routed] == ["planning_pipeline", "surgical_guide"]
    assert routed[0]["params"]["ref_direc"] == [-1.0, 0.0, 0.0]
    assert routed[1]["params"] == {"action": "generate"}
    assert agent._is_replan_request("请重新规划") is True
    assert agent._is_replan_request("介绍放射性粒子植入的好处") is False

    injected = agent._normalize_clinical_tool_calls(
        [{"tool": "completeness_checker", "params": {}}], "请重新规划"
    )
    assert injected[0]["tool"] == "planning_pipeline"


def test_ordered_action_plan_injects_planning_before_provider_guide_call():
    from AgenticSys import BrachyAgent
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.turn_policy import classify_local_turn

    class Memory:
        def retrieve(self, key, default=None):
            if key in {"ctv_array", "oar_array"}:
                return [1]
            if key == "oar_is_full":
                return True
            if key == "tumor_type_used":
                return "nnunet_pancreatic"
            return default

        def get_ui_state(self):
            return {"planning": {}}

    message = (
        "\u6211\u6539\u4e86\u7c92\u5b50\u690d\u5165\u53c2\u6570\uff0c"
        "\u8bf7\u91cd\u65b0\u6267\u884c\u89c4\u5212\uff0c\u5e76\u751f\u6210\u65b0\u7684\u5bfc\u677f"
    )
    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {}
    agent._active_turn_token = 1
    policy = classify_local_turn(message)
    agent._active_turn_policy = policy
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    agent._turn_execution_authorization.set_action_plan(policy.action_plan, source="test")
    agent._turn_execution_authorization.grant_policy(policy)
    agent._has_completed_planning = lambda *_args, **_kwargs: True
    agent._current_ct_path = lambda *_args, **_kwargs: "/tmp/case.nii.gz"

    routed = agent._normalize_clinical_tool_calls(
        [{"tool": "surgical_guide", "params": {"action": "generate"}}],
        message,
    )

    assert [call["tool"] for call in routed] == [
        "planning_pipeline",
        "surgical_guide",
    ]
    assert routed[0]["params"]["step"] == "full"
    assert routed[0]["params"]["ct_image_path"] == "/tmp/case.nii.gz"


def test_local_replan_action_plan_builds_queue_without_waiting_for_provider():
    from AgenticSys import BrachyAgent
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.turn_policy import classify_local_turn

    class Memory:
        def retrieve(self, key, default=None):
            if key in {"ctv_array", "oar_array"}:
                return [1]
            if key == "oar_is_full":
                return True
            if key == "tumor_type_used":
                return "nnunet_pancreatic"
            if key == "ct_path":
                return "/tmp/case.nii.gz"
            if key == "plan_config":
                return {}
            return default

        def get_ui_state(self):
            return {
                "ct_path": "/tmp/case.nii.gz",
                "planning": {
                    "in_lowest_energy": 120,
                    "out_highest_energy": 120,
                    "distance_filter": {"lower_bound": 1.0, "upper_bound": 9.0},
                },
            }

    message = (
        "\u6211\u6539\u4e86\u7c92\u5b50\u690d\u5165\u53c2\u6570\uff0c"
        "\u8bf7\u91cd\u65b0\u6267\u884c\u89c4\u5212\uff0c\u5e76\u751f\u6210\u65b0\u7684\u5bfc\u677f"
    )
    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {}
    agent._active_turn_token = 1
    policy = classify_local_turn(message)
    agent._active_turn_policy = policy
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    agent._turn_execution_authorization.set_action_plan(policy.action_plan, source="test")
    agent._turn_execution_authorization.grant_policy(policy)
    agent._has_completed_planning = lambda *_args, **_kwargs: True

    calls = agent._detect_tool_request(message)

    assert [call["tool"] for call in calls] == [
        "planning_pipeline",
        "surgical_guide",
    ]
    assert calls[0]["params"]["ct_image_path"] == "/tmp/case.nii.gz"
    assert calls[0]["params"]["planning_params"]["distance_filter"] == {
        "lower_bound": 1.0,
        "upper_bound": 9.0,
    }


def test_local_replan_plan_wins_if_provider_overwrites_turn_ledger_with_guide_only():
    """A later guide-only provider round must not erase the local replan queue."""
    from AgenticSys import BrachyAgent
    from agent_runtime.action_plan import ActionPlan
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.turn_policy import classify_local_turn

    class Memory:
        def retrieve(self, key, default=None):
            if key in {"ctv_array", "oar_array"}:
                return [1]
            if key == "oar_is_full":
                return True
            if key == "tumor_type_used":
                return "nnunet_pancreatic"
            if key == "ct_path":
                return "/tmp/case.nii.gz"
            if key == "plan_config":
                return {}
            return default

        def get_ui_state(self):
            return {"ct_path": "/tmp/case.nii.gz", "planning": {}}

    message = (
        "\u6211\u6539\u4e86\u7c92\u5b50\u690d\u5165\u53c2\u6570，"
        "\u8bf7\u91cd\u65b0\u6267\u884c\u89c4\u5212，\u5e76\u751f\u6210\u65b0\u7684\u5bfc\u677f"
    )
    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {}
    agent._active_turn_token = 1
    policy = classify_local_turn(message)
    agent._active_turn_policy = policy
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    # Simulate the failure observed in production: a later provider round
    # records only the terminal guide call in the mutable authorization ledger.
    agent._turn_execution_authorization.action_plan = ActionPlan.from_tools(
        ("surgical_guide",), source="provider_guide_only"
    )
    agent._has_completed_planning = lambda *_args, **_kwargs: True

    calls = agent._detect_tool_request(message)

    assert [call["tool"] for call in calls] == [
        "planning_pipeline",
        "surgical_guide",
    ]
    assert calls[0]["params"]["step"] == "full"


def test_short_replan_action_plan_builds_planning_queue_without_guide():
    from AgenticSys import BrachyAgent
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.turn_policy import classify_local_turn

    class Memory:
        def retrieve(self, key, default=None):
            if key in {"ctv_array", "oar_array"}:
                return [1]
            if key == "oar_is_full":
                return True
            if key == "tumor_type_used":
                return "nnunet_pancreatic"
            if key == "ct_path":
                return "/tmp/case.nii.gz"
            return default

        def get_ui_state(self):
            return {"ct_path": "/tmp/case.nii.gz", "planning": {}}

    message = "\u6211\u662f\u8ba9\u4f60\u91cd\u65b0\u89c4\u5212"
    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {}
    agent._active_turn_token = 1
    policy = classify_local_turn(message)
    agent._active_turn_policy = policy
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    agent._turn_execution_authorization.set_action_plan(policy.action_plan, source="test")
    agent._turn_execution_authorization.grant_policy(policy)
    agent._has_completed_planning = lambda *_args, **_kwargs: True

    calls = agent._detect_tool_request(message)

    assert [call["tool"] for call in calls] == ["planning_pipeline"]
    assert calls[0]["params"]["step"] == "full"


def test_guide_only_command_keeps_the_existing_low_latency_guide_route():
    from AgenticSys import BrachyAgent
    from agent_runtime.execution_authorization import TurnExecutionAuthorization
    from agent_runtime.turn_policy import classify_local_turn

    class Memory:
        def retrieve(self, key, default=None):
            if key == "ct_path":
                return "/tmp/case.nii.gz"
            return default

        def get_ui_state(self):
            return {"ct_path": "/tmp/case.nii.gz", "planning": {}}

    message = "请重新生成手术导板"
    agent = object.__new__(BrachyAgent)
    agent.memory = Memory()
    agent.config = {}
    agent._active_turn_token = 1
    policy = classify_local_turn(message)
    agent._active_turn_policy = policy
    agent._turn_execution_authorization = TurnExecutionAuthorization(token=1)
    agent._turn_execution_authorization.set_action_plan(policy.action_plan, source="test")
    agent._turn_execution_authorization.grant_policy(policy)

    calls = agent._detect_tool_request(message)

    assert [call["tool"] for call in calls] == ["surgical_guide"]


def test_chat_renders_only_reviewed_response_event():
    source = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    assert "let finalResponseReceived = false;" in source
    assert "if (!finalResponseReceived)" in source
    assert "finalResponseReceived = true;" in source
    assert "const finalText = finalResponseReceived" in source
    assert "readLoop: while (true)" in source
    assert "break readLoop;" in source


def test_reviewed_response_is_streamed_without_creating_duplicate_bubbles():
    """The post-review protocol must progressively fill one answer bubble."""
    workflows = (ROOT / "agent_runtime/chat_workflows.py").read_text(encoding="utf-8")
    ui = (ROOT / "web/app/static/js/brachybot-chat-todo.js").read_text(encoding="utf-8")
    core = (ROOT / "web/app/static/js/brachybot-chat-core.js").read_text(encoding="utf-8")

    assert '"final_text_chunk"' in workflows
    assert 'yield from final_response_events' in workflows
    assert "currentEvent === 'final_text_chunk'" in ui
    assert "finalTextStreamStarted = true" in ui
    assert "responseText = data.response" in ui
    assert "el.classList.remove('is-streaming')" in core


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


def test_dose_contours_are_session_scoped_retried_and_redrawn_at_zoom_resolution():
    """Contour slices must not disappear because of stale caches or raster-only zoom."""
    contour = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    annotation = (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    report_export = (ROOT / "web/app/static/js/brachybot-report-export.js").read_text(encoding="utf-8")
    routes = (ROOT / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    assert "function _doseContourCacheKey" in contour
    assert "_doseContourPlanningId()" in contour
    assert "const _doseContourInflight = new Map();" in contour
    assert "res.status !== 202" in contour
    assert "const _doseContourPreloadTimers = new Map();" in contour
    assert "preloadDoseContourSlices(axis, sliceIndex);" in contour
    assert "_syncLayerToSliceCanvas(axis, canvas, 7, { vector: true })" in contour
    assert "function _viewerVectorPixelRatio" in annotation
    assert "window.devicePixelRatio" in annotation
    assert "request2DViewerResolutionRefresh();" in annotation
    assert "const layerIds = [" in report_export
    assert "ctx.drawImage(layer, 0, 0, out.width, out.height)" in report_export
    assert "parent.querySelectorAll('canvas')" not in report_export
    assert "`contourCanvas${cap}`" in report_export
    assert "range_tolerance" in routes
    assert "for level_index, level_contour, level_gy, level_rel in valid_levels" in routes


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
    assert "async function loadLabelVolumes(options = {})" in viewer
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
    assert "await _persistNeedleGeometryOnly({" in manual
    assert "reason: 'needle_drag'" in manual


def test_needle_endpoint_interaction_uses_scene_render_scheduler_and_seed_clipped_geometry():
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    # These functions are outside init3DScene() and cannot see its local
    # requestRender closure. Calling that name directly caused every hover,
    # press, and release to throw ReferenceError in the browser.
    assert "requestRender?.(" not in layout
    assert "scene3D.requestRender(1)" in layout
    assert "scene3D.requestRender(2)" in layout
    # The 3D shaft must use the same deepest-seed-clipped points as its handles
    # and the canonical 2D overlay, rather than the raw algorithm extension.
    assert "const treeNeedle = dataTreeState.planning.needles.find" in manual
    assert "_needleDisplayPoints(treeNeedle)" in manual
    assert "_moveDeepestSeedWithInternalEndpoint" in manual


def test_needle_render_scheduler_survives_mixed_static_asset_revisions():
    """An open tab must not lose endpoint interaction during a deployment."""
    index = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
    layout = (ROOT / "web/app/static/js/brachybot-viewer-layout.js").read_text(encoding="utf-8")
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    # Keep this contract aligned with the actual cache-busting revisions in
    # index.html. A stale assertion here falsely reports a deployment bug and
    # hides whether the endpoint interaction bundle is really versioned.
    assert "brachybot-viewer-layout.js?v=30" in index
    assert "brachybot-3d-manual.js?v=62" in index
    assert "scene3D.requestRender(1)" in layout
    assert "scene3D.requestRender(2)" in layout
    assert "window.requestRender = requestRender;" in manual


def test_dose_overlay_opacity_is_invariant_during_slice_scrubbing():
    """Cached and asynchronous dose slices must share one layer opacity.

    Regression: opacity used to be baked into every slice's pixels. Rapidly
    scrubbing a slice slider could therefore display an opaque intermediate
    frame until the final, debounced repaint restored the Data Tree opacity.
    """
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    annotation = (ROOT / "web/app/static/js/brachybot-manual-annotation.js").read_text(encoding="utf-8")
    viewer = (ROOT / "web/app/static/js/brachybot-viewer-volume.js").read_text(encoding="utf-8")
    report_export = (ROOT / "web/app/static/js/brachybot-report-export.js").read_text(encoding="utf-8")
    report_editor = (ROOT / "web/app/static/js/brachybot-report-editor.js").read_text(encoding="utf-8")
    dvh_planning = (ROOT / "web/app/static/js/brachybot-dvh-planning.js").read_text(encoding="utf-8")
    ui_api = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    index = (ROOT / "web/app/index.html").read_text(encoding="utf-8")

    setter = manual.split("function setDoseOverlayOpacity(val)", 1)[1].split(
        "// ============ DOSE CONTOUR", 1
    )[0]
    renderer = manual.split("function renderDoseOverlayOnLayer", 1)[1].split(
        "function toggleDoseOverlayVisibility", 1
    )[0]
    geometry = annotation.split("function _applySliceLayerGeometry", 1)[1].split(
        "function _syncExistingSliceLayer", 1
    )[0]

    assert "function getDoseOverlayOpacity()" in manual
    assert "function applyDoseOverlayLayerOpacity(targetCanvas = null)" in manual
    opacity_getter = manual.split("function getDoseOverlayOpacity()", 1)[1].split(
        "function applyDoseOverlayLayerOpacity", 1
    )[0]
    assert opacity_getter.index("savedOpacity") < opacity_getter.index("runtimeOpacity")
    assert "applyDoseOverlayLayerOpacity(doseCanvas);" in renderer
    assert "imageData.data[idx + 3] = 255;" in renderer
    assert "Math.floor(opacity * 255)" not in renderer
    assert "dataTreeState.planning.doseOverlay.opacity = opacity;" in setter
    assert "_scheduleDataTreeSave('viewer.opacity:dose_overlay')" in setter
    assert "updateSlice(" not in setter
    assert "applyDoseOverlayLayerOpacity(layerCanvas);" in geometry
    assert "applyDoseOverlayLayerOpacity();" in (
        ROOT / "web/app/static/js/brachybot-viewer-volume.js"
    ).read_text(encoding="utf-8")
    update_slice = viewer.split("function updateSlice(view, val)", 1)[1].split(
        "let _viewerRefreshTimer", 1
    )[0]
    assert update_slice.index("applyDoseOverlayLayerOpacity(") < update_slice.index(
        "renderSliceFromVolume(view, sliceIndex)"
    )
    assert "function _composite2DViewerCanvas(axis, options = {})" in report_export
    assert "options.doseOpacity" in report_export
    assert "state.doseOverlay.opacity = 0.75" not in report_editor
    assert "state.doseOverlay.opacity = 0.75" not in dvh_planning
    assert "state.doseOverlay.opacity = 0.7" not in ui_api
    assert "_composite2DViewerCanvas(cfg.ax, { doseOpacity: 0.75 })" in report_editor
    assert "_composite2DViewerCanvas(cfg.ax, { doseOpacity: 0.75 })" in dvh_planning
    assert "_composite2DViewerCanvas(a.ax, { doseOpacity: 0.7 })" in ui_api
    assert "brachybot-viewer-volume.js?v=37" in index
    assert "brachybot-3d-manual.js?v=62" in index
    assert "brachybot-manual-annotation.js?v=14" in index


def test_manual_seed_defaults_to_needle_middle_and_is_proximity_selectable():
    """A manually added seed must land inside the needle (around its midpoint),
    never on an endpoint, and must win the 3D pick over a coincident endpoint
    handle so the user can slide it along the needle.

    Regression: seeds added at frac near 0.22 / 0.88 could sit on the needle
    endpoint, merge with the endpoint handle sphere, and become ungrabbable."""
    manual = (ROOT / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    add_block = manual.split("async function addManualSeed()", 1)[1].split("_upsertSceneMesh(seed.id", 1)[0]
    # The first seed must be placed around the midpoint, not at an endpoint.
    assert "0.5 - spread * Math.ceil(existing / 2)" in add_block
    assert "0.5 + spread * Math.ceil(existing / 2)" in add_block
    assert "Math.max(0.18, Math.min(0.82, frac))" in add_block
    assert "0.22" not in add_block
    # The 3D pick must prefer a seed near the pointer over an endpoint handle.
    assert "prefer that seed over any endpoint handle" in manual
    assert "perp < pickRadius" in manual
    assert "const nearestSeed = seedHits.length ? null : nearestSeedOnPointerRay();" in manual
    assert ": nearestSeed ? [{ object: nearestSeed }]" in manual



def test_dicom_rt_summary_omits_contour_coordinates():
    """Workspace restore returns provenance/counts, not a huge contour payload."""
    from web.server import _dicom_rt_import_summary

    summary = _dicom_rt_import_summary({
        "modality": "RTSTRUCT",
        "path": "/private/workspace/imports/case_rtstruct.dcm",
        "patient_id": "case-123",
        "frame_of_reference_uid": "1.2.3",
        "structures": [{
            "name": "CTV",
            "roi_number": "7",
            "contours": [
                {"number_of_points": 120000, "points_lps_mm": [[1, 2, 3]]},
                {"number_of_points": 8, "points_lps_mm": [[4, 5, 6]]},
            ],
        }],
    })

    assert summary["filename"] == "case_rtstruct.dcm"
    assert summary["structure_count"] == 1
    assert summary["structures"][0]["contour_count"] == 2
    assert summary["structures"][0]["point_count"] == 120008
    assert "points_lps_mm" not in str(summary)


def test_case_import_audit_and_review_controls_share_manual_ui_paths():
    index = (ROOT / "web/app/index.html").read_text(encoding="utf-8")
    ui = (ROOT / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    report = (ROOT / "web/app/static/js/brachybot-report-shell.js").read_text(encoding="utf-8")
    registry = (ROOT / "tool_factory/ui_controller/__init__.py").read_text(encoding="utf-8")

    assert 'id="fileDicomRT"' in index
    assert "handleDicomRTImport(this)" in index
    assert "Report.review.openModal()" in index
    assert "fetch(API + '/import/dicom_rt'" in ui
    assert "const ownerSessionId = String(options.sessionId || _activeApiSessionId())" in ui
    assert "const isCurrentOwner = () => ownerSessionId === String(_activeApiSessionId())" in ui
    assert "'input.dicom_rt.browse': 'fileDicomRT'" in ui
    assert "target === 'report.review.open'" in ui
    assert "'/api/workspace/audit?limit=200'" in report
    assert "'/api/workspace/review/comments'" in report
    assert "audit, review, snapshots" in report
    for target in (
        '"input.ct.browse"', '"input.ctv.browse"',
        '"input.oar.browse"', '"input.dicom_rt.browse"',
        '"report.review.open"',
    ):
        assert target in registry
