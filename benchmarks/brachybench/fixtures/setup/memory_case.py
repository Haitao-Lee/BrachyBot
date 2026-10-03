"""Setup script for memory / self-evolution tasks (K).

Carries the memory section so retrieval-contamination can be evaluated.
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
    s = base_case("memory_case", dims=(16, 16, 16), spacing_mm=(1.0, 1.0, 1.0))
    s["memory"] = {
        "retrieved_ids": ["mem_own_1"],
        "written_ids": [],
        "cross_case_guard": {"last_case": "case_self", "contamination_flag": False},
        "skills": {"crystallized": [], "version": 1},
    }
    return s
