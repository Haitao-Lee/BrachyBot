"""Dedicated deployment/runtime provisioning. Never touch production directories."""
from __future__ import annotations
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

from .core import Blocked, atomic_json, child, digest, load_json, sha256, utc


def link_owned(link, target):
    target.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise Blocked("RUNTIME_LINK_MISMATCH", str(link))
    elif link.exists():
        raise Blocked("RUNTIME_PATH_ALREADY_EXISTS", str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def provision(storage, cfg):
    """Copy tracked product code; link only pinned model assets, never patient runtimes."""
    storage.initialize()
    source = Path(cfg["source_repository"]).resolve()
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != cfg["product_revision"]:
        raise Blocked("PRODUCT_REVISION_DRIFT")
    # Refuse relevant tracked modifications rather than accidentally measure HEAD + changes.
    if subprocess.check_output(["git", "-C", str(source), "diff", "HEAD", "--name-only"], text=True).strip():
        raise Blocked("PRODUCT_DIRTY_TRACKED_CODE", "Freeze a reviewed checkout before provisioning")
    destination = Path(cfg["deployment_checkout"]).resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        raise Blocked("DEPLOYMENT_SOURCE_OVERLAP")
    if storage.mount == destination or storage.mount in destination.parents:
        raise Blocked("CODE_CHECKOUT_REQUIRES_LOCAL_SYMLINK_CAPABLE_FILESYSTEM")
    marker = storage.path("deployment/deployment.json")
    metadata = Path(cfg["metadata_runtime"]).resolve()
    if source in metadata.parents or metadata == source or metadata == Path("/"):
        raise Blocked("UNSAFE_METADATA_RUNTIME")
    if destination.exists() and not marker.is_file():
        raise Blocked("UNOWNED_DEPLOYMENT_DIRECTORY")
    files = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode().split("\0")
    if not marker.exists():
        destination.mkdir(parents=True)
        inventory = []
        for name in files:
            if not name or name.startswith((".git/", ".claude/", "benchmarks/", "tests/", "docs/")):
                continue
            src = child(source, name)
            if not src.is_file():
                continue
            if src.name.startswith(".env") or src.suffix in {".sqlite3", ".db", ".nii", ".dcm"}:
                raise Blocked("SENSITIVE_TRACKED_FILE", name)
            storage.check()
            dst = child(destination, name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix in {".pth", ".pt", ".onnx", ".ckpt"}:
                dst.symlink_to(src)
            else:
                shutil.copy2(src, dst)
            inventory.append({"path": name, "sha256": sha256(src), "linked_model": dst.is_symlink()})
        atomic_json(marker, {"revision": head, "source": str(source), "deployment": str(destination),
                    "metadata_runtime": str(metadata), "files": inventory, "created_at": utc()})
    frozen = load_json(marker)
    if frozen["revision"] != head or frozen["metadata_runtime"] != str(metadata):
        raise Blocked("DEPLOYMENT_RECIPE_CHANGED")
    metadata.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(metadata, 0o700)
    except OSError:
        pass
    own = metadata / "cohort-owner.json"
    if own.exists() and load_json(own).get("experiment_root") != str(storage.base):
        raise Blocked("METADATA_RUNTIME_BELONGS_TO_OTHER_EXPERIMENT")
    if not own.exists() and any(p.name not in {"cohort-owner.json"} for p in metadata.iterdir()):
        raise Blocked("METADATA_RUNTIME_NOT_EMPTY")
    atomic_json(own, {"experiment_root": str(storage.base), "revision": head})
    for name in ("workspaces", "trash", ".staging"):
        link_owned(metadata / name, storage.path("backend/" + name))
    # Existing tracked data paths are not silently replaced or deleted.
    for name in ("uploads", "output", "outputs", "runtime", ".runtime"):
        link_owned(destination / name, storage.path("backend/legacy/" + name))
    for asset in cfg.get("model_assets", []):
        src = Path(asset["source"]).resolve()
        dst = child(destination, asset["relative_path"])
        if not src.is_file() or sha256(src) != asset["sha256"]:
            raise Blocked("MODEL_ASSET_CHANGED", str(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            if sha256(dst) != asset["sha256"]:
                raise Blocked("MODEL_ASSET_DESTINATION_CONFLICT", asset["relative_path"])
        else:
            dst.symlink_to(src)
    atomic_json(storage.path("deployment/model-assets.json"), cfg.get("model_assets", []))
    return frozen


def validate_runtime(storage, cfg):
    storage.check()
    marker = load_json(storage.path("deployment/deployment.json"))
    if marker["revision"] != cfg["product_revision"]:
        raise Blocked("DEPLOYMENT_VERSION_DRIFT")
    if marker["deployment"] != str(Path(cfg["deployment_checkout"]).resolve()) or marker["metadata_runtime"] != str(Path(cfg["metadata_runtime"]).resolve()):
        raise Blocked("DEPLOYMENT_PATH_DRIFT")
    runtime = Path(cfg["metadata_runtime"]).resolve()
    if load_json(runtime / "cohort-owner.json").get("experiment_root") != str(storage.base):
        raise Blocked("RUNTIME_OWNERSHIP_MISMATCH")
    for name in ("workspaces", "trash", ".staging"):
        if (runtime / name).resolve() != storage.path("backend/" + name).resolve():
            raise Blocked("BULK_RUNTIME_NOT_ON_NAS", name)
    for entry in marker["files"]:
        if sha256(child(marker["deployment"], entry["path"])) != entry["sha256"]:
            raise Blocked("DEPLOYMENT_FILE_CHANGED", entry["path"])
    if load_json(storage.path("deployment/model-assets.json")) != cfg.get("model_assets", []):
        raise Blocked("MODEL_ASSET_RECIPE_CHANGED")
    for asset in cfg.get("model_assets", []):
        if sha256(child(marker["deployment"], asset["relative_path"])) != asset["sha256"]:
            raise Blocked("MODEL_ASSET_CHANGED")
    return marker


def validate_live_service(storage, cfg, allow_shutdown_pending=False):
    """A healthy HTTP endpoint alone cannot identify the intended isolated service."""
    import psutil
    from urllib.parse import urlsplit
    marker = validate_runtime(storage, cfg)
    service = load_json(storage.path("backend/service.json"))
    if service.get("shutdown_status") == "PENDING" and not allow_shutdown_pending:
        raise Blocked("ISOLATED_SERVICE_SHUTDOWN_PENDING")
    if service.get("url") != cfg["deployment_url"] or service.get("runtime") != cfg["metadata_runtime"]:
        raise Blocked("LIVE_SERVICE_RECIPE_MISMATCH")
    try:
        process = psutil.Process(service["pid"])
        if abs(process.create_time() - service["process_created_at"]) > .01 or Path(process.cwd()).resolve() != Path(marker["deployment"]).resolve():
            raise Blocked("LIVE_SERVICE_PROCESS_REUSED")
        if not any(Path(x).name == "server_entry.py" for x in process.cmdline()):
            raise Blocked("LIVE_SERVICE_COMMAND_MISMATCH")
        env = process.environ()
        if env.get("BRACHYBOT_RUNTIME_DIR") != cfg["metadata_runtime"]:
            raise Blocked("LIVE_SERVICE_RUNTIME_MISMATCH")
        port = urlsplit(cfg["deployment_url"]).port
        if not any(c.status == psutil.CONN_LISTEN and c.laddr.port == port for c in process.net_connections(kind="inet")):
            raise Blocked("LIVE_SERVICE_NOT_LISTENING")
    except (psutil.Error, KeyError) as exc:
        raise Blocked("LIVE_SERVICE_NOT_VERIFIABLE", str(exc)) from exc
    return {"pid": service["pid"], "revision": marker["revision"], "url": service["url"], "status": "IDENTITY_VERIFIED"}


def validate_account_quota(cfg, minimum):
    """Metadata-only read of the experiment's own DB; never retrieve password hashes."""
    import sqlite3
    username = os.environ.get(cfg.get("username_env", "COHORT_USERNAME"))
    if not username:
        raise Blocked("EXPERIMENT_USERNAME_MISSING")
    database = Path(cfg["metadata_runtime"]) / "brachybot.sqlite3"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT is_active, storage_quota_bytes FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if not row or row[0] != 1 or row[1] < minimum:
        raise Blocked("EXPERIMENT_ACCOUNT_QUOTA_NOT_READY")
    return {"status": "PASS", "quota_bytes": row[1]}


def set_account_quota(storage, cfg):
    """Setup-only metadata change after registration, with the isolated service stopped."""
    import psutil
    import sqlite3
    validate_runtime(storage, cfg)
    budget = load_json(cfg["budget_path"])
    quota = budget.get("approved_account_quota_bytes")
    if budget.get("status") != "APPROVED" or not budget.get("owner") or type(quota) is not int or quota <= 0:
        raise Blocked("ACCOUNT_QUOTA_BUDGET_NOT_APPROVED")
    service_path = storage.path("backend/service.json")
    if service_path.is_file():
        s = load_json(service_path)
        try:
            process = psutil.Process(s["pid"])
            if abs(process.create_time() - s["process_created_at"]) < .01:
                raise Blocked("STOP_ISOLATED_SERVICE_BEFORE_QUOTA_SETUP")
        except psutil.NoSuchProcess:
            pass
    username = os.environ.get(cfg.get("username_env", "COHORT_USERNAME"))
    if not username:
        raise Blocked("EXPERIMENT_USERNAME_MISSING")
    database = Path(cfg["metadata_runtime"]) / "brachybot.sqlite3"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True) as db:
        row = db.execute("SELECT id, is_active FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if not row or row[1] != 1:
            raise Blocked("REGISTER_EXPERIMENT_ACCOUNT_FIRST")
        db.execute("UPDATE users SET storage_quota_bytes = ?, updated_at = ? WHERE id = ?", (quota, time.time(), row[0]))
    receipt = {"status": "QUOTA_CONFIGURED", "quota_bytes": quota, "experiment_id": cfg["experiment_id"],
               "budget_hash": digest(budget), "setup_at": utc(), "production_accounts_modified": False}
    atomic_json(storage.path("protocol/account-quota-setup.json"), receipt)
    return receipt


def serve(storage, cfg):
    """Foreground supervised isolated service; terminate only its own process group."""
    from urllib.parse import urlsplit
    marker = validate_runtime(storage, cfg)
    url = urlsplit(cfg["deployment_url"])
    if url.hostname not in {"127.0.0.1", "localhost"} or not url.port or url.port in {8080, 18082}:
        raise Blocked("ISOLATED_SERVICE_MUST_BE_LOOPBACK_NEW_PORT")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", url.port)) == 0:
            raise Blocked("PORT_ALREADY_IN_USE")
    env = {**os.environ, "BRACHYBOT_RUNTIME_DIR": cfg["metadata_runtime"],
           "BRACHYBOT_ARCHIVE_ROOT": str(storage.path("archive/backend")),
           "COHORT_COOKIE_NAME": "bb_cohort_" + digest(cfg["experiment_id"])[:12],
           "TMPDIR": str(storage.path("tmp")), "TEMP": str(storage.path("tmp")),
           "BRACHYBOT_SERVER_LOG": str(storage.path("backend/server.log"))}
    command = [cfg["product_python"], str(Path(__file__).with_name("server_entry.py")), marker["deployment"], str(url.port)]
    with storage.lease("isolated-server"), storage.path("backend/launcher.log").open("ab") as log:
        process = subprocess.Popen(command, cwd=marker["deployment"], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        atomic_json(storage.path("backend/service.json"), {"pid": process.pid, "url": cfg["deployment_url"],
                    "process_created_at": __import__("psutil").Process(process.pid).create_time(),
                    "runtime": cfg["metadata_runtime"], "revision": marker["revision"], "started_at": utc()})
        try:
            while process.poll() is None:
                storage.check()
                time.sleep(2)
            if process.returncode:
                raise Blocked("ISOLATED_SERVER_EXITED", str(process.returncode))
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    # The product intentionally defers shutdown for active
                    # operations. Do not turn a graceful request into SIGKILL.
                    info = load_json(storage.path("backend/service.json"))
                    atomic_json(storage.path("backend/service.json"), {**info, "shutdown_status": "PENDING"})
                    raise Blocked("ISOLATED_SHUTDOWN_PENDING", "Own process remains alive; reconcile its task before any new mutation")
            # No production PID lookup, restart, account migration, or cleanup.
