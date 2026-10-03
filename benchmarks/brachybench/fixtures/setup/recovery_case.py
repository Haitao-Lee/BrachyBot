"""Setup script for robustness/recovery tasks (E, H).

A case with an in-flight plan and a receipt chain so idempotency and receipt
completeness can be checked.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

_BB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BB not in sys.path:
    sys.path.insert(0, _BB)
from fixtures import base_case  # noqa: E402


def build() -> Dict[str, Any]:
    s = base_case("recovery_case", dims=(24, 24, 24), spacing_mm=(1.0, 1.0, 1.0))
    s["plan"] = {
        "status": "ready",
        "trajectories": [{"id": "t1", "entry": [4.0, 4.0, 4.0], "dir": [0.0, 0.0, 1.0]}],
        "seeds": [{"id": "s1", "traj": "t1", "pos_mm": [4.0, 4.0, 8.0], "activity_u": 0.35}],
        "planning_version": 2,
        "receipts": [{"op_id": "op_seed_plan", "status": "completed", "hash": "a" * 64}],
    }
    return s
