"""Freeze installed wheel hashes and local model hashes without loading models.

The wheelhouse must already contain every installed distribution's wheel. A
lock includes the entire probe environment, not just the top-level packages.
Model hashes identify observed bytes, not source trust or clinical approval.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import zipfile


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024**2), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output directory must be new")
    installed = {canonical(d.metadata["Name"]): d.version for d in importlib.metadata.distributions()}
    wheels = {}
    for wheel in sorted(args.wheelhouse.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            metadata = archive.read(metadata_path).decode()
        name = canonical(re.search(r"^Name: (.+)$", metadata, re.MULTILINE).group(1).strip())
        version = re.search(r"^Version: (.+)$", metadata, re.MULTILINE).group(1).strip()
        if installed.get(name) == version:
            if name in wheels:
                raise RuntimeError("Multiple wheels for an installed distribution; select one target-platform wheel")
            wheels[name] = {"version": version, "filename": wheel.name, "sha256": digest(wheel)}
    missing = set(installed) - set(wheels)
    if missing:
        raise RuntimeError("Wheelhouse lacks installed packages: " + ", ".join(sorted(missing)))
    models = []
    for directory in (args.repo / "models", args.repo / "VoCo"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix in {".pth", ".pt", ".safetensors"}:
                models.append({"path": str(path.relative_to(args.repo)), "bytes": path.stat().st_size, "sha256": digest(path)})
    args.output.mkdir(parents=True, mode=0o700)
    lock = ["# Linux x86_64 / Python 3.12 isolated compatibility candidate; not deployment approval.",
            "# Install offline with --no-index --find-links <wheelhouse> --require-hashes."]
    lock += [f"{name}=={entry['version']} --hash=sha256:{entry['sha256']}" for name, entry in sorted(wheels.items())]
    (args.output / "requirements.lock").write_text("\n".join(lock) + "\n")
    (args.output / "wheel_manifest.json").write_text(json.dumps({"python": sys.version, "packages": wheels}, indent=2) + "\n")
    (args.output / "model_manifest.json").write_text(json.dumps({"scope": "Observed local models/ and VoCo/ bytes only; external model/runtime roots are not frozen; no provenance or clinical approval implied", "models": models}, indent=2) + "\n")
    print(json.dumps({"packages": len(wheels), "local_models": len(models), "output": str(args.output)}))


if __name__ == "__main__":
    main()
