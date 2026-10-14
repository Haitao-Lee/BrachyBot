"""Public messages follow a bounded explicit locale, never exception prose."""
from types import SimpleNamespace
import pytest

from web.timepoint_messages import (timepoint_message, timepoint_error, supported_language,
    resolve_timepoint_language, timepoint_operation_presentation)
from web.timepoints import TimepointError, TimepointConflict


@pytest.mark.parametrize("locale, expected", [("zh", "zh"), ("zh-CN", "zh"), ("en", "en"),
    ("en-US", "en"), ("fr", ""), ("中文", ""), ("zh\nINJECT", ""), (True, ""), (None, "")])
def test_only_supported_bounded_locales(locale, expected):
    assert supported_language(locale) == expected


def test_explicit_ui_locale_wins_and_never_changes_conversation_memory():
    memory = SimpleNamespace(user_lang="en", retrieve=lambda key: {"code": "en"})
    agent = SimpleNamespace(memory=memory)
    assert resolve_timepoint_language(language="zh", agent=agent) == "zh"
    assert memory.user_lang == "en"
    assert resolve_timepoint_language(agent=agent) == "en"


@pytest.mark.parametrize("language", ["zh", "en"])
def test_raw_exception_and_paths_do_not_enter_public_packets(language):
    exc = TimepointConflict("sensitive-name /private/case/file.nii credential-secret")
    packet, status = timepoint_error(exc, language)
    assert packet["code"] == "timepoint_conflict" and status == 409
    assert packet["language"] == language
    assert "sensitive" not in str(packet) and "/private" not in str(packet) and "credential" not in str(packet)


@pytest.mark.parametrize("count", [True, -1, 257, "12", 1.5])
def test_counts_are_real_bounded_integers(count):
    with pytest.raises(ValueError):
        timepoint_message("timepoint_inspector_listed", "zh", count=count)


def test_unknown_code_retained_but_does_not_become_ui_prose():
    packet = timepoint_message("unknown_future_condition", "zh")
    assert packet["code"] == "unknown_future_condition"
    assert packet["message_code"] == "timepoint_request_failed"
    assert "unknown_future_condition" not in packet["message"]


def test_operation_state_is_preserved_and_free_form_error_not_translated_or_echoed():
    saved = {"task_id": "technical-id", "state": "failed", "error": "PRIVATE STACKTRACE", "message": "RAW ENGLISH"}
    presented = timepoint_operation_presentation(saved, "zh")
    assert presented["task_id"] == "technical-id" and presented["state"] == "failed"
    assert "PRIVATE" not in str(presented) and "RAW ENGLISH" not in str(presented)
    assert saved["error"] == "PRIVATE STACKTRACE"
