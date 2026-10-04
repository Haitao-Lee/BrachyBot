"""Bounded, read-only credential checks. Never return values or matched text.

Only provider-key-shaped literals and registered compromised fingerprints are
recognized. This is not a general DLP scan or proof of provider revocation.
Explicit roots include backups/logs; Git objects, patient/model data, symlink
targets and compressed archives are NOT inspected. Exclusions are reported.
"""
import hashlib
import codecs
import json
import os
from pathlib import Path
import re
import stat


KEY_PATTERN = re.compile(rb"\bsk-[A-Za-z0-9_-]{20,1024}")
EXCLUDED_DIRS = frozenset({
    ".git", ".runtime", "runtime", "release-state", "models", "node_modules",
    "__pycache__", ".pytest_cache", ".venv", "venv", "data", "datasets",
})
ARCHIVE_SUFFIXES = (".zip", ".tar", ".gz", ".bz2", ".xz", ".7z")
DATA_SUFFIXES = frozenset({
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".npy", ".npz", ".pkl",
    ".nii", ".dcm", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".pdf", ".stl",
    ".sqlite", ".sqlite3", ".db", ".tif", ".tiff", ".parquet", ".so", ".pyc", ".h5", ".hdf5",
})


def load_incidents(path):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = document["credentials"]
        if document["schema_version"] != 1 or not isinstance(entries, list) or not entries:
            raise ValueError
        for entry in entries:
            if (not isinstance(entry, dict)
                    or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", ""))
                    or entry.get("revocation_status") not in {"unverified", "revoked"}):
                raise ValueError
        return entries, []
    except (OSError, ValueError, KeyError, TypeError):
        return [], [{"id": "credential_incident_registry_unavailable", "severity": "block",
                     "message": "Compromised credential fingerprints could not be verified."}]


def _stream_key_locations(handle, prefix, max_file_bytes):
    """Bounded overlap includes keys split across a 1 MiB read boundary."""
    buffer, line, consumed = prefix, 1, len(prefix)
    while True:
        chunk = handle.read(1024**2)
        consumed += len(chunk)
        if consumed > max_file_bytes:
            raise OSError("Scan file grew past its resource budget")
        buffer += chunk
        cutoff = max(0, len(buffer) - 2048) if chunk else len(buffer)
        for match in KEY_PATTERN.finditer(buffer):
            if match.start() < cutoff:
                yield match.group(), line + buffer.count(b"\n", 0, match.start())
        line += buffer.count(b"\n", 0, cutoff)
        buffer = buffer[cutoff:]
        if not chunk:
            return


def scan_sources(roots, incidents, *, max_file_bytes=512 * 1024**2,
                 max_total_bytes=2 * 1024**3, max_files=120000):
    findings, excluded, seen = [], [], set()
    fingerprints = {item["sha256"] for item in incidents}
    total, count = 0, 0
    for raw_root in roots:
        root = Path(raw_root).absolute()
        if not root.exists() or root.is_symlink():
            findings.append({"id": "credential_scan_root_unavailable", "severity": "block",
                             "path": str(root), "message": "Explicit scan root is missing or a symlink."})
            continue
        if root.is_file():
            candidates = [(root.parent, [], [root.name])]
        else:
            def walk_error(_error):
                findings.append({"id": "credential_scan_unreadable_directory", "severity": "block",
                                 "path": str(root), "message": "A scan directory could not be read."})
            candidates = os.walk(root, followlinks=False, onerror=walk_error)
        for directory, dirs, names in candidates:
            directory = Path(directory)
            dirs.sort()
            for name in list(dirs):
                path = directory / name
                if name in EXCLUDED_DIRS or path.is_symlink():
                    dirs.remove(name)
                    excluded.append({"path": str(path), "reason": "data/cache/Git or symlink directory"})
            for name in sorted(names):
                path = directory / name
                if path in seen:
                    continue
                seen.add(path)
                try:
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        excluded.append({"path": str(path), "reason": "non-regular file or symlink"})
                        continue
                    if name.endswith(ARCHIVE_SUFFIXES):
                        excluded.append({"path": str(path), "reason": "compressed archive; inspect separately"})
                        continue
                    if path.suffix.lower() in DATA_SUFFIXES:
                        excluded.append({"path": str(path), "reason": "binary model/medical/artifact data; not source scan"})
                        continue
                    # Do not follow a file swapped to a symlink after lstat.
                    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                    with os.fdopen(descriptor, "rb") as handle:
                        opened = os.fstat(handle.fileno())
                        if (not stat.S_ISREG(opened.st_mode)
                                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                            raise OSError("Scan target changed while opening")
                        prefix = handle.read(4096)
                        try:
                            codecs.getincrementaldecoder("utf-8")().decode(prefix, final=False)
                            text = b"\0" not in prefix
                        except UnicodeDecodeError:
                            text = False
                        if not text:
                            excluded.append({"path": str(path), "reason": "non-UTF8/binary file; not source scan"})
                            continue
                        count += 1
                        if count > max_files or total + opened.st_size > max_total_bytes:
                            findings.append({"id": "credential_scan_budget_exceeded", "severity": "block",
                                             "message": "Source scan stopped at its explicit resource budget."})
                            return findings, {"files": count - 1, "bytes": total, "complete_within_scope": False,
                                              "excluded": excluded}
                        if opened.st_size > max_file_bytes:
                            findings.append({"id": "credential_scan_oversized_file", "severity": "block",
                                             "path": str(path), "message": "An in-scope file exceeds the scan budget."})
                            continue
                        for value, line in _stream_key_locations(handle, prefix, max_file_bytes):
                            compromised = hashlib.sha256(value).hexdigest() in fingerprints
                            findings.append({"id": "compromised_credential_copy" if compromised else "plaintext_provider_key",
                                             "severity": "block", "path": str(path), "line": line,
                                             "message": "A credential-shaped literal was found; its value is redacted. Unknown fingerprints may be synthetic placeholders and require review."})
                        if os.fstat(handle.fileno()).st_size != opened.st_size:
                            raise OSError("Scan target changed while reading")
                    total += opened.st_size
                except OSError:
                    findings.append({"id": "credential_scan_file_unreadable", "severity": "block",
                                     "path": str(path), "message": "An in-scope file could not be read safely."})
    return findings, {"files": count, "bytes": total,
                      "complete_within_scope": not any(f["severity"] == "block" and f["id"].startswith("credential_scan") for f in findings),
                      "excluded": excluded}


def discover_processes(root, *, proc_root=Path("/proc")):
    """Find same-user processes whose cwd is this checkout; never read cmdline."""
    root = Path(root).resolve()
    found = []
    for path in Path(proc_root).glob("[0-9]*"):
        try:
            if int(path.name) == os.getpid() or path.stat().st_uid != os.getuid():
                continue
            if (path / "cwd").resolve(strict=True) == root:
                found.append(int(path.name))
        except (OSError, ValueError):
            continue
    return sorted(found)


def scan_processes(pids, incidents, *, proc_root=Path("/proc")):
    fingerprints = {item["sha256"] for item in incidents}
    findings, inspected = [], []
    for pid in sorted(set(pids)):
        try:
            pid = int(pid)
            if pid < 1:
                raise ValueError
            path = Path(proc_root) / str(pid)
            if path.stat().st_uid != os.getuid():
                raise PermissionError
            with (path / "environ").open("rb") as handle:
                raw = handle.read(8 * 1024**2 + 1)
            if len(raw) > 8 * 1024**2:
                raise ValueError
            inspected.append(pid)
            for field in raw.split(b"\0"):
                name, equals, value = field.partition(b"=")
                if equals and value and hashlib.sha256(value).hexdigest() in fingerprints:
                    # Unexpected variable names may themselves contain sensitive
                    # data. Emit a name only when it is a normal shell identifier.
                    safe_name = name.decode("ascii", "ignore")
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", safe_name):
                        safe_name = "<redacted-variable-name>"
                    findings.append({"id": "compromised_process_credential", "severity": "block",
                                     "pid": pid, "variable": safe_name,
                                     "message": "A registered compromised credential remains in process environment."})
                if equals and name in {b"BRACHYBOT_ALLOW_INSECURE_REMOTE", b"BRACHYBOT_DEBUG_ACCOUNT_ENABLED", b"BRACHYBOT_ALLOW_SELF_REGISTRATION"} and value.lower() in {b"1", b"true", b"yes", b"on"}:
                    findings.append({"id": "process_development_override", "severity": "block", "pid": pid,
                                     "variable": name.decode(), "message": "The selected process inherits a release-unsafe override."})
        except (OSError, ValueError, TypeError):
            findings.append({"id": "credential_process_uninspectable", "severity": "block",
                             "pid": pid, "message": "A requested process environment could not be inspected."})
    return findings, {"inspected_pids": inspected, "requested_pids": sorted(set(pids)),
                      "scope": "same-user selected processes; compromised fingerprints only"}
