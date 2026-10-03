"""EXT-13 · AMEGA adapter (DESIGN §25.3.13, §25.5).

Data: DATEXIS/AMEGA-benchmark (Apache-2.0).  The four CSVs ship in-repo and are
mirrored under ``external/EXT-13/data/``; the upstream tree lives read-only
under ``vendor/`` and is imported without putting its top level on ``sys.path``.

Hierarchy: case -> question -> section -> weighted criteria.  Given the
per-criterion booleans from the upstream LLM evaluator, scoring is fully
deterministic: ``Experiment.calculate_score`` is ``sum(weight * boolean)``.
Without recorded booleans the evaluator cannot run offline, so :meth:`score`
raises ``UpstreamUnavailable``; :meth:`offline_probe` exercises the upstream
aggregation directly over real criteria.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from typing import Any, Dict, List, Optional, Tuple

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = xc.data_dir("EXT-13")
_VENDOR = xc.vendor_dir("EXT-13")
_REQUIRED_CSV = ("cases.csv", "questions.csv", "sections.csv", "criteria.csv")


def _ensure_tabulate() -> None:
    """``amega.experiment`` imports ``tabulate`` for pretty-printing only.

    The build host lacks it; a display-only shim lets the deterministic scoring
    path load without altering any upstream logic.
    """
    if "tabulate" in sys.modules:
        return
    try:
        import tabulate  # noqa: F401
    except Exception:  # noqa: BLE001
        shim = types.ModuleType("tabulate")
        shim.tabulate = lambda *a, **k: ""  # type: ignore[attr-defined]
        sys.modules["tabulate"] = shim


def _load_upstream():
    if _VENDOR not in sys.path:
        sys.path.append(_VENDOR)
    xc.ensure_vendor_package("amega", os.path.join(_VENDOR, "amega"))
    _ensure_tabulate()
    benchmark_mod = importlib.import_module("amega.benchmark")
    experiment_mod = importlib.import_module("amega.experiment")
    return benchmark_mod, experiment_mod


class AmegaAdapter(ExtAdapter):
    EXT_ID = "EXT-13"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P5",)

    def __init__(self) -> None:
        self._benchmark: Any = None
        self._experiment_mod: Any = None
        self._rows: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}

    # -- data --------------------------------------------------------------
    def _ensure(self) -> None:
        if self._rows is not None:
            return
        for name in _REQUIRED_CSV:
            xc.require_path(os.path.join(_DATA, name), f"AMEGA {name}")
        benchmark_mod, experiment_mod = _load_upstream()
        self._experiment_mod = experiment_mod
        self._benchmark = benchmark_mod.Benchmark(_DATA)
        cases = self._benchmark.cases.set_index("case_id")
        rows: List[Dict[str, Any]] = []
        for q in self._benchmark.questions.sort_values(
            ["case_id", "question_id"]
        ).itertuples():
            cid, qid = int(q.case_id), int(q.question_id)
            tid = f"{cid}/{qid}"
            rec = {
                "case_id": cid,
                "question_id": qid,
                "case_str": str(cases.loc[cid, "case_str"]),
                "question_str": str(q.question_str),
            }
            rows.append(rec)
            self._by_id[tid] = rec
        self._rows = rows

    def _criteria_frame(self, task_id: str):
        rec = self._by_id[task_id]
        crit = self._benchmark.criteria
        mask = (crit["case_id"] == rec["case_id"]) & (
            crit["question_id"] == rec["question_id"]
        )
        return crit.loc[mask]

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        self._ensure()
        return list(self._by_id.keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure()
        rec = self._by_id[task_id]
        crit = self._criteria_frame(task_id)
        positive = crit.loc[crit["criteria_score_possible"] > 0, "criteria_str"].tolist()
        guide = positive or crit["criteria_str"].tolist()
        return {
            "case_str": rec["case_str"],
            "question_str": rec["question_str"],
            "reference_answer": "\n".join(str(c) for c in guide),
        }

    def run_task(
        self, task_id: str, sut_handle: Any, budget: Dict[str, int]
    ) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={
                "case_id": self._by_id[task_id]["case_id"],
                "question_id": self._by_id[task_id]["question_id"],
                "question_str": obs["question_str"],
            },
            sut_output={
                "text": out.get("text", ""),
                "trace": out.get("trace", []),
                "criteria_booleans": out.get("criteria_booleans"),
            },
            derived={
                "tool_call_count": 0,
                "wall_clock_s": 0.0,
                "retries": 0,
                "partial_status": "COMPLETED",
            },
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        out = record.get("sut_output") or {}
        booleans = out.get("criteria_booleans")
        if not booleans:
            raise xc.UpstreamUnavailable(
                "AMEGA criterion booleans come from the upstream LLM evaluator "
                "(EvaluatorModel.run); record['sut_output']['criteria_booleans'] "
                "is required to aggregate a score offline"
            )
        rec = self._by_id[record["source_task_id"]]
        scores = self._benchmark.get_criteria_scores(rec["case_id"], rec["question_id"])
        if len(scores) != len(booleans):
            raise xc.UpstreamUnavailable(
                f"AMEGA criteria/booleans length mismatch for "
                f"{record['source_task_id']}: {len(scores)} vs {len(booleans)}"
            )
        # calculate_score is a pure upstream method (never touches self); call it
        # verbatim rather than re-implementing the weighted sum.
        weighted = self._experiment_mod.Experiment.calculate_score(
            None, scores, list(booleans)
        )
        possible = float(sum(s for s in scores if s > 0))
        return {
            "ext_id": self.EXT_ID,
            "source_task_id": record["source_task_id"],
            "upstream_verdict": {
                "metric": "amega.experiment.Experiment.calculate_score",
                "score": float(weighted),
                "possible_score": possible,
                "n_criteria": len(scores),
            },
            "rescored": False,
        }

    def offline_probe(self) -> Tuple[str, str]:
        self._ensure()
        target: Optional[Tuple[str, List[float]]] = None
        for tid, rec in self._by_id.items():
            sc = self._benchmark.get_criteria_scores(rec["case_id"], rec["question_id"])
            if any(s < 0 for s in sc):
                target = (tid, sc)
                break
        if target is None:
            tid = next(iter(self._by_id))
            rec = self._by_id[tid]
            target = (tid, self._benchmark.get_criteria_scores(rec["case_id"], rec["question_id"]))
        tid, scores = target
        if not scores:
            return ("fail", f"no criteria found for probe task {tid}")
        calc = self._experiment_mod.Experiment.calculate_score
        all_true = calc(None, scores, [True] * len(scores))
        all_false = calc(None, scores, [False] * len(scores))
        possible = float(sum(s for s in scores if s > 0))
        n_neg = sum(1 for s in scores if s < 0)
        ok = all_false == 0.0 and abs(all_true - sum(scores)) < 1e-9
        detail = (
            f"upstream Experiment.calculate_score exercised over {len(self._rows)} "
            f"questions; probe {tid}: all-True={float(all_true)}, all-False={float(all_false)}, "
            f"possible={possible} ({n_neg} negative weights); LLM evaluator supplies the booleans"
        )
        return ("ok" if ok else "fail", detail)
