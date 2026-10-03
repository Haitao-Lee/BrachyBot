"""EXT-11 · MedCalc-Bench adapter (DESIGN §25.3, §25.5).

Data: the HF release ``ncbi/MedCalc-Bench`` ``test_data_11_18_final.csv``
(CC-BY-SA-4.0 for the data, MIT/ncbi-nlp code), materialised under
``external/EXT-11/data/`` by ``fetch_all.sh``.  The vendored upstream tree
(commit ``20b10f9``) supplies the official deterministic evaluator at
``vendor/evaluation/evaluate.py``.

Scoring is delegated verbatim to the upstream reusable function
``check_correctness`` (date parsing / integer rounding / decimal tolerance
band).  Nothing is re-implemented here.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-11"), "test_data_11_18_final.csv")
_EXPECTED_BYTES = 5350557


def _load_evaluator():
    """Import the upstream ``evaluation/evaluate.py`` module lazily.

    The vendored tree is registered as a package so its top-level modules never
    shadow the standard library; ``evaluate`` itself is imported without an
    ``__init__.py`` by supplying an explicit ``__path__``.
    """
    vendor = xc.vendor_dir("EXT-11")
    evaluation_dir = os.path.join(vendor, "evaluation")
    if not os.path.isfile(os.path.join(evaluation_dir, "evaluate.py")):
        raise xc.UpstreamUnavailable(
            f"upstream evaluator missing at {evaluation_dir}/evaluate.py"
        )
    xc.ensure_vendor_package("medcalc", vendor)
    xc.ensure_vendor_package("medcalc.evaluation", evaluation_dir)
    return importlib.import_module("medcalc.evaluation.evaluate")


class MedCalcAdapter(ExtAdapter):
    EXT_ID = "EXT-11"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P2",)

    def __init__(self) -> None:
        self._rows: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}

    # -- data --------------------------------------------------------------
    def _ensure_rows(self) -> List[Dict[str, Any]]:
        if self._rows is None:
            path = xc.require_path(_DATA, "MedCalc-Bench test_data_11_18_final.csv")
            size = os.path.getsize(path)
            if size != _EXPECTED_BYTES:
                raise xc.DatasetUnavailable(
                    f"{path} has {size} B, expected {_EXPECTED_BYTES} B "
                    "(truncated download?)"
                )
            import pandas as pd

            rows: List[Dict[str, Any]] = []
            df = pd.read_csv(path)
            for r in df.to_dict(orient="records"):
                tid = str(r["Row Number"])
                rec = {**r, "task_id": tid}
                rows.append(rec)
                self._by_id[tid] = rec
            self._rows = rows
        return self._rows

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        rows = self._ensure_rows()
        return [r["task_id"] for r in rows]

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure_rows()
        row = self._by_id[task_id]
        return {
            "patient_note": row["Patient Note"],
            "question": row["Question"],
            "calculator": row["Calculator Name"],
            "reference_answer": row["Ground Truth Answer"],
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        row = self._by_id[task_id]
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={
                "calculator": obs["calculator"],
                "calculator_id": int(row["Calculator ID"]),
                "question": obs["question"],
                "note_chars": len(obs["patient_note"]),
            },
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={
                "tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                "partial_status": "COMPLETED",
            },
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_rows()
        row = self._by_id[record["source_task_id"]]
        answer = record["sut_output"].get("text", "")
        evaluate = _load_evaluator()
        correctness = evaluate.check_correctness(
            answer,
            row["Ground Truth Answer"],
            int(row["Calculator ID"]),
            row["Upper Limit"],
            row["Lower Limit"],
        )
        return {
            "ext_id": self.EXT_ID,
            "source_task_id": record["source_task_id"],
            "upstream_verdict": {
                "correctness": int(correctness),
                "is_correct": bool(correctness),
                "calculator_id": int(row["Calculator ID"]),
                "answer": answer,
                "ground_truth": row["Ground Truth Answer"],
                "evaluator": "evaluation/evaluate.py::check_correctness",
            },
            "rescored": False,
        }

    def offline_probe(self):
        rows = self._ensure_rows()
        probes = [rows[0]]
        for wanted in (13, 4):  # first date and first integer calculator
            hit = next((r for r in rows if int(r["Calculator ID"]) == wanted), None)
            if hit is not None:
                probes.append(hit)
        for row in probes:
            rec = {
                "ext_id": self.EXT_ID,
                "source_task_id": row["task_id"],
                "sut_output": {"text": row["Ground Truth Answer"]},
            }
            verdict = self.score(rec)["upstream_verdict"]
            if not verdict["is_correct"]:
                return (
                    "fail",
                    f"ground-truth answer scored incorrect for row {row['task_id']} "
                    f"(calculator {verdict['calculator_id']})",
                )
        kinds = sorted({r["Output Type"] for r in probes})
        return (
            "ok",
            f"upstream check_correctness marked ground truth correct for "
            f"{len(probes)}/{len(probes)} probes ({', '.join(kinds)}); "
            f"delegated to evaluation/evaluate.py::check_correctness over "
            f"{len(rows)} rows / {len(self._by_id)} tasks",
        )
