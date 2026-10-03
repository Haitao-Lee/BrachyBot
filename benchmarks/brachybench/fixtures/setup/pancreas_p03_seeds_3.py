"""Setup script for ``phantom/pancreas_p03`` with three seeds (A3b-DOSE-002).

Same geometry as ``pancreas_p03_pipeline`` but the plan is final with three
seeds so that the dose-additivity and metric-provenance assertions have real
per-seed contributions to work with.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

_BB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BB not in sys.path:
    sys.path.insert(0, _BB)
from fixtures import base_case, hash_cws  # noqa: E402

SEED_IDS = ["s1", "s2", "s3"]


def build() -> Dict[str, Any]:
    s = base_case("pancreas_p03", dims=(48, 512, 512), spacing_mm=(0.68, 0.68, 5.0))
    s["segmentation"] = {
        "ctv_pancreas": {"present": True, "volume_mm3": 27849.0, "label_id": 3},
        "oar_duodenum": {"present": True, "volume_mm3": 41022.5, "label_id": 11},
    }
    s["plan"].update(
        {
            "status": "final",
            "trajectories": [
                {"id": "t1", "entry": [18.0, 30.0, 24.0], "dir": [0.0, 0.0, 1.0], "clearance_mm": 4.6},
                {"id": "t2", "entry": [30.0, 30.0, 24.0], "dir": [0.0, 0.0, 1.0], "clearance_mm": 5.1},
            ],
            "seeds": [
                {"id": "s1", "traj": "t1", "pos_mm": [18.0, 30.0, 30.0], "activity_u": 0.35},
                {"id": "s2", "traj": "t1", "pos_mm": [18.0, 30.0, 38.0], "activity_u": 0.35},
                {"id": "s3", "traj": "t2", "pos_mm": [30.0, 30.0, 34.0], "activity_u": 0.35},
            ],
            "planning_version": 5,
            "receipts": [
                {"op_id": "op_seed_plan", "status": "completed", "hash": "d" * 64},
            ],
        }
    )
    s["dose"].update(
        {
            "computed": False,
            "per_seed_contributions_available": True,
            "metrics": {},
        }
    )
    s["ui"].update(
        {
            "opacity": {"dose": 0.6, "structure": 1.0},
            "visibility": {"ctv_pancreas": True},
            "version_fence": {"state_seq": 55, "plan_revision": 5},
        }
    )
    return s


if __name__ == "__main__":
    st = build()
    print(hash_cws(st))
