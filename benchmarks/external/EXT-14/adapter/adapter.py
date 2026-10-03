"""EXT-14 · MedPhysBench adapter (DESIGN §25.3, §25.5).

Data: the public task YAMLs of ``udiram/MedPhysBench`` (commit ``bde8dc6``;
code MIT, tasks CC0-1.0), vendored under ``external/EXT-14/vendor/`` and copied
self-contained into ``external/EXT-14/data/tasks/public/**/task.yaml`` (97
tasks).

Scoring is delegated verbatim to the upstream deterministic grader
``medphys_agentbench.scoring`` (``score_attempt`` / ``grades_pass`` /
``grades_safe`` / ``weighted_grade_score``); task loading goes through the
upstream ``medphys_agentbench.task_loader``.  Nothing is re-implemented here.

The upstream ``src/`` tree is appended (never inserted) to ``sys.path`` and
imported lazily so its top-level modules cannot shadow the standard library.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-14"), "tasks", "public")
_PROBE_TASK_ID = "public.brachy.dwell-time-scaling-001"


def _load_upstream():
    """Import the vendored ``medphys_agentbench`` scoring + loader modules."""
    src = os.path.join(xc.vendor_dir("EXT-14"), "src")
    if not os.path.isdir(src):
        raise xc.UpstreamUnavailable(
            f"vendored upstream source missing at {src}"
        )
    if src not in sys.path:
        sys.path.append(src)
    scoring = importlib.import_module("medphys_agentbench.scoring")
    task_loader = importlib.import_module("medphys_agentbench.task_loader")
    return scoring, task_loader


def _parse_output(raw: Any) -> Dict[str, Any]:
    """Coerce a SUT return value into the answer dict the graders expect.

    Accepts a JSON object (``dict`` or JSON ``str``).  A thin ``{"text": ...}``
    envelope (as produced by the E0 ``NullSUT``) is unwrapped when its ``text``
    is itself a JSON object.
    """
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            return {"text": raw}
        return obj if isinstance(obj, dict) else {"text": raw}
    if isinstance(raw, dict):
        if set(raw).issubset({"text", "trace", "artifacts"}) and isinstance(
            raw.get("text"), str
        ):
            try:
                inner = json.loads(raw["text"])
            except (TypeError, ValueError):
                return raw
            if isinstance(inner, dict):
                return inner
        return raw
    return {}


class MedPhysBenchAdapter(ExtAdapter):
    EXT_ID = "EXT-14"
    GRADE_R = "R0"
    GRADE_C = "C3"
    PANELS = ("P4", "P5")

    def __init__(self) -> None:
        self._tasks_by_id: Optional[Dict[str, Any]] = None
        self._order: Optional[List[str]] = None

    # -- data --------------------------------------------------------------
    def _ensure_tasks(self) -> Dict[str, Any]:
        if self._tasks_by_id is None:
            root = xc.require_path(_DATA, "MedPhysBench public task YAMLs")
            _, task_loader = _load_upstream()
            by_id: Dict[str, Any] = {}
            order: List[str] = []
            for path in task_loader.discover_tasks(root):
                task = task_loader.load_task(path)
                tid = str(task.task_id)
                if tid not in by_id:
                    by_id[tid] = task
                    order.append(tid)
            self._tasks_by_id = by_id
            self._order = order
        return self._tasks_by_id

    @staticmethod
    def _reference_answer(task: Any) -> Dict[str, Any]:
        """Best-effort gold output derived from the upstream grader specs.

        ``numeric_tolerance``/``exact_match``/list/IoU/mask graders all encode
        their gold value; ``contains_all_strings`` is joined into a single
        string.  The escalation flag from ``safety`` is added when declared.
        """
        ref: Dict[str, Any] = {}
        grading = task.grading if isinstance(task.grading, dict) else {}
        for spec in grading.get("graders", []) or []:
            if not isinstance(spec, dict):
                continue
            gtype = str(spec.get("type", ""))
            field = spec.get("field")
            if not field:
                continue
            if gtype in {
                "numeric_tolerance", "exact_match", "unordered_list_exact_match",
                "bounding_box_iou", "grid_mask_dice",
            }:
                if "expected" in spec:
                    ref[str(field)] = spec["expected"]
            elif gtype == "contains_all_strings":
                expected = spec.get("expected") or []
                ref[str(field)] = " ".join(str(item) for item in expected)
        safety = task.safety if isinstance(task.safety, dict) else {}
        if isinstance(safety.get("requires_escalation"), bool):
            ref.setdefault("requires_escalation", safety["requires_escalation"])
        return ref

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        self._ensure_tasks()
        return list(self._order or [])

    def build_input(self, task_id: str) -> Dict[str, Any]:
        by_id = self._ensure_tasks()
        task = by_id[task_id]
        obs: Dict[str, Any] = {
            "task_id": str(task.task_id),
            "title": str(task.title),
            "domain": str(task.domain),
            "instructions": str(task.instructions),
            "input_payload": task.input_payload,
            "expected_output_schema": task.expected_output_schema,
        }
        reference = self._reference_answer(task)
        if reference:
            obs["reference_answer"] = reference
        return obs

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {}
        answer = _parse_output(out)
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={
                "title": obs["title"],
                "domain": obs["domain"],
                "instructions": obs["instructions"],
                "input_payload": obs["input_payload"],
            },
            sut_output=answer,
            derived={
                "tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                "partial_status": "COMPLETED",
            },
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        by_id = self._ensure_tasks()
        task = by_id[record["source_task_id"]]
        output = _parse_output(record.get("sut_output"))
        scoring, _ = _load_upstream()
        grades = scoring.score_attempt(task, output)
        return {
            "ext_id": self.EXT_ID,
            "source_task_id": record["source_task_id"],
            "upstream_verdict": {
                "passed": bool(scoring.grades_pass(grades)),
                "safe": bool(scoring.grades_safe(grades)),
                "weighted_score": float(scoring.weighted_grade_score(grades)),
                "grades": [grade.to_dict() for grade in grades],
            },
        }

    def offline_probe(self):
        by_id = self._ensure_tasks()
        candidates = []
        if _PROBE_TASK_ID in by_id:
            candidates.append(_PROBE_TASK_ID)
        candidates.extend(
            tid for tid in (self._order or [])
            if tid not in candidates and str(by_id[tid].track) == "calculator"
        )
        for tid in candidates:
            task = by_id[tid]
            ref = self._reference_answer(task)
            props = (task.expected_output_schema or {}).get("properties", {})
            required = (task.expected_output_schema or {}).get("required", [])
            output = {k: v for k, v in ref.items() if not props or k in props}
            if any(field not in output for field in required):
                continue
            verdict = self.score(
                {"source_task_id": tid, "sut_output": output}
            )["upstream_verdict"]
            if verdict["passed"] and verdict["safe"]:
                return (
                    "ok",
                    f"upstream score_attempt marked {tid!r} passed+safe "
                    f"(weighted_score={verdict['weighted_score']:.3f}) over "
                    f"{len(self._order or [])} public tasks",
                )
        return ("fail", "no public calculator task could be satisfied from its YAML graders")
