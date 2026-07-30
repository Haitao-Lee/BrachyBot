from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def test_volume_metric_unit_declaration_is_honored_and_legacy_values_remain_compatible():
    from web.server_support import _metric_as_fraction, _volume_metric_as_fraction

    assert _metric_as_fraction(0.85, units="fraction") == 0.85
    assert _metric_as_fraction(85.0, units="percent") == 0.85
    assert _volume_metric_as_fraction(
        {"v100": 85.0, "volume_metric_units": "percent"}, "v100"
    ) == 0.85
    # Older persisted cases did not carry a declaration.
    assert _metric_as_fraction(0.85) == 0.85
    assert _metric_as_fraction(85.0) == 0.85


def test_training_lifecycle_event_is_not_counted_as_a_training_action():
    from web.server_support import _append_ui_event, _drop_ui_bucket, _ui_bucket

    session_id = f"training-audit-{uuid4()}"
    try:
        bucket = _ui_bucket(session_id)
        bucket["training"]["active"] = True
        _append_ui_event(
            session_id,
            {"type": "training.start", "label": "Training started"},
            include_in_training=False,
        )
        _append_ui_event(session_id, {"type": "manual.dose", "label": "Dose updated"})
        assert [item["type"] for item in bucket["events"]] == ["training.start", "manual.dose"]
        assert [item["type"] for item in bucket["training"]["events"]] == ["manual.dose"]
    finally:
        _drop_ui_bucket(session_id)


def test_training_monitor_frontend_handles_high_value_checkpoints_and_report_lifecycle():
    root = Path(__file__).resolve().parents[1]
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    routes = (root / "web/routes/planning_routes.py").read_text(encoding="utf-8")

    assert "const isDoseCheckpoint = type === 'manual.dose'" in ui_api
    assert "trainingMonitorState.lastFeedbackAt = 0;" in manual
    assert "const localizedAdvice = data.localized_advice || data.advice;" in manual
    assert "_formatAdviceReport(localizedAdvice, fallbackPrefix, language)" in manual
    assert "description`` is kept as a compatibility fallback" in ui_api
    assert "training_events = training.get(\"events\")" in routes
    assert "events from before monitoring began" in routes
    assert "feedback_localized" in routes
    assert "localized_advice" in routes
    assert "language" in ui_api
    assert "screenshotGalleryContext" in ui_api
    assert "_snapshotScreenshotViewerState" in ui_api
    assert "_restoreScreenshotViewerState(snapshot, restoreFocus)" in ui_api
    assert "focusPlanningSeedsForScreenshot" in ui_api or "focusPlanningSeedsForScreenshot" in manual
    assert "setMonitorPresentation" in ui_api
    assert "setTrainingMonitorPhase" in ui_api
    assert "monitorConversationLanguage" in ui_api
    assert "monitor_run_id" in ui_api
    assert "monitor_run_id" in routes
    assert "pendingFeedback" in ui_api
    assert "_queueMonitorFeedback" in ui_api
    assert "_flushMonitorFeedback" in ui_api
    assert "}, 2500);" in ui_api
    assert "monitorStatus" in (root / "web/app/index.html").read_text(encoding="utf-8")
    assert 'id="monitorStartButton"' in (root / "web/app/index.html").read_text(encoding="utf-8")
    assert 'id="monitorStopButton"' in (root / "web/app/index.html").read_text(encoding="utf-8")
    css = (root / "web/app/static/css/brachybot-chat-status.css").read_text(encoding="utf-8")
    assert "body.monitor-active::after" in css
    assert ".monitor-status[hidden]" in css
    assert "#monitorStartButton," in css
    assert "monitor-edge-breathe" in css
    assert "monitor-avatar-breathe" in css


def test_monitor_lifecycle_keeps_feedback_and_evidence_case_scoped():
    root = Path(__file__).resolve().parents[1]
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    routes = (root / "web/routes/planning_routes.py").read_text(encoding="utf-8")
    css = (root / "web/app/static/css/brachybot-chat-status.css").read_text(encoding="utf-8")

    # A delayed timer from another case may not erase a new case's feedback.
    assert "function _flushMonitorFeedback(ownerSessionId, ownerRunId, options = {})" in ui_api
    assert "if (!ownsRun || ownerSessionId !== _activeApiSessionId())" in ui_api
    assert "{ allowStopping: true }" in manual
    assert manual.index("_flushMonitorFeedback(stopSessionId, stopRunId") < manual.index("window.setTrainingMonitorPhase('stopping')")
    # A late /training/start response cannot restore its global visual state in
    # another selected session, and an empty interceptor attachment array must
    # not discard the gallery attachment built by the capture pipeline.
    assert "|| _activeApiSessionId() !== startSessionId) return data;" in manual
    assert "Array.isArray(result.attachments) && result.attachments.length" in ui_api
    assert "monitorScreenshotContext.items || []" in ui_api
    # The perimeter transitions both in and out, while remaining entirely
    # non-interactive.
    assert ".monitor-edge-overlay.is-visible" in css
    assert "pointer-events: none;" in css
    # UI telemetry must not hydrate a cold case just to answer a click.
    assert "agent = get_cached_agent(session_id) if monitor_run_matches" in routes
    assert "and request_run_id" in routes
    assert "A monitor run is already active for this case." in routes


def test_monitor_seed_focus_restores_camera_and_mesh_state_after_capture():
    root = Path(__file__).resolve().parents[1]
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")

    assert "function focusPlanningSeedsForScreenshot" in manual
    assert "meshStates" in manual
    assert "saved.meshStates.forEach" in manual
    assert "box.isEmpty()" in manual
    assert "focusPlanningSeedsForScreenshot(options.focusSeedIds)" in ui_api


def test_manual_workflow_exposes_real_surgical_guide_actions():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web/app/index.html").read_text(encoding="utf-8")
    guide = (root / "web/app/static/js/brachybot-surgical-guide.js").read_text(encoding="utf-8")

    assert 'id="generateSurgicalGuideButton"' in html
    assert "generateSurgicalGuide()" in html
    assert "exportSurgicalGuideSTL()" in html
    assert "guideNeedleSelection" in html
    assert "/api/surgical-guides/generate" in guide


def test_monitor_and_screenshots_prefer_global_ui_language():
    root = Path(__file__).resolve().parents[1]
    chat_core = (root / "web/app/static/js/brachybot-chat-core.js").read_text(encoding="utf-8")
    ui_api = (root / "web/app/static/js/brachybot-ui-api.js").read_text(encoding="utf-8")
    manual = (root / "web/app/static/js/brachybot-3d-manual.js").read_text(encoding="utf-8")

    assert "function detectConversationLanguage(text)" in chat_core
    assert "function conversationLanguageForSession" in chat_core
    assert "session.conversationLanguage = detectedLanguage" in chat_core
    assert "if (window._i18nLang) return window._i18nLang;" in ui_api
    assert "const raw = window._i18nLang || (" in ui_api
    assert "const language = monitorConversationLanguage(ownerSessionId);" in ui_api
    assert "window.monitorConversationLanguage(startSessionId)" in manual
    assert "window.monitorConversationLanguage(stopSessionId)" in manual


def test_monitor_maps_manual_stages_to_their_own_viewer_checkpoint():
    from web.server_support import (
        _format_training_summary,
        _training_feedback_for_event,
        _training_screenshot_for_event,
    )

    trajectory_event = {
        "type": "planning.step",
        "label": "Trajectory refinement completed",
        "detail": {"step": "trajectory_refine"},
        "language": "en",
    }
    dose_event = {
        "type": "planning.step",
        "label": "Dose evaluation completed",
        "detail": {"step": "dose_eval"},
        "language": "en",
    }
    running_event = {
        "type": "planning.step",
        "label": "Seed planning started",
        "detail": {"step": "seed_planning"},
        "language": "en",
    }

    assert _training_screenshot_for_event(None, None, trajectory_event, "stage") == {
        "target": "viewer-3d",
        "question": "Training monitor snapshot: show the 3D viewer, needle/seed output, and Data Tree after Trajectory refinement.",
    }
    assert _training_screenshot_for_event(None, None, dose_event, "stage")["target"] == "dose-overview"
    assert _training_screenshot_for_event(None, None, running_event, "stage") is None
    assert "Trajectory refinement completed" in _training_feedback_for_event(None, None, trajectory_event)

    class Memory:
        def __init__(self):
            self.values = {
                "manual_seeds": [
                    {
                        "id": "seed_a",
                        "needle_id": "needle_1",
                        "position": [0.0, 0.0, 0.0],
                        "direction": [0.0, 0.0, 1.0],
                    },
                    {
                        "id": "seed_b",
                        "needle_id": "needle_2",
                        "position": [0.5, 0.0, 0.0],
                        "direction": [0.0, 0.0, 1.0],
                    },
                ],
                "manual_needles": [],
                "plan_config": {
                    "seed_info": {
                        "length": 4.5,
                        "radius": 0.4,
                        "minimum_clearance_mm": 0.5,
                    }
                },
            }

        def retrieve(self, key):
            return self.values.get(key)

    class Agent:
        memory = Memory()

    close_seed_event = {
        "type": "manual.seed.drag",
        "label": "Seed moved",
        "detail": {},
        "language": "en",
    }
    close_seed_screenshot = _training_screenshot_for_event(
        Agent(), None, close_seed_event, "seed spacing requires review"
    )
    assert close_seed_screenshot["target"] == "viewer-3d"
    assert close_seed_screenshot["focus_seed_ids"] == ["seed_a", "seed_b"]

    from web.server_support import _build_plan_advice
    from web.server_support import _localize_plan_advice

    geometry_advice = _build_plan_advice(Agent(), None)
    pair_issue = next(
        item for item in geometry_advice["issues"]
        if "seed_a (needle_1)" in item
    )
    assert "seed_b (needle_2)" in pair_issue
    assert "surface clearance" in pair_issue
    localized = _localize_plan_advice(geometry_advice, "zh")
    assert any("表面间隙" in item for item in localized["issues"])

    zh_summary = _format_training_summary(
        [trajectory_event],
        {"planning.step": 1},
        {"strengths": ["CTV V100 is 91.0%; compare it with the applicable site-specific guidance or confirmed case protocol target."], "issues": [], "advice": []},
        "zh",
    )
    assert "\u89c4\u5212\u76d1\u6d4b\u603b\u7ed3" in zh_summary
    assert "CTV V100 \u4e3a 91.0%" in zh_summary
