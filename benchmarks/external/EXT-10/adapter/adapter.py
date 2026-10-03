"""EXT-10 · MedHallu adapter (DESIGN §25.3.10, §25.5).

MedHallu (arXiv 2502.14302, MIT) is a medical hallucination detection
benchmark derived from PubMedQA: each row pairs a ``ground_truth`` answer with a
generated ``least_similar_answer`` (the hallucination).  The official detector
(``vendor/Detection/detection_vllm_notsurecase.py``) presents one of the two
answers and asks the model to emit ``0`` (factual) / ``1`` (hallucinated) /
``2`` (unsure), then reads that as a binary classification against the known
label using scikit-learn accuracy/precision/recall/F1.

Protocol translation only: this adapter maps every ``(row, candidate)`` pair to
a task, wraps the SUT as the classifier, and reproduces -- verbatim -- the
upstream label parser and the per-record accuracy decision
(``calculate_metrics`` in the vendored script).  It never re-implements the
metric: the parse rule and the ``Correct`` test are copied from upstream.

Data: the two public HF parquet splits (``pqa_labeled`` 1000 rows +
``pqa_artificial`` 9000 rows = the full 10 000 QA pairs) materialised under
``external/EXT-10/data/``.  The released parquet uses title-case column names
(``Question``, ``Ground Truth``, ...) while the upstream script uses the lower
case names it saw in its own CSV; both spellings are accepted here.
"""

from __future__ import annotations

import ast
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = xc.data_dir("EXT-10")

#: (file, split-tag) in the pinned full-set order.
_SPLITS: Sequence[Tuple[str, str]] = (
    ("train_labeled.parquet", "labeled"),
    ("train_artificial.parquet", "artificial"),
)

#: candidate → expected binary label (0 factual, 1 hallucinated), matching the
#: upstream ``answers = [ground_truth, hallucinated_answer]; answer_list.append(
#: random_val)`` ordering.
_CANDIDATES: Sequence[Tuple[str, int]] = (
    ("ground_truth", 0),
    ("hallucinated", 1),
)

#: canonical key → accepted raw column spellings (title-case parquet release and
#: the lower-case names used by the vendored detector).
_COLS: Dict[str, Tuple[str, ...]] = {
    "question": ("Question", "question"),
    "ground_truth": ("Ground Truth", "ground_truth"),
    "least_similar_answer": (
        "Hallucinated Answer", "hallucinated_answer", "least_similar_answer",
    ),
    "knowledge": ("Knowledge", "knowledge"),
    "final_difficulty_level": (
        "Difficulty Level", "difficulty_level", "final_difficulty_level", "difficulty",
    ),
    "category": (
        "Category of Hallucination", "category_of_hallucination", "category",
    ),
}


def _parse_label(raw: Any) -> int:
    """Reproduce upstream ``calculate_metrics`` label parsing exactly.

    Upstream::

        i_lower = i.lower()
        if any(x in i_lower for x in ['1', 'not', 'non']):    -> 1
        elif any(x in i_lower for x in ['not sure', 'pass', 'skip', '2']): -> 2
        else:                                                 -> 0

    Order matters: the ``'1' / 'not' / 'non'`` branch wins before the
    ``'not sure'`` branch, so e.g. ``"not sure"`` parses to ``1`` upstream and
    we keep that (documented) artefact rather than "fixing" it.
    """
    i_lower = str(raw).lower()
    if any(x in i_lower for x in ("1", "not", "non")):
        return 1
    if any(x in i_lower for x in ("not sure", "pass", "skip", "2")):
        return 2
    return 0


def _knowledge_text(value: Any) -> str:
    """Normalise the ``Knowledge`` field (list[str] in the parquet release, or a
    stringified ``{'contexts': [...]}`` dict as the upstream script expected)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n\n".join(str(v) for v in value)
    text = str(value)
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    if isinstance(parsed, dict):
        ctx = parsed.get("contexts", parsed)
        if isinstance(ctx, (list, tuple)):
            return "\n\n".join(str(v) for v in ctx)
        return str(ctx)
    if isinstance(parsed, (list, tuple)):
        return "\n\n".join(str(v) for v in parsed)
    return text


class MedHalluAdapter(ExtAdapter):
    EXT_ID = "EXT-10"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P1",)

    def __init__(self, splits: Sequence[Tuple[str, str]] = _SPLITS):
        self.splits = tuple(splits)
        self._order: Optional[List[str]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._n_rows = 0

    # -- data --------------------------------------------------------------
    @staticmethod
    def _canonical(raw: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for canon, names in _COLS.items():
            for name in names:
                if name in raw and raw[name] is not None:
                    out[canon] = raw[name]
                    break
        return out

    def _ensure(self) -> List[str]:
        if self._order is not None:
            return self._order

        import pyarrow.parquet as pq

        order: List[str] = []
        for fname, split in self.splits:
            path = xc.require_path(
                os.path.join(_DATA, fname), f"MedHallu parquet {fname}"
            )
            table = pq.read_table(path)
            for i, raw in enumerate(table.to_pylist()):
                row = self._canonical(raw)
                self._n_rows += 1
                for cand, expected in _CANDIDATES:
                    tid = f"{split}/r{i:05d}/{cand}"
                    self._by_id[tid] = {
                        "row": row, "candidate": cand, "expected": expected,
                    }
                    order.append(tid)
        self._order = order
        return order

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        return list(self._ensure())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure()
        entry = self._by_id[task_id]
        row = entry["row"]
        answer = (row["ground_truth"] if entry["candidate"] == "ground_truth"
                  else row["least_similar_answer"])
        obs: Dict[str, Any] = {
            "question": row.get("question", ""),
            "answer": answer,
            "difficulty": row.get("final_difficulty_level", ""),
            # reference labels are the strings the upstream detector expects
            "reference_answer": str(entry["expected"]),
        }
        knowledge = _knowledge_text(row.get("knowledge"))
        if knowledge:
            obs["knowledge"] = knowledge
        if row.get("category"):
            obs["category"] = row["category"]
        return obs

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={
                "question": obs["question"],
                "answer": obs["answer"],
                "difficulty": obs["difficulty"],
                "has_knowledge": "knowledge" in obs,
            },
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic label accuracy, matching upstream ``calculate_metrics``.

        Upstream decides ``Correct`` iff the parsed prediction equals the known
        binary label (a ``2`` / "not sure" is never correct).  We replicate that
        per-record test; classification accuracy is therefore 1.0 for a correct
        record and 0.0 otherwise.
        """
        self._ensure()
        entry = self._by_id[record["source_task_id"]]
        expected = int(entry["expected"])
        text = (record.get("sut_output") or {}).get("text", "")
        got = _parse_label(text)
        correct = got == expected
        return {
            "ext_id": self.EXT_ID,
            "source_task_id": record["source_task_id"],
            "upstream_verdict": {
                "metric": "classification_accuracy",
                "correct": bool(correct),
                "expected": expected,
                "got": got,
            },
            "rescored": False,
        }

    def offline_probe(self):
        """Feed the correct label through the upstream parse+accuracy path."""
        order = self._ensure()
        if not order:
            return ("fail", "no tasks loaded")
        tid = order[0]
        entry = self._by_id[tid]
        expected = int(entry["expected"])
        rec = {
            "ext_id": self.EXT_ID,
            "source_task_id": tid,
            "sut_output": {"text": str(expected)},
        }
        v = self.score(rec)
        uv = v["upstream_verdict"]
        ok = uv["correct"] and uv["got"] == expected
        return (
            "ok" if ok else "fail",
            "upstream label parser + classification_accuracy exercised over "
            f"{self._n_rows} rows / {len(order)} (row,candidate) tasks from "
            f"{len(self.splits)} parquet split(s); label 0=factual, 1=hallucinated, 2=unsure",
        )
