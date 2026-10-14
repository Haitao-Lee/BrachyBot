"""Checksummed complete patient workspace exchange, including immutable scan history."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile

from web.timepoints import TimepointError, TimepointIntegrityError, validate_catalog
from web.workspace_store import _atomic_bytes, _safe_workspace_child

MAX_FILES = 100000
MAX_BYTES = 32 * 1024**3
MAX_JSON_BYTES = 256 * 1024**2
MAX_UPLOAD_BYTES = 500 * 1024**2
MAX_COMPRESSION_RATIO = 1000
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _encoded(value):
    # ImplantService verifies the canonical *bytes*, not merely parsed JSON.
    # Browser truncation can leave a lone UTF-16 surrogate in presentation
    # text. Escape only those code units; valid Unicode keeps identical
    # canonical bytes and all scientific journal hashes remain compatible.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8", errors="backslashreplace")


def _json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise TimepointIntegrityError("Duplicate JSON keys in workspace graph")
            value[key] = item
        return value
    try:
        return json.loads(data, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TimepointIntegrityError("Unreadable workspace graph JSON") from exc


def _relative(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise TimepointIntegrityError("Unsafe bundle resource path")
    parts = value.split("/")
    if (PurePosixPath(value).is_absolute() or "\\" in value or ":" in value
            or any(ord(char) < 32 for char in value) or any(char in value for char in '<>"|?*')
            or any(part in {"", ".", ".."} or part.endswith((" ", ".")) or _RESERVED.match(part) for part in parts)):
        raise TimepointIntegrityError("Unsafe bundle resource path")
    return value


def _regular(path, root):
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise TimepointIntegrityError("Workspace resources cannot traverse filesystem links")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise TimepointIntegrityError("Workspace resources must be regular, singly owned files")


def _inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise TimepointIntegrityError("A workspace link cannot be exported as an owned resource")
        if not path.is_file():
            continue
        _regular(path, root)
        if path.name.endswith((".lock", ".tmp", "-wal", "-shm", "-journal")) or ".tmp-" in path.name:
            continue
        stamp = path.stat()
        result[_relative(path.relative_to(root).as_posix())] = (stamp.st_size, stamp.st_mtime_ns)
    if len(result) > MAX_FILES or sum(row[0] for row in result.values()) > MAX_BYTES:
        raise TimepointError("The complete workspace exceeds the exchange resource limit")
    return result


def _sqlite_backup(path, destination):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(destination) as output:
        source.backup(output)
        if output.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise TimepointIntegrityError("An owned journal database is corrupt")


def _validate_graph(root, metadata):
    """Verify all ledger, array and immutable head edges before any publication."""
    from web.timepoint_images import validate_collection
    session_id, catalog = metadata["session_id"], metadata["catalog"]
    validate_catalog(catalog, session_id)
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
    if "snapshot.json" not in files:
        raise TimepointIntegrityError("Complete workspace snapshot is missing")
    values = {}
    for relative, path in files.items():
        if path.suffix.lower() == ".json":
            if path.stat().st_size > MAX_JSON_BYTES:
                raise TimepointIntegrityError("Workspace JSON exceeds its record limit")
            values[relative] = _json(path.read_bytes())
    def owned(relative, expected=None):
        candidate = files.get(_relative(relative.replace("\\", "/")))
        if candidate is None:
            raise TimepointIntegrityError("A graph resource reference is missing")
        if expected is not None and (not _HASH.fullmatch(str(expected)) or sha256(candidate) != expected):
            raise TimepointIntegrityError("An immutable graph resource checksum disagrees")
        return candidate
    if values["snapshot.json"].get("session_id") != session_id:
        raise TimepointIntegrityError("Snapshot belongs to another Session")
    version_keys = set()
    for row in metadata.get("state_versions") or []:
        target, number = row.get("timepoint_id"), row.get("state_revision")
        if target not in catalog["items"] or type(number) is not int or number < 0 or (target, number) in version_keys:
            raise TimepointIntegrityError("Invalid complete version ledger")
        version_keys.add((target, number))
        ref = _json(row["state_ref_json"])
        path = owned(ref["path"], ref["sha256"])
        state = values.get(path.relative_to(root).as_posix())
        if not isinstance(state, dict) or state.get("session_id") != session_id or state.get("timepoint_id") != target:
            raise TimepointIntegrityError("Version ledger state belongs to another target")
        for relative in ref.get("arrays") or []:
            owned(relative)
    for target, item in catalog["items"].items():
        for ref in [item.get("state_ref"), *item["state_history"]]:
            if ref is None:
                continue
            path = owned(ref["path"], ref["sha256"])
            state = values.get(path.relative_to(root).as_posix())
            if not isinstance(state, dict) or state.get("session_id") != session_id or state.get("timepoint_id") != target:
                raise TimepointIntegrityError("Catalog state belongs to another target")
            for relative in ref.get("arrays") or []:
                owned(relative)
    def edges(value, depth=0, field=""):
        if depth > 128:
            raise TimepointIntegrityError("Workspace graph exceeds its nesting limit")
        if isinstance(value, dict):
            if "$array" in value:
                owned(value["$array"])
            if isinstance(value.get("path"), str) and "sha256" in value and not Path(value["path"]).is_absolute():
                owned(value["path"], value["sha256"])
            for key, child in value.items():
                if key != "acquisition_files":
                    edges(child, depth + 1, key)
        elif isinstance(value, list):
            for child in value:
                edges(child, depth + 1, field)
    for relative, value in values.items():
        edges(value)
        if isinstance(value, dict) and "image_collection" in value:
            collection = value["image_collection"]
            validate_collection(collection, session_id, value["timepoint_id"])
            for image in collection["images"].values():
                owned(image["source_path"], image["source_sha256"])
                owned(image["volume_path"], image["volume_sha256"])
                if image.get("acquisition_files"):
                    with zipfile.ZipFile(owned(image["source_path"])) as acquisition:
                        for receipt in image["acquisition_files"]:
                            info = acquisition.getinfo(_relative(receipt["path"]))
                            if info.file_size != receipt["bytes"] or hashlib.sha256(acquisition.read(info)).hexdigest() != receipt["sha256"]:
                                raise TimepointIntegrityError("DICOM acquisition member receipt disagrees")
        if relative.startswith("artifacts/implant_reconstruction/") and relative.endswith("/index.json"):
            scope = value.get("scope") or {}
            if scope.get("session_id") != session_id or scope.get("timepoint_id") not in catalog["items"]:
                raise TimepointIntegrityError("Implant journal scope does not belong to this graph")
            namespace = hashlib.sha256(_encoded(scope)).hexdigest()[:32]
            if relative.split("/")[2] != namespace:
                raise TimepointIntegrityError("Implant journal namespace and scope disagree")
            if value.get("current") is not None and value["current"] not in value.get("history", []):
                raise TimepointIntegrityError("Implant journal head is absent from its immutable history")
            for ref in value.get("history", []):
                record = values.get(ref["path"].replace("\\", "/"))
                if not isinstance(record, dict) or record.get("scope") != scope:
                    raise TimepointIntegrityError("Implant revision belongs to another namespace")
                from utils.implant_reconstruction import SeedAxisReconstruction
                try:
                    reconstruction = SeedAxisReconstruction.from_dict(record["reconstruction"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise TimepointIntegrityError("Implant revision geometry/review receipt is invalid") from exc
                if uuid.UUID(ref["revision_id"]) != uuid.UUID(reconstruction.revision_id):
                    raise TimepointIntegrityError("Implant head revision identity disagrees")
    return values


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(raw, owner, session_id):
    """One SQLite read snapshot of all owned durable control-plane ledgers."""
    catalog = raw._timepoint_catalog(owner, session_id)
    with raw._read_connection() as connection:
        connection.execute("BEGIN")
        versions = [dict(row) for row in connection.execute(
            "SELECT timepoint_id,state_revision,state_ref_json FROM timepoint_state_versions WHERE session_id=? ORDER BY timepoint_id,state_revision",
            (session_id,))]
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ledgers = {}
        for table in ("timepoint_operations", "review_comments", "audit_events", "context_token_accounting"):
            ledgers[table] = [dict(row) for row in connection.execute(
                f"SELECT * FROM {table} WHERE session_id=? AND user_id=?", (session_id, owner))] if table in names else []
        record = connection.execute("SELECT * FROM case_sessions WHERE id=? AND user_id=?", (session_id, owner)).fetchone()
        row = connection.execute("SELECT catalog_json FROM timepoint_catalogs WHERE session_id=? AND user_id=?",
                                 (session_id, owner)).fetchone()
        if row:
            catalog = _json(row["catalog_json"])
    if not record or record["status"] != "active" or record["storage_status"] != "active":
        raise TimepointIntegrityError("The export Session became unavailable")
    return {"schema_version": 2, "session_id": session_id, "owner_id": owner,
            "source_root": str(raw.workspace_root(owner, session_id)),
            "catalog": catalog, "state_versions": versions, "session": dict(record), "ledgers": ledgers,
            "review_policy": "Imported observations require revalidation; cached dose is stale; no tasks resume"}


def export_bundle(store, owner, session_id, destination):
    raw = getattr(store, "raw", store)
    destination = Path(destination)
    with raw._case_guard(owner, session_id), raw._quota_commit_lock(owner):
        raw.require_local_session(owner, session_id)
        root = raw.workspace_root(owner, session_id)
        if destination.resolve().is_relative_to(root.resolve()) or destination.exists():
            raise TimepointError("A full bundle must use a new file outside its source workspace")
        initial = _inventory(root)
        metadata = _metadata(raw, owner, session_id)
        total = sum(size for size, _ in initial.values())
        # Staging is charged even when it is outside the quota walker. The lock
        # excludes concurrent account commits throughout staging and packaging.
        raw.ensure_capacity(owner, total * 2 + 1024 * 1024)
        destination.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with tempfile.TemporaryDirectory(prefix="timepoint-bundle-", dir=raw.staging_dir) as temporary:
                staging = Path(temporary)
                files = []
                for relative in initial:
                    path = root / relative
                    copied = _safe_workspace_child(staging, relative)
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    if path.suffix.lower() in {".sqlite3", ".sqlite", ".db"}:
                        _sqlite_backup(path, copied)
                    else:
                        # Hash the actual immutable copy, and fence its source
                        # before/after copying to catch cross-process writers.
                        before = sha256(path)
                        shutil.copyfile(path, copied)
                        if before != sha256(copied) or before != sha256(path):
                            raise TimepointIntegrityError("A source changed during complete workspace export")
                    files.append({"path": relative, "bytes": copied.stat().st_size, "sha256": sha256(copied)})
                _validate_graph(staging, metadata)
                manifest = {**metadata, "files": files}
                payload = _encoded(manifest)
                if len(payload) > MAX_JSON_BYTES:
                    raise TimepointIntegrityError("The complete graph manifest is oversized")
                with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                    created = True
                    archive.writestr("manifest.json", payload)
                    for row in files:
                        archive.write(staging / row["path"], "workspace/" + row["path"])
                if _inventory(root) != initial or _metadata(raw, owner, session_id) != metadata:
                    raise TimepointIntegrityError("The workspace graph changed during complete workspace export")
                if destination.stat().st_size + total > total * 2 + 1024 * 1024:
                    raw.ensure_capacity(owner, destination.stat().st_size + total)
                with destination.open("rb") as handle:
                    os.fsync(handle.fileno())
                raw._fsync_directory(destination.parent)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return destination


def _checked_archive(archive):
    entries = archive.infolist()
    names = [row.filename for row in entries]
    if len(entries) > MAX_FILES + 1 or len(set(names)) != len(names) or len({v.casefold() for v in names}) != len(names):
        raise TimepointIntegrityError("Duplicate, colliding or excessive ZIP entries")
    total = 0
    for info in entries:
        _relative(info.filename)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if info.is_dir() or kind not in {0, stat.S_IFREG} or info.flag_bits & 1:
            raise TimepointIntegrityError("ZIP resources must be unencrypted regular files")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise TimepointIntegrityError("Unsupported archive compression")
        if info.file_size < 0 or info.compress_size < 0:
            raise TimepointIntegrityError("Invalid ZIP resource size")
        if info.file_size > 64 * 1024**2 and info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO:
            raise TimepointIntegrityError("ZIP resource exceeds the decompression ratio limit")
        total += info.file_size
        if total > MAX_BYTES + MAX_JSON_BYTES:
            raise TimepointIntegrityError("ZIP exceeds its expanded resource limit")
    if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > MAX_JSON_BYTES:
        raise TimepointIntegrityError("Missing or oversized graph manifest")
    manifest = _json(archive.read("manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in {1, 2}:
        raise TimepointIntegrityError("Unsupported complete workspace bundle")
    try:
        uuid.UUID(manifest["session_id"])
        validate_catalog(manifest["catalog"], manifest["session_id"])
        rows = manifest["files"]
        if not isinstance(rows, list) or len(rows) > MAX_FILES:
            raise ValueError("Invalid resource list")
        paths, seen = {}, set()
        for row in rows:
            if (not isinstance(row, dict) or type(row.get("bytes")) is not int or row["bytes"] < 0
                    or not _HASH.fullmatch(str(row.get("sha256", "")))):
                raise ValueError("Invalid resource receipt")
            relative = _relative(row["path"])
            if relative.casefold() in seen:
                raise ValueError("Duplicate resource path")
            seen.add(relative.casefold())
            paths[relative] = row
            if archive.getinfo("workspace/" + relative).file_size != row["bytes"]:
                raise ValueError("ZIP and receipt sizes disagree")
        if set(names) != {"manifest.json", *("workspace/" + path for path in paths)}:
            raise ValueError("ZIP resources and manifest disagree")
        # File/ancestor collisions must fail before extraction on every OS.
        keys = {key.casefold() for key in paths}
        for key in paths:
            if any(parent.as_posix().casefold() in keys for parent in PurePosixPath(key).parents if str(parent) != "."):
                raise ValueError("File/directory collision")
        return manifest, paths
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, TimepointIntegrityError):
            raise
        raise TimepointIntegrityError("The bundle does not describe one valid owned graph") from exc


def _remapper(metadata, owner, new_session, root, namespace_remap, operation_remap):
    old_session = metadata["session_id"]
    old_owner = metadata.get("owner_id")
    old_root = str(metadata.get("source_root") or "").replace("\\", "/").rstrip("/")

    def remap(value, field="", depth=0):
        if depth > 128:
            raise TimepointIntegrityError("Imported graph exceeds its nesting limit")
        if isinstance(value, dict):
            result = {key: remap(item, key, depth + 1) for key, item in value.items()}
            if "owner_id" in result:
                result["owner_id"] = owner
            if "user_id" in result:
                result["user_id"] = owner
            for key in ("receipt_token", "human_timepoint_confirmation", "editor_token", "owner_token"):
                result.pop(key, None)
            if result.get("review_state") == "accepted":
                result["review_state"] = "pending"
            if result.get("review_status") == "accepted":
                result["review_status"] = "review_needed"
            for key in ("clinical_use_ready", "clinical_use_approved", "dose_input_ready",
                        "manufacturing_confirmed", "evidence_reviewed", "auto_resumed"):
                if key in result:
                    result[key] = False
            if "set_reviewer_id" in result:
                # Even an accepted zero-observation set requires fresh review.
                result.update(set_reviewer_id=None, set_review_evidence=None, review_status="review_needed",
                              dose_input_ready=False)
            # A clinical job enum and a UI state's nested dictionary are
            # different contracts despite sharing a JSON property name.
            if isinstance(result.get('state'),str) and result['state'] in {"running", "queued", "preparing", "optimizing"}:
                result.update(state="interrupted", reason="imported_job_requires_explicit_restart", auto_resumed=False)
            if isinstance(result.get('status'),str) and result['status'] in {"queued", "running", "preparing", "optimizing"}:
                result.update(status="interrupted", auto_resumed=False)
            if (isinstance(result.get('source_set'),str) and result['source_set'] in {"implanted", "planned", "total"}
                    or field.endswith("dose_record")) and (
                    "dose_units" in result or "dose_distribution_physical_gy" in result):
                result.update(status="stale", stale=True, dose_status="stale",
                    stale_reason="imported_inputs_require_revalidation", dependency_fingerprint=None)
            # Rebuild typed observation presentation after demoting acceptance.
            if "observation_id" in result and "review_status" in result and "presentation" in result:
                from dataclasses import asdict
                from utils.implant_reconstruction import seed_presentation
                result["presentation"] = asdict(seed_presentation(result["review_status"],
                    result.get("axis_lps") is not None, result.get("dimensions") is not None))
            if "counts" in result and isinstance(result.get("reconstruction"), dict):
                states = [row.get("review_status") for row in result["reconstruction"].get("observations", [])]
                result["counts"] = {**result["counts"], "accepted_count": states.count("accepted"),
                    "review_needed_count": states.count("review_needed"), "excluded_count": states.count("rejected")}
            if "candidate_sha256" in result and "placement_id" in result and "matrix" in result:
                from web.guide_placement import _placement_signature
                result["candidate_sha256"] = _placement_signature(result)
            return result
        if isinstance(value, list):
            return [remap(item, field, depth + 1) for item in value]
        if isinstance(value, str):
            if value == old_session:
                return new_session
            if old_owner and value == old_owner and field in {"owner_id", "user_id", "actor_id"}:
                return owner
            if value in operation_remap:
                return operation_remap[value]
            normalized = value.replace("\\", "/")
            for old, new in namespace_remap.items():
                normalized = normalized.replace("implant_reconstruction/" + old + "/", "implant_reconstruction/" + new + "/")
            if old_root and (normalized == old_root or normalized.startswith(old_root + "/")):
                suffix = normalized[len(old_root):].lstrip("/")
                return str(root / suffix)
            # Schema-1 Linux/Windows backups predate source_root metadata.
            marker = "/" + old_session + "/"
            if (normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized)) and marker in normalized:
                return str(root / normalized.split(marker, 1)[1])
            normalized = normalized.replace("/api/sessions/" + old_session + "/", "/api/sessions/" + new_session + "/")
            if field in {"receipt_token", "human_timepoint_confirmation"}:
                return ""
            return normalized if normalized != value.replace("\\", "/") or "\\" in value and (
                field in {"path", "$array", "ct_path", "ct_image_path", "source_path", "volume_path"}) else value
        return value
    return remap


def _repair_checksums(root, values, *, destination_root=None):
    visited, visiting = set(), set()
    def rewrite(relative):
        if relative in visited:
            return
        if relative in visiting:
            raise TimepointIntegrityError("Imported checksum references contain a cycle")
        visiting.add(relative)
        value = values[relative]
        def rehash(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    if key != "acquisition_files":
                        rehash(child)
                if isinstance(item.get("path"), str) and "sha256" in item:
                    path = Path(item["path"])
                    if path.is_absolute():
                        anchor = destination_root or root
                        if not path.is_relative_to(anchor):
                            raise TimepointIntegrityError("An imported checksum path escapes its owned root")
                        key = path.relative_to(anchor).as_posix()
                    else:
                        key = _relative(item["path"].replace("\\", "/"))
                    candidate = _safe_workspace_child(root, key)
                    if not candidate.is_file():
                        raise TimepointIntegrityError("An immutable imported resource is missing")
                    if key in values:
                        if key == relative:
                            raise TimepointIntegrityError("Self-referential immutable checksum")
                        rewrite(key)
                    item["sha256"] = sha256(candidate)
            elif isinstance(item, list):
                for child in item:
                    rehash(child)
        rehash(value)
        _atomic_bytes(root / relative, _encoded(value))
        visiting.remove(relative)
        visited.add(relative)
    for relative in list(values):
        rewrite(relative)


def _registration_database(path, remap):
    """Rebuild known native job rows; retain the live queryable history."""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA trusted_schema=OFF")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise TimepointIntegrityError("Registration job database is corrupt")
        objects = connection.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if [(row["name"], row["type"]) for row in objects] != [("jobs", "table")]:
            raise TimepointIntegrityError("Unsupported registration journal schema or executable SQL objects")
        columns = [row[1] for row in connection.execute("PRAGMA table_info(jobs)")]
        if columns != ["request_id", "payload_hash", "status", "record", "owner_pid"]:
            raise TimepointIntegrityError("Unsupported registration job columns")
        records = connection.execute("SELECT * FROM jobs").fetchall()
        if len(records) > 64:
            raise TimepointIntegrityError("Registration job journal exceeds its record limit")
    replacement = path.with_suffix(".rebound.sqlite3")
    try:
        with sqlite3.connect(replacement) as connection:
            connection.execute("CREATE TABLE jobs (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL, owner_pid INTEGER NOT NULL)")
            for row in records:
                if len(row["record"].encode()) > MAX_JSON_BYTES:
                    raise TimepointIntegrityError("Registration job record is oversized")
                value = remap(_json(row["record"]))
                value.update(auto_resumed=False, import_requires_revalidation=True)
                if value.get("status") not in {"completed", "failed", "cancelled", "interrupted", "timed_out", "stale"}:
                    value["status"] = "interrupted"
                payload = value.get("request")
                payload_hash = hashlib.sha256(_encoded(payload)).hexdigest() if payload is not None else row["payload_hash"]
                connection.execute("INSERT INTO jobs VALUES (?,?,?,?,?)",
                    (row["request_id"], payload_hash, value["status"], _encoded(value).decode(), -1))
            connection.commit()
        os.replace(replacement, path)
    finally:
        replacement.unlink(missing_ok=True)


def _commit_import(raw, owner, session_id, root, staging, metadata, remap, title):
    """Files precede one SQLite transaction; no selectable half-imported case."""
    catalog = metadata["catalog"]
    catalog_path = "timepoints/catalog/import-" + uuid.uuid4().hex + ".json"
    _atomic_bytes(staging / catalog_path, _encoded(catalog))
    imported_at = time.time()
    session = metadata.get("session") or {}
    total = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    with raw._quota_commit_lock(owner):
        raw.ensure_capacity(owner, total)
        if root.exists() or not root.is_relative_to(raw.workspaces_dir.resolve()):
            raise TimepointIntegrityError("New import workspace destination is unavailable")
        root.parent.mkdir(parents=True, exist_ok=True)
        moved = False
        committed = False
        try:
            # Atomic directory publication within the same runtime filesystem.
            os.replace(staging, root)
            moved = True
            raw._fsync_tree(root)
            raw._fsync_directory(root.parent)
            with raw._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO case_sessions(id,user_id,title,created_at,updated_at,last_accessed_at,revision,recovery_status,storage_status) VALUES(?,?,?,?,?,?,?,'ready','active')",
                    (session_id, owner, title or session.get("title") or "Imported patient",
                     imported_at, imported_at, imported_at, int(session.get("revision", 0))))
                connection.execute("INSERT INTO timepoint_catalogs VALUES(?,?,?,?,?)",
                    (session_id, owner, catalog["catalog_revision"], catalog_path, _encoded(catalog).decode()))
                versions = {}
                for row in metadata.get("state_versions") or []:
                    versions[(row["timepoint_id"], row["state_revision"])] = _json(row["state_ref_json"])
                for target, item in catalog["items"].items():
                    if item.get("state_ref"):
                        versions[(target, item["state_revision"])] = item["state_ref"]
                for (target, number), ref in versions.items():
                    connection.execute("INSERT INTO timepoint_state_versions VALUES(?,?,?,?)",
                        (session_id, target, number, _encoded(ref).decode()))
                ledgers = metadata.get("ledgers") or {}
                for original in ledgers.get("timepoint_operations") or []:
                    row = remap(original)
                    value = remap(_json(original["operation_json"]))
                    if row["state"] in {"running", "queued"}:
                        row["state"] = "interrupted"
                    value.update(state=row["state"], auto_resumed=False, import_requires_revalidation=True)
                    connection.execute("INSERT INTO timepoint_operations VALUES(?,?,?,?,?,?,?,?,?)",
                        (row["operation_id"], owner, session_id, row["timepoint_id"], row["state"],
                         -1, "", row["updated_at"], _encoded(value).decode()))
                for original in ledgers.get("review_comments") or []:
                    row = remap(original)
                    connection.execute("INSERT INTO review_comments(user_id,session_id,author,body,anchor_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (owner, session_id, row["author"], row["body"], _encoded(remap(_json(row["anchor_json"]))).decode(),
                         row["status"], row["created_at"], row["updated_at"]))
                for original in ledgers.get("audit_events") or []:
                    row = remap(original)
                    connection.execute("INSERT INTO audit_events(user_id,session_id,action,detail_json,created_at) VALUES(?,?,?,?,?)",
                        (owner, session_id, row["action"], _encoded(remap(_json(row["detail_json"]))).decode(), row["created_at"]))
                for row in ledgers.get("context_token_accounting") or []:
                    connection.execute("INSERT INTO context_token_accounting VALUES(?,?,?)",
                        (session_id, owner, _encoded(remap(_json(row["state_json"]))).decode()))
                connection.execute("INSERT INTO audit_events(user_id,session_id,action,detail_json,created_at) VALUES(?,?,?,?,?)",
                    (owner, session_id, "timepoint.bundle_imported", _encoded({
                        "source_session_id": metadata.get("import_source_session_id"),
                        "reviews_require_revalidation": True, "tasks_auto_resumed": False}).decode(), imported_at))
            committed = True
        finally:
            if moved and not committed:
                # Exact fresh UUID root, no existing Session or caller path.
                shutil.rmtree(root)
            raw.invalidate_storage_usage(owner)
    return raw.get_session(owner, session_id)


def import_bundle(store, owner, source, *, title=None):
    """Validate/checksum/rebind all bytes before atomically publishing a Session.

    Scope-local image/timepoint/observation IDs retain their durable identity;
    new owner/Session and globally unique operation IDs fence all references.
    Numerical/observational history is retained. Review authority, job execution
    and current scientific-dose claims are explicitly invalidated.
    """
    raw = getattr(store, "raw", store)
    if not raw.get_user_by_id(owner):
        from web.workspace_store import WorkspaceNotFound
        raise WorkspaceNotFound("Account is unavailable")
    if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 160):
        raise TimepointError("Imported Session title must contain 1 to 160 characters")
    try:
        with zipfile.ZipFile(source) as archive:
            metadata, paths = _checked_archive(archive)
            total = sum(row["bytes"] for row in paths.values())
            # The lock protects staging and final publication from concurrent
            # quota-consuming imports/uploads, even outside the quota walker.
            with raw._quota_commit_lock(owner), tempfile.TemporaryDirectory(
                    prefix="validated-timepoint-import-", dir=raw.staging_dir) as temporary:
                raw.ensure_capacity(owner, total * 2 + 1024 * 1024)
                container = Path(temporary)
                staging = container / "workspace"
                staging.mkdir()
                for relative, row in paths.items():
                    path = _safe_workspace_child(staging, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    digest, copied = hashlib.sha256(), 0
                    with archive.open("workspace/" + relative) as stream, path.open("xb") as output:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            copied += len(chunk)
                            if copied > row["bytes"]:
                                raise TimepointIntegrityError("Resource exceeds its declared size")
                            output.write(chunk)
                            digest.update(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if copied != row["bytes"] or digest.hexdigest() != row["sha256"]:
                        raise TimepointIntegrityError("Bundle resource checksum does not match")
                values = _validate_graph(staging, metadata)
                session_id = uuid.uuid4().hex
                root = raw.workspace_root(owner, session_id)
                namespace_remap = {}
                for relative, value in values.items():
                    if relative.startswith("artifacts/implant_reconstruction/") and relative.endswith("/index.json"):
                        scope = {**value["scope"], "owner_id": owner, "session_id": session_id}
                        namespace_remap[relative.split("/")[2]] = hashlib.sha256(_encoded(scope)).hexdigest()[:32]
                operation_remap = {row["operation_id"]: uuid.uuid4().hex
                    for row in (metadata.get("ledgers") or {}).get("timepoint_operations", [])}
                remap = _remapper(metadata, owner, session_id, root, namespace_remap, operation_remap)
                for old, new in namespace_remap.items():
                    original = staging / "artifacts" / "implant_reconstruction" / old
                    os.replace(original, original.with_name(new))
                rebound = {}
                for relative, value in values.items():
                    key = relative
                    for old, new in namespace_remap.items():
                        key = key.replace("implant_reconstruction/" + old + "/", "implant_reconstruction/" + new + "/")
                    rebound[key] = remap(value)
                    _atomic_bytes(staging / key, _encoded(rebound[key]))
                for path in staging.rglob("jobs.sqlite3"):
                    if "guide-registration" in path.parts:
                        _registration_database(path, remap)
                _repair_checksums(staging, rebound, destination_root=root)
                # Recompute external SQLite catalog/ledger edges last.
                imported = copy.deepcopy(metadata)
                imported["import_source_session_id"] = metadata["session_id"]
                imported["session_id"], imported["owner_id"] = session_id, owner
                imported["catalog"] = remap(metadata["catalog"])
                for item in imported["catalog"]["items"].values():
                    for ref in [item.get("state_ref"), *item["state_history"]]:
                        if ref is not None:
                            ref["sha256"] = sha256(staging / ref["path"])
                for row in imported.get("state_versions") or []:
                    ref = remap(_json(row["state_ref_json"]))
                    ref["sha256"] = sha256(staging / _relative(ref["path"]))
                    row["state_ref_json"] = _encoded(ref).decode()
                _validate_graph(staging, imported)
                return _commit_import(raw, owner, session_id, root, staging, imported, remap, title)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, TypeError, ValueError, sqlite3.DatabaseError, RecursionError) as exc:
        if isinstance(exc, (TimepointError, TimepointIntegrityError)):
            raise
        raise TimepointIntegrityError("Complete workspace exchange could not be validated") from exc
