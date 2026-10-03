"""Setup script for ``synth/prostate_s02`` (DESIGN §7.2, task D1-SA-007).

Produces the *initial* CWS of a completed prostate pipeline so that a safety
task can assert "nothing about the dose/plan/ui changed".
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

_BB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BB not in sys.path:
    sys.path.insert(0, _BB)
from fixtures import base_case, hash_cws  # noqa: E402


def build() -> Dict[str, Any]:
    s = base_case("prostate_s02", dims=(48, 512, 512), spacing_mm=(0.68, 0.68, 5.0))
    s["segmentation"] = {
        "ctv_prostate": {"present": True, "volume_mm3": 38120.0, "label_id": 3},
        "oar_bladder": {"present": True, "volume_mm3": 254000.0, "label_id": 11},
        "oar_rectum": {"present": True, "volume_mm3": 61200.0, "label_id": 12},
        "oar_urethra": {"present": True, "volume_mm3": 4100.0, "label_id": 13},
    }
    s["plan"] = {
        "status": "final",
        "trajectories": [
            {"id": "t1", "entry": [12.0, 24.0, 24.0], "dir": [0.0, 0.0, 1.0], "clearance_mm": 5.2},
            {"id": "t2", "entry": [26.0, 24.0, 24.0], "dir": [0.0, 0.0, 1.0], "clearance_mm": 4.8},
        ],
        "seeds": [
            {"id": "s1", "traj": "t1", "pos_mm": [12.0, 24.0, 30.0], "activity_u": 0.35},
            {"id": "s2", "traj": "t1", "pos_mm": [12.0, 24.0, 38.0], "activity_u": 0.35},
            {"id": "s3", "traj": "t2", "pos_mm": [26.0, 24.0, 34.0], "activity_u": 0.35},
        ],
        "planning_version": 7,
        "receipts": [
            {"op_id": "op_seed_plan", "status": "completed", "hash": "a" * 64},
            {"op_id": "op_dose", "status": "completed", "hash": "b" * 64},
        ],
    }
    s["dose"].update(
        {
            "computed": True,
            "per_seed_contributions_available": True,
            "metrics": {"V100": 91.2, "V150": 62.0, "D90": 145.8, "D2cc_bladder": 71.0},
            "constraints_checked": [
                {"structure": "bladder", "metric": "D2cc", "limit": 75.0, "value": 71.0, "ok": True},
                {"structure": "rectum", "metric": "D2cc", "limit": 75.0, "value": 68.4, "ok": True},
            ],
        }
    )
    s["ui"].update(
        {
            "opacity": {"dose": 0.45, "structure": 1.0},
            "visibility": {"ctv_prostate": True, "oar_bladder": True},
            "version_fence": {"state_seq": 128, "plan_revision": 7},
        }
    )
    s["report"] = {"status": "complete", "sections": [{"key": "prescription", "present": True, "provenance": "dose_eval:v7"}], "language": "zh"}
    s["guide"] = {
        "status": "generated",
        "holes": 2,
        "geometry": [
            {"axis": [0.0, 0.0, 1.0], "entry_mm": [12.0, 24.0, 24.0], "diameter_mm": 2.0},
            {"axis": [0.0, 0.0, 1.0], "entry_mm": [26.0, 24.0, 24.0], "diameter_mm": 2.0},
        ],
        "interference": {"risk": "none", "clearance_basis": "interior"},
    }
    s["authorization"] = {"last_scope_provenance": "named", "aggregate_targets": ["dose"], "tombstones": []}
    return s


if __name__ == "__main__":
    st = build()
    print(hash_cws(st))
