"""Read-only saved-Session replay; never publishes a guide or writes its inputs.

Run baseline/current sequentially with the same saved snapshot. Only aggregate
timings, geometry/QA hashes and resource usage are written outside the Session.
"""
import argparse
import hashlib
import importlib.util
import json
import logging
import resource
import sys
import time
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Validation keys that only report grid/resolution bookkeeping. They were added
# after the frozen reference module was captured, so they are excluded from the
# equivalence hash to keep it comparable with the historical evidence. Any key
# that carries a geometry or QA value must NOT be listed here.
_ADDITIVE_METADATA_VALIDATION_KEYS = frozenset({
    "grid_budget",
    "requested_geometry_resolution_mm",
})


class Memory:
    def __init__(self, values):
        self.planning_results = values
        self.patient_data = {}
        self.ui_state = {}
        self._lock = RLock()

    def retrieve(self, key, default=None):
        return self.planning_results.get(key, default)

    def store(self, key, value, **kwargs):
        self.planning_results[key] = value


def fingerprint(value):
    def plain(v):
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, np.generic):
            return v.item()
        raise TypeError(type(v).__name__)
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=plain,
                                    separators=(",", ":")).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=["baseline", "current"], required=True)
    parser.add_argument("--resolution-mm", type=float,
                        help="Detached validation only: use the same explicit resolution on both sides")
    parser.add_argument("--snapshot-file", type=Path,
                        help="Read a frozen snapshot manifest while resolving artifacts in --workspace")
    args = parser.parse_args()
    root = args.workspace.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(root) or output.exists():
        parser.error("Output must be new and outside the source Session")
    logging.basicConfig(level=logging.INFO)
    from web import surgical_guide as guide
    from scripts.guide_latency_reference_guard import verify_reference
    reference_manifest = verify_reference()
    from web.workspace_store import WorkspaceStore, _decode_artifacts
    if args.variant == "baseline":
        path = REPO / "tests/data/surgical_guide_latency_reference.py"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == "dad562e79d2036fb836c2656f487658bf3344675bd09f8bf08186b839f1f06ff"
        spec = importlib.util.spec_from_file_location("guide_latency_frozen", path)
        guide = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = guide
        spec.loader.exec_module(guide)
    started = time.perf_counter()
    source = (args.snapshot_file or (root / "snapshot.json")).read_bytes()
    snapshot = json.loads(source)
    raw = snapshot["agent"]["planning_results"]
    keys = ["ct_path", "algorithm_plan_snapshot", "seed_plan_serialized",
            "verified_needle_geometry", "manual_seeds", "manual_needles",
            "manual_plan_version", "manual_planning_id", "active_planning_id",
            "planning_run_id", "planning_runs", "skin_surface", "surgical_guide",
            "surgical_guide_versions"]
    # Old guide meshes are irrelevant inputs; preserve metadata/version only.
    values = {}
    for key in keys:
        if key not in raw:
            continue
        value = raw[key]
        if key == "surgical_guide":
            value = {k: v for k, v in value.items() if k not in ("vertices", "faces", "stl")}
        elif key == "surgical_guide_versions":
            value = [{k: v for k, v in item.items() if k not in ("vertices", "faces", "stl")} for item in value]
        values[key] = _decode_artifacts(value, root)
    agent = SimpleNamespace(memory=Memory(values))
    WorkspaceStore._hydrate_ct_image(root, agent.memory)
    ct = agent.memory.retrieve("ct_data")
    assert ct is not None, "CT hydration failed"
    params = dict((values.get("surgical_guide") or {}).get("parameters") or {})
    if args.resolution_mm is not None:
        params["geometry_resolution_mm"] = args.resolution_mm
    loaded = time.perf_counter()
    summary = {"variant": args.variant, "snapshot_sha256": hashlib.sha256(source).hexdigest(),
               "reference_manifest": reference_manifest,
               "ct_sha256": hashlib.sha256(np.ascontiguousarray(ct).view(np.uint8)).hexdigest(),
               "parameters": guide.normalize_guide_parameters(params),
               "planning_signature": guide.planning_signature(guide._current_planning_snapshot(agent)),
               "load_seconds": loaded - started}
    try:
        result = guide.generate_surgical_guide(agent, params)
        summary["success"] = True
        validation = dict(result["validation"])
        summary["stages"] = validation.pop("stage_timings_seconds", {})
        summary["hashes"] = {k: fingerprint(result[k]) for k in ("vertices", "faces", "needle_paths", "auxiliary_holes")}
        summary["hashes"]["validation_without_timing"] = fingerprint({
            k: v for k, v in validation.items() if k not in _ADDITIVE_METADATA_VALIDATION_KEYS
        })
        summary["additive_metadata_keys"] = sorted(
            set(validation) & _ADDITIVE_METADATA_VALIDATION_KEYS
        )
        summary["validation"] = validation
        summary["selected_needle_count"] = len(result["selected_needle_ids"])
    except Exception as exc:
        logging.exception("Detached guide replay failed")
        summary.update(success=False, error=str(exc), error_type=type(exc).__name__)
    summary["generation_seconds"] = time.perf_counter() - loaded
    summary["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        json.dump(summary, handle, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != "validation"}, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
