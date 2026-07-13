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


if __name__ == "__main__":
    unittest.main()
