"""EXT-15 · MedicalAgentsBench adapter (DESIGN §25.3.15, §25.5).

MedicalAgentsBench (``gersteinlab/MedicalAgentsBench``, MIT; arXiv 2503.07459)
is a curated multi-dataset medical MCQ benchmark.  Each row is standardised to
``{"question", "options": {letter: text}, "answer_idx": letter, "answer": text}``
and the upstream evaluation is *single-choice accuracy*.

Upstream evaluation entrypoint
------------------------------
The repository has **no importable evaluator module**: its scoring function
lives only inside the analysis notebooks (``plots/figure2_hardset.ipynb`` and
``plots/table1_performance.ipynb``)::

    def calculate_accuracy(data):
        correct_predictions = 0
        total_predictions = len(data)
        for item in data:
            if item['answer_idx'] == item['predicted_answer']:
                correct_predictions += 1
        accuracy = correct_predictions / total_predictions if total_predictions > 0 else 0
        return accuracy

i.e. a record is **correct iff its predicted letter equals the gold
``answer_idx``**.  Because that rule is not factored into a reusable function,
this adapter *replicates* the documented per-record test rather than importing
it.  When a SUT returns the canonical bare letter (the upstream contract), the
normalisation below reduces to exactly ``answer_idx == predicted_answer``; the
extra letter/content normalisation only rescues common surface forms such as
``"B"``, ``"(B)"``, ``"Answer: B"`` or the option *content*, and only maps them
onto the same letter space, so the accuracy verdict never becomes more lenient
about *which* option is selected.

Data: the public HF parquet test split of ``super-dainiu/MedicalAgentsBench``
for each of the nine benchmark datasets, materialised under
``external/EXT-15/data/<Dataset>.parquet`` (see ``fetch_all.sh``); the bench's
own hard subsets (``test_hard``) are a curation of these files.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = xc.data_dir("EXT-15")

#: full-set task order; task id = f"{dataset}/{index}"
_DATASETS: Sequence[str] = (
    "MedQA", "MedMCQA", "MedBullets", "MMLU-Pro", "MedExQA",
    "AfrimedQA", "MedXpertQA-R", "MedXpertQA-U", "PubMedQA",
)

#: upstream predict field is a bare letter; these rescue ordinary surface forms
_ANSWER_PATTERNS = (
    r"answer\s*(?:is|:)?\s*[\(\[]?([A-Za-z])[\)\]\.\:]?",
    r"[\(\[]([A-Za-z])[\)\]]",
    r"\b([A-Za-z])[\)\]\.\:]",
)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


class MedicalAgentsBenchAdapter(ExtAdapter):
    EXT_ID = "EXT-15"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P1",)

    def __init__(self, datasets: Sequence[str] = _DATASETS):
        self.datasets = tuple(datasets)
        self._order: Optional[List[str]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._n_rows = 0

    # -- data --------------------------------------------------------------
    def _parquet(self, dataset: str) -> str:
        return xc.require_path(
            os.path.join(_DATA, f"{dataset}.parquet"),
            f"MedicalAgentsBench {dataset} test parquet",
        )

    def _ensure(self) -> List[str]:
        if self._order is not None:
            return self._order

        import pyarrow.parquet as pq  # lazy: only needed once data is present

        order: List[str] = []
        for dataset in self.datasets:
            table = pq.read_table(self._parquet(dataset))
            for i, raw in enumerate(table.to_pylist()):
                tid = f"{dataset}/{i}"
                self._by_id[tid] = {"dataset": dataset, "row": raw}
                order.append(tid)
                self._n_rows += 1
        self._order = order
        return order

    @staticmethod
    def _gold(row: Dict[str, Any]) -> Tuple[str, str]:
        """Return ``(gold_letter, gold_content)`` for an upstream row."""
        options = row.get("options") or {}
        letter = _text(row.get("answer_idx")).upper()
        content = _text(row.get("answer")) or _text(options.get(letter, ""))
        return letter, content

    @staticmethod
    def _options(row: Dict[str, Any]) -> Dict[str, str]:
        options = row.get("options") or {}
        return {str(k): _text(v) for k, v in options.items()}

    def _extract_choice(self, raw: Any, options: Dict[str, str]) -> Optional[str]:
        """Map a SUT answer onto an option letter (or ``None``).

        Deterministic order: exact option key, then letter patterns, then exact
        option-content match.  A bare letter (the upstream contract) falls out
        of the first test unchanged.
        """
        s = _text(raw)
        if not s:
            return None
        keys = {k.upper(): k for k in options}
        bare = s.strip("()[]{}.:; ").upper()
        if bare in keys:
            return keys[bare]
        for pat in _ANSWER_PATTERNS:
            m = re.search(pat, s, re.IGNORECASE)
            if m and m.group(1).upper() in keys:
                return keys[m.group(1).upper()]
        low = s.lower()
        for key, text in options.items():
            if text and text.lower() == low:
                return key
        return None

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        return list(self._ensure())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure()
        entry = self._by_id[task_id]
        row = entry["row"]
        letter, content = self._gold(row)
        return {
            "dataset": entry["dataset"],
            "question": _text(row.get("question")),
            "options": self._options(row),
            # upstream expects the bare answer letter; content is carried too
            "reference_answer": letter,
            "reference_letter": letter,
            "reference_content": content,
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={
                "dataset": obs["dataset"],
                "question": obs["question"],
                "n_options": len(obs["options"]),
            },
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic MCQ accuracy, replicating upstream ``calculate_accuracy``.

        Upstream: ``correct`` iff the predicted letter equals ``answer_idx``.
        We normalise both sides into the option-letter space; when the SUT emits
        the canonical bare letter this is byte-for-byte the upstream test.
        """
        self._ensure()
        entry = self._by_id[record["source_task_id"]]
        row = entry["row"]
        options = self._options(row)
        expected_letter, expected_content = self._gold(row)
        got_letter = self._extract_choice((record.get("sut_output") or {}).get("text", ""), options)

        if got_letter is not None:
            correct = got_letter.upper() == expected_letter
            got: Any = got_letter
        else:
            raw = _text((record.get("sut_output") or {}).get("text", ""))
            correct = bool(expected_content) and raw.lower() == expected_content.lower()
            got = raw
        return {
            "ext_id": self.EXT_ID,
            "source_task_id": record["source_task_id"],
            "upstream_verdict": {
                "metric": "mcq_accuracy",
                "correct": bool(correct),
                "expected": expected_letter,
                "got": got,
            },
            "rescored": False,
        }

    def offline_probe(self):
        """Feed the correct letter for a real task and confirm it scores correct."""
        order = self._ensure()
        if not order:
            return ("fail", "no tasks loaded")
        tid = order[0]
        letter, _ = self._gold(self._by_id[tid]["row"])
        rec = {
            "ext_id": self.EXT_ID,
            "source_task_id": tid,
            "sut_output": {"text": letter},
        }
        v = self.score(rec)
        uv = v["upstream_verdict"]
        ok = uv["correct"] and uv["got"] == uv["expected"]
        return (
            "ok" if ok else "fail",
            "upstream calculate_accuracy (answer_idx == predicted letter) exercised "
            f"over {self._n_rows} rows / {len(order)} tasks from {len(self.datasets)} "
            "datasets; scorer is the documented MCQ accuracy replicated from "
            "vendor/plots/figure2_hardset.ipynb (no importable upstream evaluator)",
        )
