#!/usr/bin/env python3
"""E0 minimal smoke gate for the EXT track (DESIGN §25.6).

For each benchmark it exercises the adapter lifecycle offline with a NullSUT
(build_input -> run_task) and asks the adapter to certify its scoring path via
``offline_probe``.  It never spends money and never touches gated data.

Verdicts (DESIGN §25.6): PASS / FAIL / BLOCKED / LICENSE_REQUIRED / INFRA_FAILED.
E0 is NOT a benchmark score.  Results are written to
``external/<ext_id>/results/e0_smoke.json``.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ext_common as xc  # noqa: E402

SMOKE_N = 5


def run_one(ext_id: str) -> dict:
    result = {"ext_id": ext_id, "stages": {}, "verdict": "FAIL", "detail": "",
              "evaluation_mode": "component_self_test", "comparable_sut_result": False,
              "protocol_fidelity_certified": False}
    try:
        adapter = xc.load_adapter(ext_id)
    except Exception as exc:  # adapter import failure == harness bug
        result["stages"]["load_adapter"] = f"FAIL: {exc}"
        result["verdict"] = "FAIL"
        result["detail"] = f"adapter import failed: {exc}"
        return result

    # 1) list tasks
    try:
        tasks = adapter.list_tasks()
        result["stages"]["list_tasks"] = f"OK: {len(tasks)} tasks"
    except xc.DatasetUnavailable as exc:
        result["stages"]["list_tasks"] = f"BLOCKED: {exc}"
        result["verdict"] = "BLOCKED"
        result["detail"] = str(exc)
        return result
    except xc.UpstreamUnavailable as exc:
        result["stages"]["list_tasks"] = f"BLOCKED: {exc}"
        result["verdict"] = "BLOCKED"
        return result
    except Exception as exc:
        result["stages"]["list_tasks"] = f"FAIL: {exc}"
        return result

    if not tasks:
        result["stages"]["list_tasks"] = "FAIL: empty task list"
        return result

    # 2) build_input for a few
    try:
        for tid in tasks[:SMOKE_N]:
            obs = adapter.build_input(tid)
            assert obs, "empty observation"
        result["stages"]["build_input"] = f"OK: {min(SMOKE_N, len(tasks))} observations"
    except Exception as exc:
        result["stages"]["build_input"] = f"FAIL: {exc}"
        return result

    # 3) run_task with the reference SUT
    try:
        sut = xc.NullSUT()
        rec = adapter.run_task(tasks[0], sut, {"wall_clock_s": 60, "turns": 5, "tool_calls": 10,
                                             "evaluation_mode": "component_self_test"})
        assert rec.get("ext_id") == ext_id, "record ext_id mismatch"
        status = rec["derived"]["partial_status"]
        result["stages"]["run_task"] = f"OK: partial_status={status}"
    except xc.UpstreamUnavailable as exc:
        result["stages"]["run_task"] = f"BLOCKED: {exc}"
        result["verdict"] = "BLOCKED"
        result["detail"] = str(exc)
        return result
    except Exception as exc:
        result["stages"]["run_task"] = f"FAIL: {exc}"
        return result

    # 4) scoring path certificate
    try:
        probe_status, probe_detail = adapter.offline_probe()
    except xc.UpstreamUnavailable as exc:
        probe_status, probe_detail = "blocked", str(exc)
    except Exception as exc:
        result["stages"]["score_probe"] = f"FAIL: {exc}"
        result["detail"] = traceback.format_exc(limit=2)
        return result

    if probe_status == "ok":
        result["stages"]["score_probe"] = f"OK: {probe_detail}"
        result["verdict"] = "PASS"
    elif probe_status == "blocked":
        result["stages"]["score_probe"] = f"BLOCKED: {probe_detail}"
        result["verdict"] = "BLOCKED"
    else:
        result["stages"]["score_probe"] = f"FAIL: {probe_detail}"
        result["verdict"] = "FAIL"
    result["detail"] = probe_detail
    return result


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    ids = argv or ["EXT-1", "EXT-2", "EXT-3", "EXT-4",
                   "EXT-9", "EXT-10", "EXT-11", "EXT-12", "EXT-13",
                   "EXT-14", "EXT-15"]
    summary = []
    for ext_id in ids:
        res = run_one(ext_id)
        summary.append(res)
        out = os.path.join(xc.results_dir(ext_id), "e0_smoke.json")
        xc.write_json(out, res)
        mark = {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCK",
                "LICENSE_REQUIRED": "LIC ", "INFRA_FAILED": "INF "}.get(res["verdict"], "????")
        print(f"[{mark}] {ext_id}  " + " | ".join(f"{k}={v}" for k, v in res["stages"].items()))
    xc.write_json(os.path.join(HERE, "results", "e0_summary.json"),
                  {"results": summary})
    fails = [r for r in summary if r["verdict"] == "FAIL"]
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
