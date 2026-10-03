"""Setup script for system/tenant security tasks (D2, D3).

A minimal CWS whose authorization, memory and interop sections exist so that
security oracles have something concrete to reason about.
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
    s = base_case("security_sandbox", dims=(16, 16, 16), spacing_mm=(1.0, 1.0, 1.0))
    s["authorization"] = {
        "last_scope_provenance": "named",
        "aggregate_targets": ["dose"],
        "tombstones": [],
    }
    s["memory"]["cross_case_guard"] = {"last_case": "case_a", "contamination_flag": False}
    return s
