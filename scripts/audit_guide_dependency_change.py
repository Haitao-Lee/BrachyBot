"""Detached, synthetic pre/post dependency replay; never touches a real case.

Run each dependency variant in a fresh subprocess. The pre-patch pipeline file
is explicitly loaded, so importing the same current dependency on both sides
cannot produce a false equivalence result. Timings are descriptive, not a
clinical-case/browser latency claim or an optimization significance test.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_function_digest(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_canonical_needle_points_from_seeds")
    return hashlib.sha256(ast.dump(function, include_attributes=False).encode()).hexdigest()


def worker(pipeline, count, resolution):
    import numpy as np
    import SimpleITK as sitk
    import tool_factory.seed_plan
    module_name = "tool_factory.seed_plan.planning_pipeline"
    spec = importlib.util.spec_from_file_location(module_name, pipeline)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    from web import surgical_guide

    class Memory:
        def __init__(self, values):
            self.values = values

        def retrieve(self, key):
            return self.values.get(key)

        def store(self, key, value):
            self.values[key] = value

    shape = (64, 64, 64)
    zz, yy, xx = np.indices(shape)
    ct = np.where((xx - 32)**2 + (yy - 32)**2 + (zz - 32)**2 <= 22**2, 40, -1000).astype(np.int16)
    image = sitk.GetImageFromArray(ct)
    if count == 4:
        angle = .31
        image.SetOrigin((-17., 24., -63.))
        image.SetSpacing((.8, 1.1, 1.4))
        image.SetDirection((np.cos(angle), -np.sin(angle), 0., np.sin(angle), np.cos(angle), 0., 0., 0., 1.))
    offsets = [(32, 32)] if count == 1 else [(26, 26), (26, 38), (38, 26), (38, 38)]
    needles, seeds = [], []
    for i, (y, z) in enumerate(offsets):
        world = lambda x: list(image.TransformContinuousIndexToPhysicalPoint((float(x), float(y), float(z))))
        needles.append({"id": f"needle_{i}", "trajectory_id": f"traj_{i}", "points": [world(32), world(-10)]})
        seeds.append({"id": f"seed_{i}", "trajectory_id": f"traj_{i}", "position": world(28)})
    snapshot = {"needles": needles, "seeds": seeds}
    agent = SimpleNamespace(memory=Memory({"ct_image": image, "ct_data": ct, "algorithm_plan_snapshot": snapshot}))
    start = time.perf_counter()
    result = surgical_guide.generate_surgical_guide(agent, {"geometry_resolution_mm": resolution})
    elapsed = time.perf_counter() - start
    def plain(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError(type(value).__name__)
    def fingerprint(value):
        return hashlib.sha256(json.dumps(value, default=plain, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    validation = {k: v for k, v in result["validation"].items() if k != "stage_timings_seconds"}
    return {"dependency_sha256": digest(pipeline), "seconds": elapsed,
            "input_sha256": fingerprint({"ct_sha256": hashlib.sha256(ct.tobytes()).hexdigest(),
                                          "spacing": image.GetSpacing(), "origin": image.GetOrigin(),
                                          "direction": image.GetDirection(), "snapshot": snapshot,
                                          "resolution_mm": resolution}),
            "hashes": {key: fingerprint(result[key]) for key in ("vertices", "faces", "needle_paths", "auxiliary_holes")},
            "qa_sha256": fingerprint(validation), "watertight": validation.get("watertight"),
            "selected_needle_count": len(result["selected_needle_ids"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--count", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--resolution", type=float, default=.5, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.before.resolve(strict=True), args.count, args.resolution)))
        return 0
    if args.output is None or args.output.exists():
        parser.error("--output must be a new evidence file")
    before = args.before.resolve(strict=True)
    current = REPO / "tool_factory/seed_plan/planning_pipeline.py"
    pairs = []
    for count, resolution in ((1, .2), (4, .5)):
        for repeat in range(2):
            observations = []
            # Alternate order to avoid confounding every current run with warm
            # filesystem caches. Each subprocess still has a cold in-memory cache.
            order = (before, current) if repeat == 0 else (current, before)
            for path in order:
                process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--before", str(path),
                                          "--count", str(count), "--resolution", str(resolution)],
                                         cwd=REPO, capture_output=True, text=True, timeout=180)
                if process.returncode:
                    raise RuntimeError("Synthetic guide replay failed; inspect detached worker diagnostics")
                observations.append(json.loads(process.stdout.strip().splitlines()[-1]))
            old, new = observations if repeat == 0 else observations[::-1]
            matched = all(old[key] == new[key] for key in ("input_sha256", "hashes", "qa_sha256", "selected_needle_count"))
            pairs.append({"needle_count": count, "resolution_mm": resolution, "repeat": repeat,
                          "geometry_and_qa_match": matched, "before": old, "after": new})
    direct_function = {"before_sha256": canonical_function_digest(before), "after_sha256": canonical_function_digest(current)}
    evidence = {"schema_version": 1, "scope": "Synthetic isolated dependency replay only; not real-case, browser or clinical validation",
                "dependencies": {name: digest(REPO / name) for name in (
                    "tool_factory/seed_plan/planning_pipeline.py", "plans/guide_geometry.py", "web/planning_runs.py", "web/surgical_guide.py")},
                "before_pipeline_sha256": digest(before), "direct_guide_dependency_function": direct_function,
                "runner_sha256": digest(Path(__file__)), "python": sys.version,
                "pairs": pairs, "all_pairs_match": all(pair["geometry_and_qa_match"] for pair in pairs)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "paired_replays": len(pairs), "all_pairs_match": evidence["all_pairs_match"]}))
    return 0 if evidence["all_pairs_match"] and len(set(direct_function.values())) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
