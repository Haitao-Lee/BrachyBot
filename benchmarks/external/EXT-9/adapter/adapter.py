"""EXT-9 · LongMemEval adapter (DESIGN §25.3.9, §25.5).

Data: the HF ``xiaowu0162/longmemeval-cleaned`` release, materialised under
``external/EXT-9/data/`` by ``fetch_all.sh``:

* ``longmemeval_oracle.json`` -- 500 questions with only the evidence sessions
  in the history (this is the adapter's task set), and
* ``longmemeval_s_cleaned.json`` -- the full ~115k-token session histories.

Protocol translation only.  The upstream tree (``vendor/``) is read-only.  Its
official evaluator ``src/evaluation/evaluate_qa.py`` is an **LLM judge**: for
every hypothesis it asks a judge model (OpenAI ``gpt-4o``/``gpt-4o-mini`` or a
local vLLM OpenAI-compatible server) whether the response contains the reference
answer.  There is no deterministic QA scorer upstream, so :meth:`score` raises
``UpstreamUnavailable`` offline rather than inventing one.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ext_common as xc
from adapter_base import ExtAdapter

_DATA = os.path.join(xc.data_dir("EXT-9"))
_ORACLE = os.path.join(_DATA, "longmemeval_oracle.json")
_S_CLEANED = os.path.join(_DATA, "longmemeval_s_cleaned.json")


def _load_anscheck_prompt():
    """Import the upstream ``get_anscheck_prompt`` (lazy; needs ``backoff``).

    ``evaluate_qa.py`` imports ``backoff`` / ``openai`` / ``tqdm`` at module
    scope even though the prompt builder is pure.  We register a tiny
    ``backoff`` shim only if it is genuinely absent so the vendored module can
    be imported without paying for (or installing) the network stack.
    """
    import importlib
    import sys
    import types

    if "backoff" not in sys.modules:
        try:
            import backoff  # noqa: F401
        except Exception:  # noqa: BLE001
            shim = types.ModuleType("backoff")

            def _on_exception(*_a, **_k):
                def _decorate(fn):
                    return fn

                return _decorate

            shim.on_exception = _on_exception  # type: ignore[attr-defined]
            shim.expo = lambda *_a, **_k: None  # type: ignore[attr-defined]
            shim.constant = lambda *_a, **_k: None  # type: ignore[attr-defined]
            sys.modules["backoff"] = shim

    src_eval = os.path.join(xc.vendor_dir("EXT-9"), "src", "evaluation")
    xc.ensure_vendor_package("ext9_eval", src_eval)
    mod = importlib.import_module("ext9_eval.evaluate_qa")
    return mod.get_anscheck_prompt


class LongMemEvalAdapter(ExtAdapter):
    EXT_ID = "EXT-9"
    GRADE_R = "R0"
    GRADE_C = "C2"
    PANELS = ("P6",)

    def __init__(self, data_file: str = _ORACLE):
        self.path = data_file
        self._entries: Optional[List[Dict[str, Any]]] = None
        self._by_id: Dict[str, Dict[str, Any]] = {}

    # -- data --------------------------------------------------------------
    def _ensure(self) -> List[Dict[str, Any]]:
        if self._entries is None:
            xc.require_path(self.path, "LongMemEval oracle json")
            rows = xc.read_json(self.path)
            if not isinstance(rows, list):
                raise xc.DatasetUnavailable(f"unexpected LongMemEval payload at {self.path}")
            self._entries = rows
            for i, row in enumerate(rows):
                tid = row.get("question_id") or f"row-{i:05d}"
                self._by_id[tid] = row
        return self._entries

    #: the full LongMemEval_S release (not the task set) is available too;
    #: exposed for callers that want the unpruned haystack.
    @property
    def full_history_path(self) -> str:
        return _S_CLEANED

    def _render_history(self, entry: Dict[str, Any]) -> str:
        dates = entry.get("haystack_dates") or []
        sessions = entry.get("haystack_sessions") or []
        blocks: List[str] = []
        for i, sess in enumerate(sessions):
            date = dates[i] if i < len(dates) else "unknown date"
            sid = ""
            sids = entry.get("haystack_session_ids") or []
            if i < len(sids):
                sid = f" {sids[i]}"
            lines = [f"[session {i + 1}{sid} | {date}]"]
            if isinstance(sess, str):
                lines.append(sess)
            else:
                for turn in sess:
                    role = turn.get("role", "?") if isinstance(turn, dict) else "?"
                    content = turn.get("content", "") if isinstance(turn, dict) else str(turn)
                    lines.append(f"{role}: {content}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # -- contract ----------------------------------------------------------
    def list_tasks(self) -> List[str]:
        self._ensure()
        return list(self._by_id.keys())

    def build_input(self, task_id: str) -> Dict[str, Any]:
        self._ensure()
        entry = self._by_id[task_id]
        return {
            "history": self._render_history(entry),
            "question_date": entry.get("question_date", ""),
            "question": entry.get("question", ""),
            "reference_answer": entry.get("answer", ""),
        }

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        obs = self.build_input(task_id)
        out = sut_handle(obs) if callable(sut_handle) else {"text": ""}
        return self.record(
            ext_id=self.EXT_ID,
            source_task_id=task_id,
            prompt_or_scene={"question": obs["question"],
                             "question_date": obs["question_date"],
                             "history_chars": len(obs["history"])},
            sut_output={"text": out.get("text", ""), "trace": out.get("trace", [])},
            derived={"tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
                     "partial_status": "COMPLETED"},
        )

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise xc.UpstreamUnavailable(
            "LongMemEval has no deterministic QA scorer: the official evaluator "
            "src/evaluation/evaluate_qa.py labels every hypothesis with an LLM "
            "judge (OpenAI gpt-4o/gpt-4o-mini via OPENAI_API_KEY, or a local "
            "vLLM OpenAI-compatible server at http://localhost:8001/v1). "
            "Neither is available offline, so QA scoring is BLOCKED."
        )

    def offline_probe(self):
        """Certify data + prompt construction; QA scoring needs the judge."""
        entries = self._ensure()
        if not entries:
            return ("fail", "no LongMemEval questions loaded")
        tid = next(iter(self._by_id))
        entry = self._by_id[tid]
        obs = self.build_input(tid)
        if not obs["history"] or not obs["question"]:
            return ("fail", f"empty prompt materialised for {tid}")

        upstream = "not exercised"
        try:
            prompt_fn = _load_anscheck_prompt()
            up = prompt_fn(
                entry.get("question_type", ""),
                obs["question"],
                entry.get("answer", ""),
                "e0 offline response",
                abstention="_abs" in tid,
            )
            if up:
                upstream = f"upstream get_anscheck_prompt built ({len(up)} chars)"
        except Exception as exc:  # noqa: BLE001
            upstream = f"upstream get_anscheck_prompt import skipped ({exc})"

        detail = (
            f"oracle loaded ({len(entries)} questions); timestamped history + "
            f"question rendered for {tid} ({len(obs['history'])} chars); "
            f"{upstream}. QA scoring requires the upstream LLM judge "
            "(src/evaluation/evaluate_qa.py; OPENAI_API_KEY or local vLLM at "
            "http://localhost:8001/v1) -- BLOCKED offline."
        )
        return ("blocked", detail)
