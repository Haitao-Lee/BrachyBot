"""Fail closed when a shared geometry dependency changes on both test sides."""
import hashlib
import json
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
    return manifest
