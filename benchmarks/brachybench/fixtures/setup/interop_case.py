"""Setup script for data-interoperability tasks (L).

Carries the interop section so export/round-trip checks have a home.
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
    s = base_case("interop_case", dims=(16, 16, 16), spacing_mm=(1.0, 1.0, 1.0))
    s["interop"] = {
        "last_export": {"format": "nifti", "roundtrip_ok": True},
        "last_import": {},
    }
    return s
