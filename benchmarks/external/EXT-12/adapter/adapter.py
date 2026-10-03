"""EXT-12 · AgentClinic adapter (DESIGN §25.3.12, §25.5).

AgentClinic (SamuelSchmidgall/AgentClinic, MIT) is a simulated-clinic (OSCE)
benchmark: a doctor agent is given an objective, interviews the patient /
requests tests, and must emit ``DIAGNOSIS READY: <dx>``.

Upstream schema (``agentclinic.py``)::

    {"OSCE_Examination": {"Objective_for_Doctor", "Patient_Actor",
                          "Physical_Examination_Findings", "Test_Results",
                          "Correct_Diagnosis"}}

Only the text-only doctor prompt is materialised here; the NEJM splits carry
images and are out of scope.  Upstream scoring is an **LLM moderator**
(``compare_results`` -> ``query_model``) that asks a judge model whether the
doctor dialogue names the same disease, so it cannot run offline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-12"))

#: text-only splits, in stable order; NEJM (image) splits are intentionally
#: excluded (DESIGN §25.3.12).
_SOURCES = (
    ("medqa", "agentclinic_medqa.jsonl"),
    ("medqa_extended", "agentclinic_medqa_extended.jsonl"),
)


class AgentClinicAdapter(ExtAdapter):
    EXT_ID = "EXT-12"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P1",)

    def __init__(self) -> None:
        self._rows: Optional[List[str]] = None
        self._index: Dict[str, Dict[str, Any]] = {}

    # -- data --------------------------------------------------------------
    def _ensure(self) -> List[str]:
        if self._rows is None:
            rows: List[str] = []
            for split, fname in _SOURCES:
                path = xc.require_path(
                    os.path.join(_DATA, fname), f"AgentClinic {fname}"
                )
                for i, rec in enumerate(xc.read_jsonl(path), start=1):
                    osce = (rec or {}).get("OSCE_Examination") or {}
                    tid = f"{split}/{i:04d}"
                    self._index[tid] = {
                        "split": split,
                        "objective": osce.get("Objective_for_Doctor", ""),
                        "correct_diagnosis": osce.get("Correct_Diagnosis", ""),
                        "osce": osce,
                    }
                    rows.append(tid)
            self._rows = rows
        return self._rows

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        return list(self._ensure())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure()
        item = self._index[task_id]
        dx = item["correct_diagnosis"]
        return {
            "task_id": task_id,
            "objective": item["objective"],
            "correct_diagnosis": dx,
            "reference_answer": f"DIAGNOSIS READY: {dx}",
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        raise xc.UpstreamUnavailable(
            "AgentClinic legacy adapter does not implement the upstream patient/test "
            "simulation loop. Data retained for reference; single-turn doctor prompts "
            "must not be reported as AgentClinic results."
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise xc.UpstreamUnavailable(
            "AgentClinic scoring is the upstream LLM moderator "
            "(agentclinic.compare_results -> query_model), which asks a judge "
            "model to compare the doctor dialogue against Correct_Diagnosis; "
            "it needs a live moderator LLM / API key and is not runnable offline"
        )

    def offline_probe(self):
        tasks = self._ensure()
        if not tasks:
            return ("fail", "no AgentClinic scenarios loaded")
        tid = tasks[0]
        obs = self.build_input(tid)
        if not obs["objective"]:
            return ("fail", f"prompt/reference did not build for {tid}")
        return ("blocked",
                f"{len(tasks)} text-only scenarios load (medqa+medqa_extended) and the "
                "doctor prompt builds, but the legacy adapter lacks the upstream "
                "patient/test interaction loop; not admitted for comparisons")
