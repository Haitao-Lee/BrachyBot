"""EXT adapter contract (DESIGN §25.5, appendix K).

One adapter per external benchmark.  Its only job is **protocol translation**:

* it must NOT modify the upstream repository (which lives read-only under
  ``external/<ext_id>/vendor/``);
* it must NOT implement its own scoring -- :meth:`ExtAdapter.score` calls the
  upstream evaluator verbatim;
* it must NOT relax a judgement for any particular SUT.

The uniform ``record`` it emits is what enters ``run_manifest`` and the
External Capability Anchors table.
"""

from __future__ import annotations

import json
import os
import copy
import functools
import hashlib
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from user_chat_contract import UserChatHandle, UserChatBlocked, evidence_errors

# DESIGN §25.9 -- the unified eight-state outcome
PARTIAL_STATUS = (
    "COMPLETED", "PARTIAL", "NEEDS_CLARIFICATION", "BLOCKED_BY_DEPENDENCY",
    "REFUSED_FOR_SAFETY", "FAILED_TOOL", "FAILED_VERIFICATION", "INFRA_FAILED",
)

# Public protocol fields, not a keyword denylist over medical contents.  A
# legitimate patient note/tool payload may itself contain words such as
# "expected" or "answer".  Neither those contents nor candidate answers in a
# hallucination-detection task are gold labels.  Unknown adapters keep the
# conservative legacy boundary until they declare their own public schema.
PUBLIC_INPUT_FIELDS = {
    "EXT-1": ("task_id", "task_type", "difficulty", "instruction"),
    "EXT-2": ("messages",),
    "EXT-3": ("task_id", "prompt"),
    "EXT-4": ("lang", "persona_id", "query_type", "history", "question"),
    "EXT-9": ("history", "question_date", "question"),
    "EXT-10": ("question", "answer", "difficulty", "knowledge"),
    "EXT-11": ("patient_note", "question", "calculator"),
    "EXT-12": ("task_id", "objective"),
    "EXT-13": ("case_str", "question_str"),
    "EXT-14": ("task_id", "title", "domain", "instructions", "input_payload", "expected_output_schema"),
    "EXT-15": ("dataset", "question", "options"),
}


def public_input(ext_id, value):
    fields = PUBLIC_INPUT_FIELDS.get(ext_id)
    if fields is not None:
        if not isinstance(value, dict):
            raise TypeError("external public observation must be an object")
        return {k: copy.deepcopy(value[k]) for k in fields if k in value}
    private = {"reference_answer", "reference_letter", "reference_content", "correct_answer",
               "correct_diagnosis", "gold", "ground_truth", "expected", "expect", "rubrics",
               "criteria", "criteria_booleans", "gradings", "ideal_completions_data",
               "binary_labels", "example_tags", "category"}
    if isinstance(value, dict):
        return {k: public_input(ext_id, v) for k, v in value.items() if k not in private}
    if isinstance(value, list):
        return [public_input(ext_id, v) for v in value]
    return copy.deepcopy(value)


class ExtAdapter:
    """Base class; each ``external/<ext_id>/adapter/adapter.py`` subclasses it."""

    EXT_ID: str = "EXT-?"
    #: DESIGN §25.1 -- kept here so a mismatch is visible at load time
    GRADE_R: str = "R0"
    GRADE_C: str = "C3"
    PANELS: Sequence[str] = ()

    def __init_subclass__(cls, **kwargs):
        """Enforce the same input boundary for every external adapter.

        Gold remains available to the upstream scorer, never to sut_handle.
        This wrapper measures elapsed time and preserves scorer-independent
        output fields without trusting self-reported judge gradings.
        """
        super().__init_subclass__(**kwargs)
        builder = cls.__dict__.get("build_input")
        if builder is not None and cls.EXT_ID != "EXT-REPLAY":
            @functools.wraps(builder)
            def build_public(self, task_id):
                return public_input(self.EXT_ID, builder(self, task_id))
            cls.build_input = build_public
        original = cls.__dict__.get("run_task")
        if original is None:
            return

        @functools.wraps(original)
        def bounded(self, task_id, sut_handle, budget):
            browser_chat = isinstance(sut_handle, UserChatHandle)
            component = (budget or {}).get("evaluation_mode") == "component_self_test" or self.EXT_ID == "EXT-REPLAY"
            if not component and not browser_chat:
                raise UserChatBlocked("formal external evaluation requires actual browser user input, not an arbitrary model callback")
            start = time.monotonic()
            captured = []
            def invoke(observation):
                limit = (budget or {}).get("wall_clock_s", 0)
                if limit > 0 and time.monotonic() - start >= limit:
                    raise TimeoutError("external task wall-clock budget exhausted before invocation")
                observation = public_input(self.EXT_ID, observation)
                if isinstance(observation, dict) and "task_id" in observation:
                    observation["task_id"] = hashlib.sha256(str(observation["task_id"]).encode()).hexdigest()[:24]
                result = sut_handle(observation) if callable(sut_handle) else {"text": ""}
                if not isinstance(result, dict):
                    raise TypeError("SUT output must be an object")
                captured.append(copy.deepcopy(result))
                return result

            record = original(self, task_id, invoke, budget)
            if self.EXT_ID == "EXT-REPLAY":
                # A frozen upstream record is a component test, not a fresh SUT invocation.
                record["evaluation_mode"] = "component_self_test"
                record["comparable_sut_result"] = False
                return record
            duration = time.monotonic() - start
            output = record.setdefault("sut_output", {})
            if captured:
                # These are measurements/candidate artifacts, not evaluator verdicts.
                for key in ("final_state", "artifacts", "response", "partial_status"):
                    if key in captured[-1]:
                        output[key] = captured[-1][key]
            output.pop("criteria_booleans", None)
            output.pop("gradings", None)
            derived = record.setdefault("derived", {})
            derived.update(wall_clock_s=duration, sut_calls=len(captured), tool_call_count=None,
                           reported_tool_calls=sum(len(r.get("trace") or []) for r in captured),
                           tool_budget_verified=False, protocol_fidelity="adapter_requires_upstream_validation")
            derived["partial_status"] = (captured[-1].get("partial_status", "PARTIAL")
                                          if captured else "BLOCKED_BY_DEPENDENCY")
            limit = (budget or {}).get("wall_clock_s", 0)
            if limit > 0 and duration > limit:
                derived["partial_status"] = "PARTIAL"
                derived["budget_exceeded"] = True
            if browser_chat:
                evidence = sut_handle.execution_evidence()
                evidence = {**evidence, "turns": evidence["turns"][-len(captured):] if captured else []}
                texts = sut_handle.submitted_texts[-len(captured):] if captured else []
                task = {"protocol": {"turns": [{"role": "user", "text": text} for text in texts]}}
                record["user_chat_execution"] = evidence
                record["entry_contract_errors"] = evidence_errors(evidence, task)
                record["evaluation_mode"] = "user_chat_adapted_not_fidelity_certified"
            else:
                record["evaluation_mode"] = "component_self_test"
            record["comparable_sut_result"] = False  # independent source-protocol certification still required
            return record

        cls.run_task = bounded

    # -- to implement ------------------------------------------------------
    def list_tasks(self) -> List[str]:
        """Upstream task ids, in a stable order."""
        raise NotImplementedError

    def build_input(self, task_id: str) -> Any:
        """Whatever the upstream runner needs (prompt / scene / workdir)."""
        raise NotImplementedError

    def run_task(self, task_id: str, sut_handle: Any, budget: Dict[str, int]) -> Dict[str, Any]:
        """Execute one task and return the uniform record."""
        raise NotImplementedError

    def score(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Call the **upstream** evaluator.  Never re-implement scoring."""
        raise NotImplementedError

    # -- uniform record ----------------------------------------------------
    @staticmethod
    def record(
        *,
        ext_id: str,
        source_task_id: str,
        prompt_or_scene: Any,
        sut_output: Optional[Dict[str, Any]] = None,
        upstream_verdict: Optional[Dict[str, Any]] = None,
        derived: Optional[Dict[str, Any]] = None,
        infra_failed: bool = False,
    ) -> Dict[str, Any]:
        d = {
            "tool_call_count": 0, "wall_clock_s": 0.0, "retries": 0,
            "partial_status": "COMPLETED",
            **(derived or {}),
        }
        if infra_failed:
            d["partial_status"] = "INFRA_FAILED"
        if d.get("partial_status") not in PARTIAL_STATUS:
            raise ValueError(f"partial_status must be one of {PARTIAL_STATUS}")
        return {
            "ext_id": ext_id,
            "source_task_id": source_task_id,
            "prompt_or_scene": prompt_or_scene,
            "sut_output": sut_output or {},
            "upstream_verdict": upstream_verdict or {},
            "derived": d,
            "infra_failed": bool(infra_failed),
        }

    # -- isolation (DESIGN §25.8) -----------------------------------------
    FORBIDDEN_WRITE_ROOTS = (
        "BrachyBot/session/", "BrachyBot/case/",
        "BrachyBot/runtime/", "BrachyBot/report/",
    )

    @classmethod
    def audit_isolation(cls, mtimes_before: Dict[str, float],
                        mtimes_after: Dict[str, float]) -> List[str]:
        """Return the forbidden roots whose mtime changed (empty == clean).

        DESIGN §25.8: finding any change **voids** the EXT run.
        """
        out = []
        for root in cls.FORBIDDEN_WRITE_ROOTS:
            b = mtimes_before.get(root)
            a = mtimes_after.get(root)
            if b is not None and a is not None and a != b:
                out.append(root)
        return out


class OfflineBundleAdapter(ExtAdapter):
    """DESIGN §12.1 ``offline_bundle`` -- for systems that cannot speak HTTP.

    Commercial TPS cannot implement an online SAA, but they can export DICOM
    RT.  This adapter consumes a ``bundle_out/`` directory and scores it with
    whatever the harness supplies (never with the vendor's own tools).
    """

    def load_bundle(self, out_dir: str) -> Dict[str, Any]:
        manifest = os.path.join(out_dir, "MANIFEST.sha256")
        files = {}
        for name in ("dose.nii.gz", "dose.dcm", "structures.dcm", "plan.dcm",
                     "guide.stl", "report.pdf", "report.json",
                     "final_state.json", "replies.json"):
            p = os.path.join(out_dir, name)
            if os.path.isfile(p):
                files[name] = p
        return {
            "out_dir": out_dir,
            "files": files,
            "has_manifest": os.path.isfile(manifest),
            "final_state": self._read_json(files.get("final_state.json")),
            "replies": self._read_json(files.get("replies.json")),
        }

    @staticmethod
    def _read_json(path: Optional[str]) -> Any:
        if not path:
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None
