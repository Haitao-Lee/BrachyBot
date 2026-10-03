"""EXT-4 · MedMemoryBench adapter (DESIGN §25.3.4, §25.5).

Data: the full HF parquet release ``Cyan27/MedMemoryBench`` (CC-BY-4.0) for both
languages, materialised under ``external/EXT-4/data/<lang>/`` by
``fetch_all.sh``.  The upstream repo's own ``data/`` tree is Git-LFS pointers;
the parquet release is the same content and is what we map onto the upstream
metric classes in ``vendor/metrics/``.

Deterministic metrics (string_contain / option_match) run offline and are
delegated to the upstream classes.  LLM-judge metrics need ``JUDGE_API_KEY``
and raise ``UpstreamUnavailable`` offline.
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-4"))
_LANGS = ("zh", "en")
_OFFLINE_METRIC_FOR = {
    "entity_exact_match": "StringContainMetric",
    "multiple_choice": "OptionMatchMetric",
}
_JUDGE_TYPES = {
    "temporal_localization", "state_update", "inference_generation",
    "multi_hop_clinical_deduction",
}


def _load_metrics():
    import sys

    vendor = xc.vendor_dir("EXT-4")
    # ``metrics`` imports ``utils`` absolutely; append (never insert) so the
    # vendored tree cannot shadow the standard library.
    if vendor not in sys.path:
        sys.path.append(vendor)
    xc.ensure_vendor_package("medmem", vendor)
    return importlib.import_module("medmem.metrics.string_match")


class MedMemoryAdapter(ExtAdapter):
    EXT_ID = "EXT-4"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P6",)

    def __init__(self, langs: Sequence[str] = _LANGS):
        self.langs = tuple(langs)
        self._rows: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[int, str]] = {}
        self._persona_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    # -- data --------------------------------------------------------------
    def _parquet(self, lang: str, name: str) -> str:
        return xc.require_path(
            os.path.join(_DATA, lang, f"{name}.parquet"),
            f"MedMemoryBench {lang}/{name}",
        )

    def _ensure_queries(self) -> List[Dict[str, Any]]:
        if self._rows is None:
            import pyarrow.parquet as pq

            rows: List[Dict[str, Any]] = []
            for lang in self.langs:
                tbl = pq.read_table(self._parquet(lang, "queries"))
                for r in tbl.to_pylist():
                    tid = f"{lang}/p{r['persona_id']}/{r['query_id']}"
                    rec = {"lang": lang, **r}
                    rows.append(rec)
                    self._by_id[tid] = rec
            self._rows = rows
        return self._rows

    def _sessions_for(self, lang: str) -> Dict[int, str]:
        if lang not in self._sessions:
            import pyarrow.parquet as pq

            tbl = pq.read_table(
                self._parquet(lang, "dialogues"),
                columns=["persona_id", "session_id", "turn", "role", "content"],
            )
            acc: Dict[str, Any] = {}
            for r in tbl.to_pylist():
                acc.setdefault(r["persona_id"], {}).setdefault(r["session_id"], []).append(
                    (r["turn"], f"{r['role']}: {r['content']}")
                )
            self._sessions[lang] = {
                pid: {sid: "\n".join(t for _, t in sorted(turns)) for sid, turns in sess.items()}
                for pid, sess in acc.items()
            }
        return self._sessions[lang]

    @staticmethod
    def _gold(row: Dict[str, Any]) -> List[str]:
        try:
            answers = json.loads(row.get("answers") or "[]")
        except (TypeError, ValueError):
            answers = []
        return [a.get("content", "") for a in answers if a.get("is_correct")]

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        self._ensure_queries()
        return list(self._by_id.keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        row = self._by_id[task_id]
        sessions = self._sessions_for(row["lang"]).get(row["persona_id"], {})
        upto = int(row.get("session_id") or 0)
        history = "\n\n".join(
            f"[session {sid}]\n{sessions[sid]}" for sid in sorted(sessions) if sid <= upto
        )
        return {
            "lang": row["lang"], "persona_id": row["persona_id"],
            "query_type": row["query_type"], "history": history,
            "question": row["question"],
            "reference_answer": "、".join(self._gold(row)),
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID, source_task_id=task_id,
            prompt_or_scene={"question": obs["question"], "lang": obs["lang"],
                             "history_chars": len(obs["history"])},
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        row = self._by_id[record["source_task_id"]]
        qtype = row["query_type"]
        if qtype in _JUDGE_TYPES:
            raise xc.UpstreamUnavailable(
                f"MedMemoryBench query_type={qtype!r} uses the upstream LLM judge "
                "(JUDGE_API_KEY); not runnable offline"
            )
        metric_cls = _OFFLINE_METRIC_FOR.get(qtype)
        if metric_cls is None:
            raise xc.UpstreamUnavailable(f"no offline metric mapped for {qtype!r}")
        metrics = _load_metrics()
        metric = getattr(metrics, metric_cls)()
        res = metric.compute(
            query_id=record["source_task_id"], query_type=qtype,
            model_output=record["sut_output"]["text"],
            expected_answers=self._gold(row), question=row["question"],
        )
        return {"ext_id": self.EXT_ID, "source_task_id": record["source_task_id"],
                "upstream_verdict": {"metric": metric.NAME, "score": res.score,
                                     "is_correct": res.is_correct},
                "rescored": False}

    def offline_probe(self):
        self._ensure_queries()
        eem = [t for t, r in self._by_id.items() if r["query_type"] == "entity_exact_match"]
        if not eem:
            return ("fail", "no entity_exact_match query")
        tid = eem[0]
        gold = self._gold(self._by_id[tid])
        rec = {"ext_id": self.EXT_ID, "source_task_id": tid,
               "sut_output": {"text": "、".join(gold)}}
        v = self.score(rec)
        ok = v["upstream_verdict"]["score"] == 1.0
        n_personas = len({(r["lang"], r["persona_id"]) for r in self._rows})
        return ("ok" if ok else "fail",
                f"upstream string_contain exercised over {len(self._rows)} queries / "
                f"{n_personas} personas ({'+'.join(self.langs)}); llm_judge metrics need JUDGE_API_KEY")
