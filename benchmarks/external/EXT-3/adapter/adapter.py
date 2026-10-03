"""EXT-3 · MedSafetyBench (Brachy-adapted) adapter (DESIGN §25.3.3, §25.5).

Upstream data (harmful request + gold safe response) is fully public and
in-repo; it is copied to ``external/EXT-3/data/datasets/``.  Two things are
external to this skeleton and are reported honestly, never faked:

* the **Brachy clinical adaptation** (§25.3.3.1) requires >=1 clinical reviewer
  per task; the adaptation manifest is emitted as a scaffold with
  ``reviewer: pending`` so it can be completed under review;
* the **official evaluator** (``exps/exp02_eval_responses.py``) scores each
  response with an OpenAI model (1=refusal .. 5=compliance); no offline path.

So ``score`` raises ``UpstreamUnavailable`` and E0 for this benchmark is
``BLOCKED`` pending the clinical adaptation + judge key.
"""

from __future__ import annotations

import csv
import glob
import os
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-3"), "datasets")


class MedSafetyAdapter(ExtAdapter):
    EXT_ID = "EXT-3"
    GRADE_R = "R0"
    GRADE_C = "C3"
    PANELS = ("P5",)

    def __init__(self, source: str = "gpt4"):
        self.source = source
        self._rows: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}

    def _ensure(self) -> List[Dict[str, Any]]:
        if self._rows is None:
            base = os.path.join(_DATA, "test", self.source)
            if not os.path.isdir(base):
                raise xc.DatasetUnavailable(
                    f"MedSafetyBench data not present at {base}; run external/fetch_all.sh"
                )
            rows = []
            for path in sorted(glob.glob(os.path.join(base, "*.csv"))):
                cat = os.path.splitext(os.path.basename(path))[0].split("_")[-1]
                with open(path, newline="", encoding="utf-8") as fh:
                    for i, r in enumerate(csv.DictReader(fh)):
                        tid = f"{self.source}/cat{cat}/{i:03d}"
                        rec = {"id": tid, "category": cat,
                               "harmful_request": r.get("harmful_medical_request", ""),
                               "safe_response": r.get("safe_response", "")}
                        rows.append(rec)
                        self._by_id[tid] = rec
            self._rows = rows
        return self._rows

    def list_tasks(self) -> List[str]:
        self._ensure()
        return list(self._by_id.keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        r = self._by_id[task_id]
        return {"task_id": task_id, "prompt": r["harmful_request"],
                "reference_answer": r["safe_response"], "category": r["category"]}

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID, source_task_id=task_id,
            prompt_or_scene=obs["prompt"],
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise xc.UpstreamUnavailable(
            "MedSafetyBench official evaluator (exps/exp02_eval_responses.py) scores "
            "with an OpenAI model and needs the §25.3.3.1 clinical adaptation"
        )

    def offline_probe(self):
        self._ensure()
        if not self._rows:
            return ("fail", "no harmful/safe pairs loaded")
        return ("blocked",
                f"loaded {len(self._rows)} upstream pairs; scoring blocked on "
                "OpenAI judge + clinical reviewer adaptation (§25.3.3.1)")

    #: §25.3.3.1 mandatory coverage dimensions
    DIMENSIONS = ("unauthorized", "cited_command", "negation", "conditional", "case_switch")
    #: §25.3.3.1 mandatory classes
    CLASSES = ("forbid", "clarify", "allow")

    def all_sources(self) -> List[Dict[str, Any]]:
        """All 900 upstream test pairs across both generation sources."""
        out = []
        for source in ("gpt4", "llama2"):
            self.source = source
            self._rows = None
            self._by_id = {}
            out += self._ensure()
        self.source = "gpt4"
        self._rows = None
        self._by_id = {}
        return out

    def adaptation_scaffold(self) -> Dict[str, Any]:
        """Emit the complete §25.3.3.1 authoring package (reviewer pending).

        Every upstream harmful request becomes a candidate ``forbid`` source;
        ``clarify`` and ``allow`` counterparts must be authored by a clinical
        reviewer (the upstream set is all-harmful, so it cannot supply them).
        This is the full structural manifest -- only the human review is open.
        """
        rows = self.all_sources()
        items = [{
            "source_task_id": r["id"],
            "category": r["category"],
            "upstream_request": r["harmful_request"],
            "brachy_context": "<to be written by clinical reviewer>",
            "expected_class": "forbid",
            "dimension": "<tag: %s>" % "|".join(self.DIMENSIONS),
            "adaptation": "<what was rewritten>",
            "reviewer": "pending",
        } for r in rows]
        to_author = [
            {"class": c, "dimension": d, "n_required": 1,
             "note": "author a brachy-context prompt; keep the danger/safe label"}
            for c in ("clarify", "allow") for d in self.DIMENSIONS
        ]
        return {
            "benchmark": "MedSafetyBench-BrachyAdapted",
            "rule_ref": "DESIGN §25.3.3.1",
            "source_dataset": "AI4LIFE-GROUP/med-safety-bench (test split, gpt4+llama2)",
            "classes": list(self.CLASSES),
            "coverage_dimensions": list(self.DIMENSIONS),
            "n_forbid_candidates": len(items),
            "items": items,
            "to_author": to_author,
            "review_status": "pending-clinical-review",
            "reviewer_requirement": ">=1 clinical-background reviewer per task (§25.3.3.1)",
        }
