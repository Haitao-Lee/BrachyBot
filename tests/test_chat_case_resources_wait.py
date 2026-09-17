"""Progress-aware waits for clinical case resources.

"Loading" must never become a generic failure. The wait reports phases,
fails fast with a precise code when hydration fails or is superseded, and
honours an explicit Stop while the case is still decoding.
"""
import threading
import time

import pytest

from web.chat_tasks import ChatTaskCancelled, ChatTaskError
from web.routes import planning_routes
from web.routes.planning_routes import (
    _chat_requires_full_workspace,
    await_chat_case_resources,
)


class _Shell:
    """Minimal stand-in for a metadata-only Agent shell."""

    def __init__(self, *, ready=False, phase="ct"):
        self._workspace_data_ready = ready
        self._workspace_hydration_in_progress = not ready
        self._workspace_hydration_phase = phase
        self._workspace_hydration_error = ""
        self._workspace_hydration_superseded = False
        self._workspace_ready_event = threading.Event()


def test_lightweight_and_clinical_messages_are_distinguished():
    assert _chat_requires_full_workspace("你好", "") is False
    assert _chat_requires_full_workspace("hello", "") is False
    assert _chat_requires_full_workspace("当前规划结果如何", "") is True
    assert _chat_requires_full_workspace("hello", "/tmp/screenshot.png") is True


def test_wait_reports_phases_until_ready():
    shell = _Shell()
    seen = []

    def report(phase):
        seen.append(phase)
        return True

    def complete():
        time.sleep(0.05)
        shell._workspace_hydration_phase = "artifacts"
        shell._workspace_data_ready = True
        shell._workspace_hydration_in_progress = False
        shell._workspace_ready_event.set()

    threading.Thread(target=complete, daemon=True).start()
    await_chat_case_resources(shell, report, session_id="case-a")
    assert "ct" in seen


def test_wait_cancels_on_stop_without_erroring():
    shell = _Shell()
    with pytest.raises(ChatTaskCancelled):
        await_chat_case_resources(shell, lambda phase: False, session_id="case-a")


def test_wait_fails_fast_with_a_precise_code():
    shell = _Shell()
    shell._workspace_hydration_error = "CT decode failed"
    shell._workspace_hydration_in_progress = False
    with pytest.raises(ChatTaskError) as excinfo:
        await_chat_case_resources(shell, lambda phase: True, session_id="case-a")
    assert excinfo.value.code == "workspace_hydration_failed"
    assert excinfo.value.phase == "ct"
    assert excinfo.value.retryable is True


def test_wait_distinguishes_a_superseded_restore():
    shell = _Shell()
    shell._workspace_hydration_superseded = True
    shell._workspace_hydration_in_progress = False
    with pytest.raises(ChatTaskError) as excinfo:
        await_chat_case_resources(shell, lambda phase: True, session_id="case-a")
    assert excinfo.value.code == "workspace_hydration_cancelled"


def test_wait_rejects_a_silently_stopped_restore():
    shell = _Shell()
    shell._workspace_hydration_in_progress = False
    with pytest.raises(ChatTaskError) as excinfo:
        await_chat_case_resources(shell, lambda phase: True, session_id="case-a")
    assert excinfo.value.code == "workspace_hydration_failed"


def test_wait_times_out_only_when_nothing_progresses(monkeypatch):
    monkeypatch.setattr(planning_routes, "_CHAT_HYDRATION_STALL_TIMEOUT_SECONDS", 0.2)
    shell = _Shell()
    with pytest.raises(ChatTaskError) as excinfo:
        await_chat_case_resources(shell, lambda phase: True, session_id="case-a")
    assert excinfo.value.code == "workspace_hydration_timeout"
