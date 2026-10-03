"""Reference EXT adapter (DESIGN §25.5).

The real per-benchmark adapters live at ``external/<ext_id>/adapter/adapter.py``
and translate a specific upstream protocol.  This module is the **reference
implementation** of the contract: it proves the adapter lifecycle end to end
without any vendor checkout:

* ``list_tasks`` / ``build_input`` / ``run_task`` load recorded upstream
  interactions (a replay directory), exactly as a live run would produce them;
* ``score`` returns the **recorded upstream verdict verbatim** -- an adapter
  must never re-implement scoring (DESIGN §25.5);
* ``audit_isolation`` flags any forbidden write (DESIGN §25.8 voids the run).

A live adapter differs only in where the records come from (HTTP / Docker /
in-process), never in the record shape or the scoring path.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
import sys as _sys  # noqa: E402

if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
from adapter_base import ExtAdapter  # noqa: E402


class ReplayExtAdapter(ExtAdapter):
    """EXT adapter that consumes recorded upstream interactions."""

    EXT_ID = "EXT-REPLAY"
    GRADE_R = "R2"          # a replay proves the contract, not upstream quality
    GRADE_C = "C0"

    def __init__(self, records_dir: str):
        self.records_dir = records_dir

    def list_tasks(self) -> List[str]:
        if not os.path.isdir(self.records_dir):
            return []
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(self.records_dir)
            if f.endswith(".json")
        )

    def _load(self, task_id: str) -> Dict[str, Any]:
        path = os.path.join(self.records_dir, f"{task_id}.json")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no recorded interaction for {task_id} at {path}")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def build_input(self, task_id: str) -> Any:
        return self._load(task_id).get("prompt_or_scene")

    def run_task(self, task_id: str, sut_handle: Any,
                 budget: Dict[str, int]) -> Dict[str, Any]:
        rec = self._load(task_id)
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene=rec.get("prompt_or_scene"),
            sut_output=rec.get("sut_output"),
            upstream_verdict=rec.get("upstream_verdict"),
            derived=rec.get("derived"),
            infra_failed=bool(rec.get("infra_failed", False)),
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Return the upstream verdict verbatim.  Never re-score."""
        return {
            "ext_id": record["ext_id"],
            "source_task_id": record["source_task_id"],
            "upstream_verdict": record.get("upstream_verdict") or {},
            "infra_failed": record.get("infra_failed", False),
            "rescored": False,
        }


def isolation_clean(before: Dict[str, float], after: Dict[str, float]) -> bool:
    return not ReplayExtAdapter.audit_isolation(before, after)
