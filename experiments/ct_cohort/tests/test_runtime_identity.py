from pathlib import Path
from types import SimpleNamespace
import os
import sqlite3
import tempfile
import psutil
import pytest

from brachycohort.core import Blocked, atomic_json
import brachycohort.runtime as runtime


@pytest.mark.parametrize("wrong", [None, "pid_reuse", "cwd", "command", "environment", "listener", "url"])
def test_live_service_identity_not_just_http(storage, monkeypatch, wrong):
    cfg = {"deployment_url": "http://127.0.0.1:18086", "metadata_runtime": "/owned/runtime"}
    atomic_json(storage.path("backend/service.json"), {"pid": 123, "url": cfg["deployment_url"] if wrong != "url" else "http://127.0.0.1:8080",
                "runtime": cfg["metadata_runtime"], "process_created_at": 100})
    monkeypatch.setattr(runtime, "validate_runtime", lambda *a: {"deployment": "/owned/code", "revision": "test"})
    class Process:
        def create_time(self): return 101 if wrong == "pid_reuse" else 100
        def cwd(self): return "/wrong" if wrong == "cwd" else "/owned/code"
        def cmdline(self): return ["python", "other.py" if wrong == "command" else "server_entry.py"]
        def environ(self): return {"BRACHYBOT_RUNTIME_DIR": "/production" if wrong == "environment" else "/owned/runtime"}
        def net_connections(self, kind):
            return [] if wrong == "listener" else [SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=18086))]
    monkeypatch.setattr(psutil, "Process", lambda pid: Process())
    if wrong:
        with pytest.raises(Blocked):
            runtime.validate_live_service(storage, cfg)
    else:
        assert runtime.validate_live_service(storage, cfg)["status"] == "IDENTITY_VERIFIED"


def test_quota_setup_changes_only_owned_metadata(storage, monkeypatch):
    with tempfile.TemporaryDirectory(prefix="cohort-quota-test-", dir="/dev/shm") as directory:
        cfg = {"metadata_runtime": directory, "username_env": "COHORT_TEST_ACCOUNT", "experiment_id": "test"}
        monkeypatch.setenv("COHORT_TEST_ACCOUNT", "synthetic")
        dbpath = Path(directory) / "brachybot.sqlite3"
        with sqlite3.connect(dbpath) as db:
            db.execute("CREATE TABLE users(id TEXT, username TEXT, is_active INT, storage_quota_bytes INT, updated_at REAL, password_hash TEXT)")
            db.execute("INSERT INTO users VALUES ('1','synthetic',1,100,0,'DO_NOT_READ')")
        with pytest.raises(Blocked, match="ACCOUNT_QUOTA_NOT_READY"):
            runtime.validate_account_quota(cfg, 200)
        budget = storage.path("protocol/budget.json")
        atomic_json(budget, {"status": "APPROVED", "owner": "test", "approved_account_quota_bytes": 200})
        cfg["budget_path"] = str(budget)
        monkeypatch.setattr(runtime, "validate_runtime", lambda *a: {})
        assert runtime.set_account_quota(storage, cfg)["quota_bytes"] == 200
        assert runtime.validate_account_quota(cfg, 200)["status"] == "PASS"
        with sqlite3.connect(dbpath) as db:
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
