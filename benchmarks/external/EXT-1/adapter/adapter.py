"""EXT-1 · ABRA adapter (DESIGN §25.3.1, §25.5).

ABRA ships no task YAMLs; its tasks are generated from a study manifest.  We
generate the **easy** tier offline from the vendored ``study_manifest.json``
(``scripts/generate_tasks.py --difficulties easy --from-manifest``) into
``external/EXT-1/data/tasks/``.  Medium/hard tiers need the full TCIA DICOM
downloads (see ``data/studies/download_*.py``) and are not bundled.

Scoring is the upstream pure-Python scorer library (``src/scoring``), invoked
verbatim via ``BaseScorer.score``.  The agent's tool trajectory is what we
score; a SUT must return it in ``sut_output['trajectory']``.
"""

from __future__ import annotations

import glob
import os
import sys
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-1"))
_SCORERS = {
    "state_diff_scorer": "StateDiffScorer",
    "exact_match_scorer": "ExactMatchScorer",
    "iou_scorer": "IoUScorer",
    "point_distance_scorer": "PointDistanceScorer",
    "longitudinal_scorer": "LongitudinalScorer",
    "birads_report_scorer": "BiRADSReportScorer",
}


def _vendor_on_path():
    vendor = xc.vendor_dir("EXT-1")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def _load_task(path: str):
    _vendor_on_path()
    from src.tasks.base_task import Task  # type: ignore

    return Task.from_yaml(path)


def _scorer(task):
    _vendor_on_path()
    from src.scoring import outcome  # type: ignore

    return getattr(outcome, _SCORERS[task.scorer])()


class AbraAdapter(ExtAdapter):
    EXT_ID = "EXT-1"
    GRADE_R = "R0"
    GRADE_C = "C3"
    PANELS = ("P3", "P4")

    def __init__(self, tasks_root: Optional[str] = None):
        self.tasks_root = tasks_root or os.path.join(_DATA, "tasks")
        self._files: Dict[str, str] = {}
        self._tasks: Dict[str, Any] = {}

    def _discover(self) -> Dict[str, str]:
        if not self._files:
            if not os.path.isdir(self.tasks_root):
                raise xc.DatasetUnavailable(
                    "ABRA easy tasks not generated; run external/fetch_all.sh"
                )
            for p in sorted(glob.glob(os.path.join(self.tasks_root, "**", "*.yaml"), recursive=True)):
                self._files[os.path.splitext(os.path.basename(p))[0]] = p
        return self._files

    def _task(self, tid: str):
        if tid not in self._tasks:
            self._tasks[tid] = _load_task(self._files[tid])
        return self._tasks[tid]

    def list_tasks(self) -> List[str]:
        return list(self._discover().keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        t = self._task(task_id)
        return {"task_id": task_id, "task_type": t.task_type, "difficulty": t.difficulty,
                "instruction": t.task_description,
                "reference_answer": str((t.expected_outcome or {}).get("answer", ""))}

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {}
        return self.record(
            ext_id=self.EXT_ID, source_task_id=task_id,
            prompt_or_scene={"task_type": obs["task_type"], "instruction": obs["instruction"]},
            sut_output={"text": out.get("text", ""),
                        "trajectory": out.get("trajectory", [])},
            derived={"tool_call_count": len(out.get("trajectory", [])),
                     "wall_clock_s": 0.0, "retries": 0, "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        traj = (record.get("sut_output") or {}).get("trajectory")
        if traj is None:
            raise xc.UpstreamUnavailable(
                "ABRA scoring needs the agent tool trajectory "
                "(sut_output['trajectory']); none supplied"
            )
        t = self._task(record["source_task_id"])
        res = _scorer(t).score(t, traj, (record.get("sut_output") or {}).get("final_state", {}))
        return {"ext_id": self.EXT_ID, "source_task_id": record["source_task_id"],
                "upstream_verdict": res.to_dict(), "rescored": False}

    def offline_probe(self):
        self._discover()
        em = [t for t in self._files if _load_task(self._files[t]).scorer == "exact_match_scorer"]
        if not em:
            return ("fail", "no exact_match task in generated easy set")
        tid = em[0]
        t = self._task(tid)
        expected = (t.expected_outcome or {}).get("answer")
        ref = list(t.reference_trajectory or ["submit_answer"])
        traj = []
        for i, name in enumerate(ref, start=1):
            args = {"answer": expected} if name == "submit_answer" else {}
            traj.append({"turn": i, "tool_name": name, "arguments": args,
                         "success": True, "result": {}})
        res = _scorer(t).score(t, traj, {})
        if res.outcome != 1.0:
            return ("fail", "upstream exact_match_scorer did not return 1.0")
        # DESIGN §25.6 E0 for ABRA requires "viewer launch, task load, at least one outcome";
        # the Viewer/OHIF/Orthanc Docker stack (and TCIA DICOM) is not run here, so
        # the harness parts pass but the E0 gate is not met.
        return ("blocked",
                f"harness PASS (generated {len(self._files)} easy tasks from the pinned "
                "manifest; upstream exact_match_scorer exercised); DESIGN §25.6 Viewer "
                "startup + outcome NOT run (needs Docker/OHIF/Orthanc + TCIA DICOM; "
                "medium/hard tiers need the full TCIA download)")
