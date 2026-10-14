"""Fail closed when a shared geometry dependency changes on both test sides."""
import hashlib
import json
import math
from pathlib import Path


def verify_reference(repo=None):
    root = Path(repo) if repo else Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "tests/guide_latency_reference.json").read_text())
    paths = dict(manifest["dependencies"])
    paths["tests/data/surgical_guide_latency_reference.py"] = manifest["module_sha256"]
    for name, expected in paths.items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f"Guide latency reference dependency changed: {name}. "
                                 "Audit the change and renew paired evidence before updating its hash.")
    if manifest.get("schema_version") == 2:
        renewal = manifest["renewal"]
        evidence_path = (root / renewal["evidence_path"]).resolve(strict=True)
        if root.resolve() not in evidence_path.parents:
            raise AssertionError("Guide renewal evidence escapes repository")
        raw = evidence_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != renewal["evidence_sha256"]:
            raise AssertionError("Guide renewal paired evidence hash changed")
        evidence = json.loads(raw)
        pairs = evidence.get("pairs", [])
        if len(pairs) < 4 or evidence.get("all_pairs_match") is not True:
            raise AssertionError("Guide renewal lacks passing paired evidence")
        helper = evidence["direct_guide_dependency_function"]
        if helper["before_sha256"] != helper["after_sha256"]:
            raise AssertionError("Guide dependency helper changed; this renewal protocol is insufficient")
        for name, expected in manifest["dependencies"].items():
            if evidence["dependencies"].get(name) != expected:
                raise AssertionError("Guide paired evidence does not bind current dependencies")
        if evidence["before_pipeline_sha256"] != renewal["before_pipeline_sha256"]:
            raise AssertionError("Guide renewal pre-patch evidence is not the audited baseline")
        if renewal.get('before_planning_runs_sha256') is not None and (
                evidence.get('before_planning_runs_sha256') != renewal['before_planning_runs_sha256']):
            raise AssertionError('Guide replay did not bind the earlier planning history dependency')
        for pair in pairs:
            old, new = pair["before"], pair["after"]
            if renewal.get('before_planning_runs_sha256') is not None and (
                    old.get('guide_sources',{}).get('web/planning_runs.py') != renewal['before_planning_runs_sha256']
                    or new.get('guide_sources',{}).get('web/planning_runs.py') != manifest['dependencies']['web/planning_runs.py']):
                raise AssertionError('Guide replay loaded the wrong planning history variant')
            if (pair.get("geometry_and_qa_match") is not True
                    or old["dependency_sha256"] != evidence["before_pipeline_sha256"]
                    or new["dependency_sha256"] != manifest["dependencies"]["tool_factory/seed_plan/planning_pipeline.py"]
                    or any(old[key] != new[key] for key in ("input_sha256", "hashes", "qa_sha256", "selected_needle_count"))
                    or any(not math.isfinite(item["seconds"]) or item["seconds"] <= 0 for item in (old, new))):
                raise AssertionError("Guide renewal paired replay is invalid")
    return manifest
