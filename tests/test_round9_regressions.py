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
        css = self.read("web/app/static/css/brachybot-chat-status.css")
        self.assertIn("animation-play-state: running !important", css)

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

    def test_screenshot_dose_requests_use_report_overview(self):
        tool = self.read("tool_factory/ui_screenshot/__init__.py")
        chat = self.read("web/app/static/js/brachybot-chat-todo.js")
        self.assertIn("use target `dose-overview`", tool)
        self.assertIn("three 2D planes and the DVH", tool)
        self.assertIn("_normalizeScreenshotRequestTarget", chat)
        self.assertIn("return genericDose ? 'dose-overview' : rawTarget", chat)

    def test_visual_screenshot_followup_is_multimodal_and_reviewed(self):
        chat = self.read("web/app/static/js/brachybot-chat-todo.js")
        workflow = self.read("agent_runtime/chat_workflows.py")
        runtime = self.read("agent_runtime/llm_runtime.py")
        self.assertIn("[Screenshot captured: ${url}]", chat)
        self.assertIn("_isVisualAnalysisRequest", chat)
        self.assertIn("visual_screenshot_analysis", workflow)
        self.assertIn("_screenshot_called_this_turn = set()", runtime)
        self.assertIn("all(tc.get(\"tool\") == \"ui_screenshot\"", runtime)

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


if __name__ == "__main__":
    unittest.main()
