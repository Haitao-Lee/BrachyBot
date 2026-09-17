"""Validate paired replay evidence and emit de-identified aggregate results."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", nargs=3, action="append", metavar=("LABEL", "BASELINE", "CURRENT"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for label, old, new in args.pair:
        a, b = [json.loads(Path(p).read_text()) for p in [old, new]]
        assert a["success"] and b["success"], f"Generation failed: {label}"
        for key in ("snapshot_sha256", "ct_sha256", "parameters", "planning_signature", "hashes"):
            assert a[key] == b[key], f"Paired evidence differs: {label}/{key}"
        before, after = a["stages"]["total"], b["stages"]["total"]
        records.append({
            "label": label,
            "needle_count": b["selected_needle_count"],
            "resolution_mm": b["parameters"]["geometry_resolution_mm"],
            "inputs_match": True, "output_hashes_match": True,
            "hashes": b["hashes"],
            "baseline_stages_seconds": a["stages"], "current_stages_seconds": b["stages"],
            "speedup": before / after,
            "baseline_peak_rss_gib": a["peak_rss_kib"] / 1024**2,
            "current_peak_rss_gib": b["peak_rss_kib"] / 1024**2,
            "vertex_count": b["validation"]["vertex_count"],
            "face_count": b["validation"]["face_count"],
            "watertight": b["validation"]["watertight"],
            "topology_repair_attempted": b["validation"]["mesh_repair"]["attempted"],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump({"scope": "Detached generator replay; not browser/checkpoint latency; single measurements on shared host",
                   "pairs": records}, handle, indent=2)
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
