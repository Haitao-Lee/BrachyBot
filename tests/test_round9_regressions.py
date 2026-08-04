"""Regression checks for the viewer/report/review fixes in round 9."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Round9RegressionTests(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_needle_endpoint_capture_stops_orbit_controls(self):
        source = self.read("web/app/static/js/brachybot-3d-manual.js")
        self.assertIn("event.stopImmediatePropagation()", source)
        self.assertIn("type === 'needle_handle'", source)

    def test_dvh_uses_rendered_plot_geometry(self):
        source = self.read("web/app/static/js/brachybot-dvh-planning.js")
        self.assertIn("querySelector('.nsewdrag')", source)
        self.assertIn("plotBox.left - box.left", source)
        self.assertIn("Number(yRange[1]) - p.y", source)

    def test_report_capture_has_unconditional_state_restore(self):
        source = self.read("web/app/static/js/brachybot-report-editor.js")
        self.assertIn("finally {", source)
        self.assertIn("_restoreFigure1State?.()", source)
        self.assertIn("restoreDoseSurfaceState?.()", source)

    def test_todo_keeps_parallel_active_steps(self):
        source = self.read("web/app/static/js/brachybot-chat-todo.js")
        self.assertIn("Keep every unfinished step active", source)
        self.assertNotIn("it.status = 'pending';  // will be moved to done", source)
        self.assertIn("step.requires_input ? 'User input required'", source)
        self.assertIn("cancel(reason)", source)
        self.assertIn("window._chatTurnCancelUi", source)
        self.assertIn("const isBusy = !!window._chatTurnActive", source)
        self.assertIn("queueIfBusy", source)
        self.assertIn("window.cancelVisibleChatProgress", source)
        css = self.read("web/app/static/css/brachybot-chat-status.css")
        self.assertIn("animation-play-state: running !important", css)
        responsive = self.read("web/app/static/css/brachybot-responsive.css")
        self.assertIn(".chat-todo-item.active .chat-todo-gpu", responsive)
        # Reduced-motion mode still gets a deliberately small continuous
        # status pulse; a static row made long-running work look stalled.
        self.assertIn("animation-iteration-count: infinite !important", responsive)
        self.assertIn("todo-active-breathe-soft", responsive)

    def test_planning_dose_model_uses_centralized_device_selection(self):
        source = self.read("tool_factory/seed_plan/planning_pipeline.py")
        self.assertIn('get_device(caller="planning_pipeline_dose")', source)
        self.assertNotIn('load_dose_model(device="cpu")', source)

    def test_stage_two_planning_cannot_spin_forever(self):
        source = self.read("plans/core.py")
        self.assertIn("max_stage2_iterations = 100", source)
        self.assertIn("stage2_iterations > max_stage2_iterations", source)
        self.assertIn("no measurable DVH", source)

    def test_missing_tumor_site_short_circuits_llm_tool_loop(self):
        source = self.read("agent_runtime/llm_runtime.py")
        self.assertIn("_input_missing = True", source)
        self.assertIn("clarification_required", source)
        self.assertIn('"requires_input"] = True', source)

    def test_execution_trace_counter_deduplicates_sse_events(self):
        source = self.read("web/app/static/js/brachybot-chat-core.js")
        self.assertIn("const unique = new Map();", source)
        self.assertIn("logicalSteps.filter(s => s.status === 'done')", source)
        self.assertNotIn("steps.filter(s => s.status === 'done').length;", source)

    def test_colorbar_panel_has_explicit_dismissal(self):
        html = self.read("web/app/index.html")
        js = self.read("web/app/static/js/brachybot-3d-manual.js")
        self.assertIn("closeDoseColorbarPanel", html)
        self.assertIn("Escape", js)
        self.assertIn("panel.contains(event.target)", js)

    def test_chinese_quality_review_is_localized(self):
        source = self.read("agents/plan_reviewer.py")
        orchestrator = self.read("agents/orchestrator.py")
        self.assertIn("self._merge_results(det_results, llm_results, plan_info, self._lang)", source)
        self.assertIn("\\u8d28\\u91cf\\u5ba1\\u67e5", source)
        self.assertIn('"title": "\\u8d28\\u91cf\\u5ba1\\u67e5"', orchestrator)

    def test_chat_dose_screenshots_do_not_reuse_report_compositor(self):
        tool = self.read("tool_factory/ui_screenshot/__init__.py")
        ui_api = self.read("web/app/static/js/brachybot-ui-api.js")
        self.assertIn("do not reuse the fixed Report Figure compositor", tool)
        self.assertIn('"viewer-axial"', tool)
        self.assertIn('"viewer-sagittal"', tool)
        self.assertIn('"viewer-coronal"', tool)
        self.assertIn("if (normalizedTarget === 'dose-overview' && mode !== 'report')", ui_api)
        self.assertIn("_captureDoseOverviewDataUrl", ui_api)

    def test_visual_screenshot_followup_is_multimodal_and_reviewed(self):
        chat = self.read("web/app/static/js/brachybot-chat-todo.js")
        workflow = self.read("agent_runtime/chat_workflows.py")
        runtime = self.read("agent_runtime/llm_runtime.py")
        self.assertIn("[Screenshot captured: ${url}]", chat)
        self.assertIn("_isVisualAnalysisRequest", chat)
        self.assertIn("visual_screenshot_analysis", workflow)
        self.assertIn("_screenshot_called_this_turn = set()", runtime)
        self.assertIn("all(tc.get(\"tool\") == \"ui_screenshot\"", runtime)

    def test_invalid_screenshot_calls_are_filtered_before_tool_execution(self):
        from agent_runtime.response_tools import ResponseToolMixin

        calls = ResponseToolMixin()._normalize_tool_params([
            {"tool": "ui_screenshot", "params": {}},
            {"tool": "ui_screenshot", "params": {"target": "dvh", "question": "Describe the curve"}},
        ])
        assert len(calls) == 1
        assert calls[0]["params"]["target"] == "dvh"

    def test_web_fetch_failure_keeps_reason_and_does_not_hide_successful_search(self):
        from agent_runtime.llm_runtime import (
            _collect_tool_fallback_text,
            _is_placeholder_tool_response,
        )
        from tool_factory.web_fetch import WebFetchTool

        failed = WebFetchTool()._execute(url="")
        assert failed.success is False
        assert failed.error == "No URL provided"
        assert failed.message == failed.error
        steps = [
            {
                "type": "tool",
                "tool": "web_fetch",
                "status": "error",
                "result": "Error: Request failed: blocked",
            },
            {
                "type": "tool",
                "tool": "web_search",
                "status": "done",
                "result": "Search results: DeepRare\nSource: https://example.org",
            },
        ]
        successes, failures = _collect_tool_fallback_text(
            steps,
            [{"role": "tool", "content": "Search results: DeepRare\nSource: https://example.org"}],
        )
        assert successes
        assert failures
        assert _is_placeholder_tool_response("Tools executed. Check the execution trace above for results.")

    def test_web_fetch_explains_anti_bot_block_instead_of_bare_status(self):
        from unittest import mock
        from tool_factory.web_fetch import WebFetchTool

        tool = WebFetchTool()

        class BlockedResp:
            status_code = 403
            headers = {}

            def close(self):
                pass

            def iter_content(self, chunk_size):
                return []

        with mock.patch("tool_factory.web_fetch.requests.get", return_value=BlockedResp()):
            r = tool._execute(url="https://zhuanlan.zhihu.com/p/123")
            assert r.success is False
            assert "blocked automated access" in r.error
            assert "anti-bot" in r.error

        class ServerResp:
            status_code = 502
            headers = {}

            def close(self):
                pass

            def iter_content(self, chunk_size):
                return []

        with mock.patch("tool_factory.web_fetch.requests.get", return_value=ServerResp()):
            r = tool._execute(url="https://example.com/")
            assert r.success is False
            assert "server error" in r.error

    def test_oar_count_uses_current_case_state_not_external_tools(self):
        from agent_runtime.chat_workflows import ChatWorkflowMixin

        class Memory:
            user_lang = "en"

            def retrieve(self, key, default=None):
                return {"organ_names": {1: "stomach", 2: "duodenum"}}.get(key, default)

        class Workflow(ChatWorkflowMixin):
            memory = Memory()

        workflow = Workflow()
        assert workflow._is_current_oar_count_request("How many OARs are loaded?")
        assert not workflow._is_current_oar_count_request("What are the pancreatic OAR constraints?")
        assert "2 loaded OAR structures" in workflow._build_current_oar_count_response("en")

    def test_segmentation_refresh_is_bound_to_the_origin_case(self):
        chat = self.read("web/app/static/js/brachybot-chat-todo.js")
        assert "loadLabelVolumes({" in chat
        assert "sessionId: turnSessionId" in chat
        assert "preserveViewerState: true" in chat

    def test_completed_task_does_not_start_a_second_full_restore(self):
        workspace = self.read("web/app/static/js/brachybot-workspace.js")
        block = workspace.split("async function refreshSessionAfterTaskCompletion", 1)[1].split("async function recoverWorkspaceAfterTransitionFailure", 1)[0]
        assert "scheduleBackgroundWorkspaceRestore(workspace, ownerSessionId)" not in block
        assert "Full hydration remains reserved" in block

    def test_3d_telemetry_and_recovery_are_present(self):
        ui_api = self.read("web/app/static/js/brachybot-ui-api.js")
        core = self.read("agent_runtime/core.py")
        viewer = self.read("web/app/static/js/brachybot-viewer-layout.js")
        manual = self.read("web/app/static/js/brachybot-3d-manual.js")
        self.assertIn("visible_mesh_count", ui_api)
        self.assertIn("context_lost", ui_api)
        self.assertIn("3D Viewer:", core)
        self.assertIn("webglcontextlost", manual)
        self.assertIn("_repair3DSceneVisibility", manual)
        self.assertIn("contextLost: false", viewer)

    def test_3d_status_has_deterministic_fallback(self):
        workflow = self.read("agent_runtime/chat_workflows.py")
        self.assertIn("_is_3d_status_request", workflow)
        self.assertIn("_build_3d_status_response", workflow)
        self.assertIn("scene has no mounted 3D meshes", workflow)

    def test_viewer_refreshes_do_not_implicitly_fit_camera(self):
        manual = self.read("web/app/static/js/brachybot-3d-manual.js")
        viewer = self.read("web/app/static/js/brachybot-viewer-layout.js")
        force_start = manual.index("function forceRender3DViewer")
        force_end = manual.index("function update3DMeshOpacity", force_start)
        force_block = manual[force_start:force_end]
        self.assertNotIn("fitCameraToScene();", force_block)
        self.assertIn("Camera pose", manual)
        self.assertIn("Dose-surface toggles must not reset the user's camera", viewer)

    def test_explicit_fit_reset_controls_remain_available(self):
        ui_api = self.read("web/app/static/js/brachybot-ui-api.js")
        self.assertIn("target === '3d.fit'", ui_api)
        self.assertIn("target === '3d.reset'", ui_api)

    def test_needle_drag_uses_renderer_capture_and_live_shaft_preview(self):
        manual = self.read("web/app/static/js/brachybot-3d-manual.js")
        self.assertIn("const interactionCanvas = scene3D.renderer?.domElement || canvas", manual)
        self.assertIn("interactionCanvas.addEventListener('pointerdown', beginNeedleHandleDrag, true)", manual)
        self.assertIn("interactionCanvas.setPointerCapture", manual)
        self.assertIn("window.addEventListener('pointermove', updateManualDrag)", manual)
        self.assertIn("window.addEventListener('pointercancel', finishManualDrag)", manual)
        self.assertIn("const scheduleManualOverlayRedraw", manual)
        self.assertIn("window.addEventListener('blur', finishManualDrag)", manual)
        self.assertIn("const preview = _makeNeedleMesh(needle)", manual)
        self.assertIn("onManualNeedleHandleEdited(finishedObject)", manual)

    def test_report_recaptures_restore_the_user_camera(self):
        report = self.read("web/app/static/js/brachybot-report-editor.js")
        planning = self.read("web/app/static/js/brachybot-dvh-planning.js")
        self.assertIn("const savedCamera = scene3D.camera && scene3D.controls", report)
        # A report capture can finish after a case transition. Restore the
        # originally captured camera object only when it is still the active
        # scene camera; restoring through scene3D.camera would repaint a new
        # session with an old report capture.
        self.assertIn("scene3D.camera === savedCamera.camera", report)
        self.assertIn("savedCamera.camera.quaternion.copy(savedCamera.quaternion)", report)
        self.assertIn("const _restoreCamera = () =>", planning)
        self.assertIn("_restoreCamera();\n            forceRender3DViewer();", planning)


if __name__ == "__main__":
    unittest.main()
