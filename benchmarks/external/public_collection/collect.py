"""Acquire/verify public benchmark assets, without ever calling a SUT or API judge.

Vendor sources are inert files, not auto-imported code. SHA locks are trusted only
after explicit bootstrap review. All writes are confined to this collection.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def confined(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or not p.parts:
        raise ValueError("unsafe asset path")
    dest = (Path(root) / relative).resolve()
    if not dest.is_relative_to(Path(root).resolve()):
        raise ValueError("asset escapes collection")
    return dest


def selected(path, includes, excludes):
    return (any(path == p or path.startswith(p.rstrip("/") + "/") for p in includes)
            and not any(p in PurePosixPath(path).parts for p in excludes))


def unpack(source, dest, includes, excludes=(), kind="tar"):
    """No extractall, links, device nodes, traversal, or arbitrary archive roots."""
    if kind == "tar":
        with tarfile.open(source) as archive:
            for m in archive:
                name = "/".join(PurePosixPath(m.name).parts[1:])
                if not name or not selected(name, includes, excludes):
                    continue
                target = confined(dest, name)
                if not m.isfile() or m.issym() or m.islnk():
                    if m.isdir():
                        continue
                    raise ValueError("archive contains selected non-regular member")
                if m.size > 1024 ** 3:
                    raise ValueError("archive member too large")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(m) as src, target.open("wb") as out:
                    while chunk := src.read(1024 * 1024):
                        out.write(chunk)
    else:
        with zipfile.ZipFile(source) as archive:
            for m in archive.infolist():
                if m.is_dir() or not selected(m.filename, includes, excludes):
                    continue
                target = confined(dest, m.filename)
                if (m.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("zip symlink")
                if m.file_size > 1024 ** 3:
                    raise ValueError("zip member too large")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(m) as src, target.open("wb") as out:
                    while chunk := src.read(1024 * 1024):
                        out.write(chunk)


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    # No credentials; fail closed on HTTP errors. In particular never bypass a gate.
    max_seconds = "600" if dest.suffix in (".zip", ".gz", ".parquet") or "corpus" in dest.name else "75"
    subprocess.run(["curl", "-fSL", "--max-time", max_seconds, "--retry", "1",
                    "--max-filesize", str(1024 ** 3), "-o", str(part), url],
                   check=True, capture_output=True, timeout=1900)
    if part.stat().st_size == 0:
        raise ValueError("empty downloaded asset")
    part.replace(dest)


def jobs_for(entry, hf_host):
    repo = entry["source"].removeprefix("https://github.com/")
    for asset in entry["assets"]:
        kind = asset["kind"]
        if kind in ("github", "archive") and not re.fullmatch(r"[0-9a-f]{40}", entry["revision"]):
            raise ValueError("GitHub source must be commit pinned")
        if kind == "github":
            for path in asset["paths"]:
                yield {"url": f"https://raw.githubusercontent.com/{repo}/{entry['revision']}/{path}",
                       "path": f"assets/{entry['id']}/vendor/{path}", "kind": "file"}
        elif kind == "hf":
            if not re.fullmatch(r"[0-9a-f]{40}", asset["revision"]):
                raise ValueError("HF source must be revision pinned")
            # Subrepos do not share a corpus or qrels by accidental path collisions.
            sub = asset["repo"].split("/")[-1] if entry["id"] == "EXT-23" else "data"
            for path in asset["paths"]:
                yield {"url": f"https://{hf_host}/datasets/{asset['repo']}/resolve/{asset['revision']}/{path}",
                       "canonical_url": f"https://huggingface.co/datasets/{asset['repo']}/resolve/{asset['revision']}/{path}",
                       "path": f"assets/{entry['id']}/{sub}/{path}", "kind": "file"}
        elif kind == "archive":
            yield {"url": f"https://codeload.github.com/{repo}/tar.gz/{entry['revision']}",
                   "path": f"assets/{entry['id']}/source.tar.gz", "kind": "tar",
                   "dest": f"assets/{entry['id']}/vendor", "include": asset["include"], "exclude": asset["exclude"]}
        elif kind == "url_zip":
            yield {"url": asset["url"], "path": f"assets/{entry['id']}/data/{asset['name']}",
                   "kind": "zip", "dest": f"assets/{entry['id']}/data", "include": asset["include"], "exclude": []}
        else:
            raise ValueError("unknown source kind")


def fetch(root=ROOT, ids=(), bootstrap=False, hf_host="huggingface.co"):
    root = Path(root).resolve()
    catalog = read_json(root / "catalog.json")
    lock_path = root / "assets.lock.json"
    prior = read_json(lock_path) if lock_path.exists() else {"files": {}}
    if not bootstrap and not prior["files"]:
        raise ValueError("missing lock; explicit --bootstrap-lock required for first acquisition")
    if not bootstrap and prior.get("catalog_sha256") != sha256(root / "catalog.json"):
        raise ValueError("catalog changed; review in a new versioned collection before acquisition")
    entries = [e for e in catalog["benchmarks"] if not ids or e["id"] in ids]
    if set(ids) - {e["id"] for e in entries}:
        raise ValueError("unknown benchmark id")
    jobs = [j for e in entries for j in jobs_for(e, hf_host)]
    prefixes = tuple("assets/" + e["id"] + "/" for e in entries)
    # Check existing extracted members BEFORE unpacking an immutable archive.
    # Otherwise re-extraction could silently erase a user's local source edits.
    for name, expected in prior["files"].items():
        if name.startswith(prefixes):
            p = confined(root, name)
            if p.exists() and sha256(p) != expected["sha256"]:
                raise ValueError("existing locked asset changed; preserve it: " + name)

    def one(job):
        path = confined(root, job["path"])
        expected = prior["files"].get(job["path"])
        if expected and expected["url"] != job.get("canonical_url", job["url"]):
            raise ValueError("source revision/URL changed under a locked path; use a new versioned collection")
        if not bootstrap and not expected:
            raise ValueError("asset absent from reviewed lock: " + job["path"])
        if not path.exists():
            download(job["url"], path)
        digest = sha256(path)
        if expected and digest != expected["sha256"]:
            raise ValueError("asset hash mismatch; never overwrite lock: " + job["path"])
        if job["kind"] in ("tar", "zip"):
            unpack(path, confined(root, job["dest"]), job["include"], job["exclude"], job["kind"])
        if expected:
            # Revalidation of a cache is not a new network transfer. Preserve
            # the actual acquisition/mirror URL instead of rewriting provenance.
            return job["path"], dict(expected)
        return job["path"], {"sha256": digest, "bytes": path.stat().st_size,
                             "url": job.get("canonical_url", job["url"]), "download_url": job["url"]}

    failed = []
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(one, j): j for j in jobs}
        for f in cf.as_completed(futures):
            try:
                name, item = f.result()
                prior["files"][name] = item
                print(json.dumps({"asset": name, "bytes": item["bytes"], "status": "verified"}), flush=True)
            except Exception as exc:
                failed.append({"asset": futures[f]["path"], "error": str(exc)[:700]})
                print(json.dumps(failed[-1]), flush=True)
    # Also lock extracted source/data members so a changed scorer cannot hide behind an archive hash.
    for entry in entries:
        folder = root / "assets" / entry["id"]
        if folder.exists():
            for path in folder.rglob("*"):
                if path.is_file() and not path.name.endswith((".part", ".pyc")) and "__pycache__" not in path.parts:
                    name = path.relative_to(root).as_posix()
                    digest = sha256(path)
                    old = prior["files"].get(name)
                    if old and digest != old["sha256"]:
                        raise ValueError("extracted asset hash mismatch: " + name)
                    prior["files"].setdefault(name, {"sha256": digest, "bytes": path.stat().st_size,
                                                    "url": "member_of_pinned_archive"})
    prior.update(schema_version=1, catalog_sha256=sha256(root / "catalog.json"), sut_runs=0)
    write_json(lock_path, prior)
    write_json(root / "acquisition_status.json", {"failures": failed, "requested_ids": [e["id"] for e in entries], "sut_runs": 0})
    return failed


def verify(root=ROOT):
    root = Path(root)
    lock = read_json(root / "assets.lock.json")
    problems = []
    if sha256(root / "catalog.json") != lock["catalog_sha256"]:
        problems.append("catalog_changed_since_lock")
    for name, item in lock["files"].items():
        p = confined(root, name)
        if not p.is_file() or sha256(p) != item["sha256"]:
            problems.append(name)
    expected = {j["path"] for e in read_json(root / "catalog.json")["benchmarks"] for j in jobs_for(e, "huggingface.co")}
    problems.extend("unacquired:" + p for p in sorted(expected - set(lock["files"])))
    return {"asset_files": len(lock["files"]), "problems": problems, "sut_runs": 0,
            "evaluation_mode": "collection_integrity_not_sut_evaluation"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["fetch", "verify"])
    p.add_argument("--ids", nargs="*", default=[])
    p.add_argument("--bootstrap-lock", action="store_true")
    p.add_argument("--hf-host", choices=["huggingface.co", "hf-mirror.com"], default="huggingface.co")
    a = p.parse_args()
    if a.action == "fetch":
        return int(bool(fetch(ids=a.ids, bootstrap=a.bootstrap_lock, hf_host=a.hf_host)))
    result = verify()
    print(json.dumps(result, indent=2))
    return int(bool(result["problems"]))


if __name__ == "__main__":
    raise SystemExit(main())
