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

    assert "const isDoseCheckpoint = type === 'manual.dose'" in ui_api
    assert "trainingMonitorState.lastFeedbackAt = 0;" in manual
    assert "data.summary || _formatAdviceReport(data.advice)" in manual
    assert "description`` is kept as a compatibility fallback" in ui_api

