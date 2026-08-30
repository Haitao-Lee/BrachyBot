#!/usr/bin/env python3
"""Install the pinned official SAT3D runtime outside the BrachyBot checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path


REPOSITORY = "https://github.com/himashi92/SAT3D.git"
COMMIT = "e85cbf4b2e17c09b34b36369c4eca29e98321b4b"
ARTIFACTS = {
    "sam_model_dice_best.pth": (
        "https://ndownloader.figshare.com/files/58060666",
        "a5e59c357e01a4f9bda20564114bbd8a",
    ),
    "critic_dice_best.pth": (
        "https://ndownloader.figshare.com/files/58060657",
        "867286a0cf792693608509d0131834dc",
    ),
}


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=str(cwd) if cwd else None, check=True)


def md5(path: Path) -> str:
    digest = hashlib.md5()  # nosec B324 - artifact identity only
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--base-python", default=sys.executable)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if root.exists() and not (root / ".git").is_dir():
        raise RuntimeError(f"Refusing to overwrite non-git path: {root}")
    if not root.exists():
        run("git", "clone", REPOSITORY, str(root))
    run("git", "fetch", "--all", "--prune", cwd=root)
    run("git", "checkout", "--detach", COMMIT, cwd=root)

    runtime = root / ".venv"
    if not runtime.exists():
        run(args.base_python, "-m", "venv", "--system-site-packages", str(runtime))
    python = runtime / "bin" / "python"
    run(str(python), "-m", "pip", "install", "--upgrade", "pip")
    run(
        str(python), "-m", "pip", "install",
        "monai", "SimpleITK", "scipy", "torchio", "timm", "yacs", "einops", "edt", "prefetch_generator",
    )

    weights = root / "weights"
    weights.mkdir(parents=True, exist_ok=True)
    for filename, (url, expected) in ARTIFACTS.items():
        destination = weights / filename
        if not destination.is_file() or md5(destination) != expected:
            temporary = destination.with_suffix(destination.suffix + ".part")
            urllib.request.urlretrieve(url, temporary)
            if md5(temporary) != expected:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum mismatch for {filename}")
            temporary.replace(destination)

    marker = {
        "repository": REPOSITORY,
        "commit": COMMIT,
        "runtime_python": str(python),
        "artifacts": {
            name: {"path": str(weights / name), "md5": expected}
            for name, (_, expected) in ARTIFACTS.items()
        },
    }
    (root / ".brachybot-sat3d-runtime.json").write_text(
        json.dumps(marker, indent=2), encoding="utf-8"
    )
    print(json.dumps(marker, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
