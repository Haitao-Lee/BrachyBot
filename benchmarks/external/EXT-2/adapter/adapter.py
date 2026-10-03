"""EXT-2 · HealthBench adapter (DESIGN §25.3.2, §25.5).

Protocol translation only.  Scoring is delegated verbatim to the upstream
``simple_evals.healthbench_eval`` module (``calculate_score``,
``GRADER_TEMPLATE``, ``RubricItem``); this file never re-implements a score.

Live judging needs an LLM grader (``OPENAI_API_KEY``).  Offline, the pure
scoring path is still exercisable with recorded rubric gradings -- that is what
``offline_probe`` does, so E0 can certify the wiring without a paid API.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-2"))
_DEFAULT = "2025-05-07-06-14-12_oss_eval.jsonl"

#: the four upstream jsonl files (DESIGN §25.3.2); ``meta`` is the judge
#: calibration set (§8.5 / O5), the other three are task sets.
DATA_FILES = {
    "oss": "2025-05-07-06-14-12_oss_eval.jsonl",
    "hard": "hard_2025-05-08-21-00-10.jsonl",
    "consensus": "consensus_2025-05-09-20-00-46.jsonl",
    "meta": "2025-05-07-06-14-12_oss_meta_eval.jsonl",
}


def _load_vendor():
    vendor = xc.vendor_dir("EXT-2")
    xc.ensure_vendor_package(
        "simple_evals", vendor, shims={"blobfile": xc.blobfile_shim()}
    )
    return importlib.import_module("simple_evals.healthbench_eval")


class HealthBenchAdapter(ExtAdapter):
    EXT_ID = "EXT-2"
    GRADE_R = "R0"
    GRADE_C = "C3"
    PANELS = ("P1",)

    def __init__(self, data_file: str = _DEFAULT):
        self.path = os.path.join(_DATA, data_file)
        self._rows: Optional[List[Dict[str, Any]]] = None
        self._index: Dict[str, Dict[str, Any]] = {}

    # -- data --------------------------------------------------------------
    def _ensure(self) -> List[Dict[str, Any]]:
        if self._rows is None:
            xc.require_path(self.path, "HealthBench jsonl")
            self._rows = xc.read_jsonl(self.path)
            for i, row in enumerate(self._rows):
                tid = row.get("prompt_id") or f"row-{i:05d}"
                self._index[tid] = row
        return self._rows

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        self._ensure()
        return list(self._index.keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        row = self._index[task_id]
        ideal = row.get("ideal_completions_data") or {}
        return {
            "messages": row.get("prompt") or [],
            "reference_answer": ideal.get("ideal_completion") or "",
            "rubrics": row.get("rubrics") or [],
            "example_tags": row.get("example_tags") or [],
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene=obs["messages"],
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def build_grader_prompt(self, task_id: str, response_text: str) -> str:
        """Exercise the upstream GRADER_TEMPLATE for one example's first rubric."""
        hb = _load_vendor()
        row = self._index[task_id]
        convo = "\n\n".join(
            f"{m['role']}: {m['content']}" for m in list(row.get("prompt") or [])
            + [{"role": "assistant", "content": response_text}]
        )
        rubric = hb.RubricItem.from_dict((row.get("rubrics") or [{"criterion": "", "points": 1.0, "tags": []}])[0])
        return hb.GRADER_TEMPLATE.replace("<<conversation>>", convo).replace(
            "<<rubric_item>>", str(rubric)
        )

    def load_meta_examples(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load the O5 / §8.5 judge-calibration set.

        Rows carry ``prompt`` / ``completion`` / ``rubric`` / ``binary_labels``
        and are used to calibrate the rubric judge, not to score a SUT.
        """
        path = xc.require_path(os.path.join(_DATA, DATA_FILES["meta"]), "HealthBench meta_eval")
        return xc.read_jsonl(path, limit)

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Call the upstream ``calculate_score``; requires recorded gradings.

        ``record['sut_output']['gradings']`` is a list of ``{"criteria_met":bool}``
        aligned with the example's rubrics (as a live judge would produce).
        """
        gradings = (record.get("sut_output") or {}).get("gradings")
        if gradings is None:
            raise xc.UpstreamUnavailable(
                "HealthBench scoring requires an LLM judge (OPENAI_API_KEY); "
                "no recorded gradings supplied"
            )
        return self.score_with_gradings(record["source_task_id"], gradings)

    def score_with_gradings(self, task_id: str, gradings: List[Dict[str, Any]]) -> Dict[str, Any]:
        hb = _load_vendor()
        row = self._index[task_id]
        rubrics = [hb.RubricItem.from_dict(r) for r in (row.get("rubrics") or [])]
        score = hb.calculate_score(rubrics, gradings)
        return {"ext_id": self.EXT_ID, "source_task_id": task_id,
                "upstream_verdict": {"metric": "overall_score", "score": score,
                                     "n_rubrics": len(rubrics)},
                "rescored": False}

    def offline_probe(self):
        """Certify the pure upstream scoring path without any API key."""
        self._ensure()
        if not self._rows:
            return ("fail", "no examples loaded")
        tid = next(iter(self._index))
        row = self._index[tid]
        gradings = [{"criteria_met": False, "explanation": "e0-offline"}
                    for _ in (row.get("rubrics") or [{}])]
        v = self.score_with_gradings(tid, gradings)
        p = self.build_grader_prompt(tid, "e0 offline response")
        ok = v["upstream_verdict"]["score"] == 0.0 and "<<rubric_item>>" not in p
        return ("ok" if ok else "fail",
                "calculate_score + GRADER_TEMPLATE exercised; live judge needs OPENAI_API_KEY")
