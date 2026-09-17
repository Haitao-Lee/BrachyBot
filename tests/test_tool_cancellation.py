"""Cooperative-cancellation contracts for long-running agent tools.

An explicit chat Stop must abort in-flight tool work instead of leaving it
running behind the next same-case turn. The guide's 0.2 mm grid resample is
the reference heavy loop: it samples an 836M-voxel crop and used to run to
completion (~117 s) after the user had already stopped the task.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from agent_runtime import contracts as agent_contracts
from tool_factory import ToolResult
from utils.cancellation import (
    OperationCancelled,
    cancellation_scope,
    is_cancelled,
    raise_if_cancelled,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_cancellation_scope_only_affects_the_owning_thread():
    assert is_cancelled() is False
    with cancellation_scope(lambda: True):
        assert is_cancelled() is True
        with pytest.raises(OperationCancelled):
            raise_if_cancelled()
    assert is_cancelled() is False
    raise_if_cancelled()  # outside a scope this must be a no-op


def _skin_mask(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    mask = np.zeros((60, 80, 70), dtype=bool)
    mask[10:50, 15:65, 12:58] = rng.random((40, 50, 46)) > 0.35
    return mask


def test_guide_resample_parallel_matches_serial(monkeypatch):
    from web.surgical_guide import _resample_mask_to_local_grid

    mask = _skin_mask()
    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_WORKERS", "1")
    serial = _resample_mask_to_local_grid(
        mask, (1.0, 0.7, 0.7), 0.2, return_signed_distance=True
    )
    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_WORKERS", "8")
    parallel = _resample_mask_to_local_grid(
        mask, (1.0, 0.7, 0.7), 0.2, return_signed_distance=True
    )

    serial_mask, serial_spacing, serial_distance = serial
    parallel_mask, parallel_spacing, parallel_distance = parallel
    assert np.array_equal(serial_mask, parallel_mask)
    assert np.array_equal(
        serial_distance.view(np.uint8), parallel_distance.view(np.uint8)
    )
    assert tuple(serial_spacing) == tuple(parallel_spacing)


def test_guide_resample_aborts_promptly_when_turn_cancelled(monkeypatch):
    from web.surgical_guide import _resample_mask_to_local_grid

    monkeypatch.setenv("BRACHYBOT_GUIDE_RESAMPLE_WORKERS", "1")
    mask = _skin_mask()
    with cancellation_scope(lambda: True):
        started = time.perf_counter()
        with pytest.raises(OperationCancelled):
            _resample_mask_to_local_grid(
                mask, (1.0, 0.7, 0.7), 0.2, return_signed_distance=True
            )
        elapsed = time.perf_counter() - started
    # Nothing may be written to the local grid before the loop poll rejects
    # the cancelled turn, and the abort must not wait for the full scan.
    assert elapsed < 1.0


def _cancelling_tool_factory():
    from tool_factory import BaseTool

    class CancellingTool(BaseTool):
        name = "cancelling_probe"
        description = "test probe"
        input_schema = {}

        def _execute(self, **kwargs) -> ToolResult:
            raise OperationCancelled("cancelled inside tool")

    return CancellingTool()


def test_base_tool_execute_reraises_cancellation_instead_of_failing_result():
    tool = _cancelling_tool_factory()
    with pytest.raises(OperationCancelled):
        tool.execute()


def test_tool_gateway_reraises_cancellation_instead_of_journaling_failure():
    registry = _RegistryStub()
    gateway = agent_contracts.ToolCallGateway(agent_contracts.RunLedger())

    def _executor():
        raise OperationCancelled("cancelled inside gateway executor")

    with pytest.raises(OperationCancelled):
        gateway.execute(registry, "cancelling_probe", {}, _executor)


class _RegistryStub:
    tool_names = ("cancelling_probe",)

    def get(self, name):
        class _Tool:
            input_schema = {"type": "object", "properties": {}}

        return _Tool()


def test_agent_tool_paths_install_the_cancellation_scope():
    llm_runtime = _read("agent_runtime/llm_runtime.py")
    chat_workflows = _read("agent_runtime/chat_workflows.py")
    assert "from utils.cancellation import cancellation_scope" in llm_runtime
    assert "with cancellation_scope(_cancelled):" in llm_runtime
    assert "from utils.cancellation import cancellation_scope" in chat_workflows
    assert (
        "with cancellation_scope(lambda: self._is_turn_cancelled(self._current_turn_token())):"
        in chat_workflows
    )


def test_guide_resample_polls_cancellation_inside_the_slab_loop():
    surgical_guide = _read("web/surgical_guide.py")
    assert "from utils.cancellation import raise_if_cancelled" in surgical_guide
    assert "def _resample_worker_count(slab_count: int) -> int:" in surgical_guide
    assert "raise_if_cancelled()" in surgical_guide
    assert "ThreadPoolExecutor(max_workers=workers)" in surgical_guide
    assert "GUIDE_RESAMPLE_MAX_WORKERS = 8" in surgical_guide


def test_explicit_stop_clears_the_single_progress_dock():
    chat_todo = _read("web/app/static/js/brachybot-chat-todo.js")
    # Stop must cancel the global Progress dock even when this turn's
    # closure never owned a todo instance.
    assert "window._activeTodoApi?.cancel?.('Stopped');" in chat_todo
    # Both attach paths (new turn, resumed task) claim the single dock
    # instead of stacking a second root that can outlive its turn.
    assert chat_todo.count("dock.replaceChildren(todo.root);") >= 2
