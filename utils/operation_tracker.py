"""Process-local tracking for graceful shutdown of active tool operations."""

from __future__ import annotations

import itertools
import threading
import time
from typing import Dict, List


_active: Dict[int, dict] = {}
_counter = itertools.count(1)
_lock = threading.RLock()
_local = threading.local()


class OperationContext:
    def __init__(self, name: str):
        self.name = str(name)
        self.operation_id = None
        self._nested = False

    def __enter__(self):
        depth = getattr(_local, "depth", 0)
        self._nested = depth > 0
        _local.depth = depth + 1
        if self._nested:
            return self
        with _lock:
            self.operation_id = next(_counter)
            _active[self.operation_id] = {
                "name": self.name,
                "started_at": time.time(),
                "thread": threading.current_thread().name,
            }
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        _local.depth = max(0, getattr(_local, "depth", 1) - 1)
        if not self._nested and self.operation_id is not None:
            with _lock:
                _active.pop(self.operation_id, None)
        return False


def track_operation(name: str) -> OperationContext:
    return OperationContext(name)


def get_active_operations() -> List[dict]:
    with _lock:
        now = time.time()
        return [
            {
                "id": operation_id,
                "name": metadata["name"],
                "thread": metadata["thread"],
                "elapsed_sec": round(now - metadata["started_at"], 1),
            }
            for operation_id, metadata in sorted(_active.items())
        ]
