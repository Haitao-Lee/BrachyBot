"""EXT adapter contract tests (DESIGN §25.5, §25.8).

Uses the reference replay adapter: it proves the adapter lifecycle without a
vendor checkout, and that scoring is passed through verbatim.
"""

from __future__ import annotations

import json
import os
import sys

BB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BB)
EXT = os.path.abspath(os.path.join(BB, "..", "external"))
sys.path.insert(0, EXT)

from replay_adapter import ReplayExtAdapter  # noqa: E402


def _write_record(directory, task_id):
    rec = {
        "ext_id": "EXT-REPLAY",
        "source_task_id": task_id,
        "prompt_or_scene": {"q": "what is the D90?"},
        "sut_output": {"answer": "145.8 Gy"},
        "upstream_verdict": {"score": 1.0, "rubric": "upstream"},
        "derived": {"tool_call_count": 3, "partial_status": "COMPLETED"},
    }
    path = os.path.join(directory, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    return rec


def test_ext_adapter_lifecycle_and_verbatim_scoring(tmp_path):
    d = str(tmp_path)
    _write_record(d, "t1")
    _write_record(d, "t2")
    adapter = ReplayExtAdapter(d)

    assert adapter.list_tasks() == ["t1", "t2"]
    assert adapter.build_input("t1") == {"q": "what is the D90?"}

    rec = adapter.run_task("t1", sut_handle=None, budget={})
    assert rec["ext_id"] == "EXT-REPLAY"
    assert rec["derived"]["partial_status"] == "COMPLETED"

    verdict = adapter.score(rec)
    assert verdict["rescored"] is False
    assert verdict["upstream_verdict"] == {"score": 1.0, "rubric": "upstream"}


def test_ext_adapter_isolation_audit_flags_forbidden_write():
    before = {"BrachyBot/case/": 1.0, "benchmarks/external/x/results/": 1.0}
    after = {"BrachyBot/case/": 2.0, "benchmarks/external/x/results/": 1.0}
    assert ReplayExtAdapter.audit_isolation(before, after) == ["BrachyBot/case/"]
    assert ReplayExtAdapter.audit_isolation(before, before) == []


def test_ext_record_rejects_bad_partial_status():
    import pytest

    with pytest.raises(ValueError):
        ReplayExtAdapter.record(
            ext_id="EXT-REPLAY", source_task_id="t", prompt_or_scene="p",
            derived={"partial_status": "NOT_A_REAL_STATE"},
        )
