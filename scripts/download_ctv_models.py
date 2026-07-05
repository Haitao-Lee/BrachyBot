"""Download external CTV model checkpoints listed in BrachyBot's catalog.

The downloaded DiffTumor checkpoints are research resources. They are not
activated automatically because their checkpoint format is not the native
nnU-Net v2 folder format used by BrachyBot's production pancreatic tool.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_catalog():
    catalog_path = ROOT / "tool_factory" / "CTV_seg" / "model_catalog.py"
    spec = importlib.util.spec_from_file_location("brachybot_ctv_model_catalog", catalog_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load catalog from {catalog_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CTV_MODEL_CATALOG


CTV_MODEL_CATALOG = _load_catalog()


def _download(url: str, dest: Path, force: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"exists: {dest}")
        return

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"download: {url}")
    print(f"to:       {dest}")
    with urllib.request.urlopen(url) as response, open(tmp, "wb") as fh:
        total = response.headers.get("Content-Length")
        expected = int(total) if total and total.isdigit() else None
        copied = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            copied += len(chunk)
            if expected:
                pct = copied * 100.0 / expected
                print(f"\r{copied / 1024 / 1024:.1f} MB / {expected / 1024 / 1024:.1f} MB ({pct:.1f}%)", end="")
    if expected:
        print()
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", help="Catalog model id to download. Repeatable. Default: all downloadable models.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--list", action="store_true", help="List downloadable model ids and exit.")
    args = parser.parse_args()

    downloadable = [m for m in CTV_MODEL_CATALOG if m.get("download_url")]
    if args.list:
        for model in downloadable:
            print(f"{model['id']}\t{model['site']}\t{model['download_url']}")
        return 0

    selected = set(args.model or [str(m["id"]) for m in downloadable])
    missing = selected - {str(m["id"]) for m in downloadable}
    if missing:
        raise SystemExit(f"Unknown or non-downloadable model ids: {', '.join(sorted(missing))}")

    for model in downloadable:
        if str(model["id"]) not in selected:
            continue
        rel = model.get("local_expected_path")
        url = model.get("download_url")
        if not isinstance(rel, str) or not isinstance(url, str):
            continue
        _download(url, ROOT / rel, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
