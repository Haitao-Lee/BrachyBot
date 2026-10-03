"""Fixture builders (BA-15).

Seed tasks used to point at non-existent ``setup_script`` paths and carry
placeholder ``initial_state_hash`` values, so they were schema skeletons, not
runnable tasks.  This package supplies real, deterministic fixtures:

* :func:`canonical_json` -- stable serialisation (sorted keys, no whitespace
  noise) used for hashing;
* :func:`hash_cws` -- ``sha256:...`` over the canonical form;
* one builder per ``case_family`` in ``fixtures/setup/``.

Hashes in ``tasks/*.json`` are recomputed by ``tools/build_fixtures.py`` and
checked by the test suite, so a fixture change cannot silently drift away
from the frozen ``initial_state_hash``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def canonical_json(state: Dict[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_cws(state: Dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


_IDENTITY_LPS = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def base_case(case_id: str, *, dims, spacing_mm, origin=None) -> Dict[str, Any]:
    return {
        "cws_version": "1.0",
        "case": {
            "id": case_id,
            "ct": {
                "loaded": True,
                "dims": list(dims),
                "spacing_mm": list(spacing_mm),
                "origin": list(origin or [0.0, 0.0, 0.0]),
                "direction_lps": list(_IDENTITY_LPS),
                "hu_stats": {"p05": -980.0, "p95": 220.0},
            },
        },
        "segmentation": {},
        "plan": {"status": "none", "trajectories": [], "seeds": [], "planning_version": 0, "receipts": []},
        "dose": {
            "engine": "cnn_dose_engine@DoseUNet",
            "engine_weight_sha256": "0" * 64,
            "computed": False,
            "per_seed_contributions_available": False,
            "metrics": {},
            "constraints_checked": [],
        },
        "ui": {"opacity": {"dose": 1.0, "structure": 1.0}, "visibility": {}, "version_fence": {"state_seq": 0, "plan_revision": 0}},
        "report": {"status": "empty", "sections": [], "language": "zh"},
        "guide": {"status": "none", "holes": 0, "geometry": [], "interference": {"risk": "none", "clearance_basis": "interior"}},
        "authorization": {"last_scope_provenance": "none", "aggregate_targets": [], "tombstones": []},
        "memory": {"retrieved_ids": [], "written_ids": [], "cross_case_guard": {"last_case": None, "contamination_flag": False}, "skills": {"crystallized": [], "version": 0}},
        "monitor": {"active_advice": None, "training_loop": {"open": False}},
        "interop": {"last_export": {}, "last_import": {}},
    }
