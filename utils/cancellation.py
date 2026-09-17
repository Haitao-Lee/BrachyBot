"""Cooperative cancellation for long-running agent tool work.

The chat worker executes a turn in one thread while long clinical tools run in
a helper thread.  ``ChatTask.cancel`` / ``agent._cancel_active_turn`` can mark
the turn terminal, but a tool that is already inside a heavy loop (for example
the 0.2 mm surgical-guide grid resample) must also observe that state, or the
worker thread and the next same-case turn stay blocked behind it.

The scope below is thread-local on purpose: tools execute in a dedicated
helper thread, and an unrelated request thread must never inherit another
turn's cancellation state.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

_state = threading.local()


class OperationCancelled(Exception):
    """Raised inside tool work after the owning chat turn was cancelled."""


def _active_checker() -> Optional[Callable[[], bool]]:
    return getattr(_state, "checker", None)


@contextmanager
def cancellation_scope(checker: Optional[Callable[[], bool]]) -> Iterator[None]:
    """Install ``checker`` for the current thread while the block runs."""
    previous = _active_checker()
    _state.checker = checker
    try:
        yield
    finally:
        _state.checker = previous


def is_cancelled() -> bool:
    """Return whether the current thread's owner requested cancellation."""
    checker = _active_checker()
    if checker is None:
        return False
    try:
        return bool(checker())
    except Exception:
        # A broken checker must never turn into a fake clinical success; treat
        # it as "not cancelled" so the caller keeps its normal error handling.
        return False


def raise_if_cancelled() -> None:
    """Abort the current tool loop when the owning turn was cancelled."""
    if is_cancelled():
        raise OperationCancelled("Operation cancelled by user")
