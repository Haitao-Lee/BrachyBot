"""Setup script for ``phantom/pancreas_p03`` (task B-UI-014).

A loaded CT plus segmentation and a *draft* plan: the dual-path UI opacity
task needs a stable base state whose ``ui.opacity.dose`` starts at 1.0 so a
write to 0.30 is observable.
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
    s = base_case("pancreas_p03", dims=(48, 512, 512), spacing_mm=(0.68, 0.68, 5.0))
    s["segmentation"] = {
        "ctv_pancreas": {"present": True, "volume_mm3": 27849.0, "label_id": 3},
        "oar_duodenum": {"present": True, "volume_mm3": 41022.5, "label_id": 11},
    }
    s["plan"].update(
        {
            "status": "draft",
            "trajectories": [{"id": "t1", "entry": [18.0, 30.0, 24.0], "dir": [0.0, 0.0, 1.0], "clearance_mm": 4.6}],
            "seeds": [],
            "planning_version": 3,
            "receipts": [{"op_id": "op_traj", "status": "completed", "hash": "c" * 64}],
        }
    )
    s["ui"].update(
        {
            "opacity": {"dose": 1.0, "structure": 1.0},
            "visibility": {"ctv_pancreas": True, "oar_duodenum": True},
            "version_fence": {"state_seq": 42, "plan_revision": 3},
        }
    )
    return s


if __name__ == "__main__":
    st = build()
    print(hash_cws(st))
