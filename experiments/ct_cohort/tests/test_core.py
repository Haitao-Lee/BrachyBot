import json
from pathlib import Path
import pytest
from brachycohort import core
from brachycohort.core import Blocked, Storage, atomic_json, child, digest, finite, sanitize


@pytest.mark.parametrize("value", ["../escape", "/etc/passwd", "a/../../escape", "."])
def test_unsafe_children(tmp_path, value):
    with pytest.raises(Blocked):
        child(tmp_path, value)


def test_symlink_escape():
    # The deployed CIFS intentionally lacks symlinks. Exercise the escape on
    # volatile Linux tmpfs, not by weakening/skipping the path safety assertion.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="cohort-path-test-", dir="/dev/shm") as root:
        source, other = Path(root) / "base", Path(root) / "outside"
        source.mkdir()
        other.mkdir()
        (source / "link").symlink_to(other)
        with pytest.raises(Blocked):
            child(source, "link/out")


def test_atomic_and_recipe(tmp_path):
    p = tmp_path / "record.json"
    atomic_json(p, {"b": 2, "a": 1})
    assert json.loads(p.read_text()) == {"a": 1, "b": 2}
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1", None])
def test_finite_rejects_invalid(value):
    assert not finite(value)


def test_redact_without_erasing_clinical_metrics():
    assert sanitize({"authorization": "x", "dose": 42, "nested": {"api_key": "y"}}) == {
        "authorization": "[REDACTED]", "dose": 42, "nested": {"api_key": "[REDACTED]"}}


@pytest.fixture
def config(tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir()
    cfg = {"nas_mount": str(nas), "nas_source": "fixture", "nas_filesystems": ["cifs"],
           "result_root": str(nas / "results"), "source_root": str(nas / "CT"),
           "source_repository": str(tmp_path / "repo"), "metadata_runtime": str(tmp_path / "metadata"),
           "experiment_id": "test", "min_nas_free_bytes": 0, "min_local_free_bytes": 0}
    monkeypatch.setattr(core, "mounts", lambda: [{"mount_id": "1", "target": str(nas), "fstype": "cifs", "source": "fixture"}])
    return cfg


def test_nas_disappears(config, monkeypatch):
    s = Storage(config)
    monkeypatch.setattr(core, "mounts", lambda: [])
    with pytest.raises(Blocked, match="NAS_NOT_MOUNTED"):
        s.initialize()
    assert not s.base.exists()


def test_mount_replaced(config, monkeypatch):
    s = Storage(config)
    monkeypatch.setattr(core, "mounts", lambda: [{"mount_id": "2", "target": config["nas_mount"], "fstype": "cifs", "source": "fixture"}])
    with pytest.raises(Blocked, match="NAS_MOUNT_CHANGED"):
        s.check()


def test_sources_and_results_never_overlap(config):
    config["result_root"] = config["source_root"] + "/output"
    with pytest.raises(Blocked, match="RESULT_SOURCE_OVERLAP"):
        Storage(config)


def test_wal_not_on_nas(config):
    config["metadata_runtime"] = config["nas_mount"] + "/metadata"
    with pytest.raises(Blocked, match="SQLITE_RUNTIME_ON_NETWORK"):
        Storage(config).check()


def test_lock_never_stolen(config):
    s = Storage(config)
    s.initialize()
    with s.lease("account"):
        with pytest.raises(Blocked, match="EXPERIMENT_LOCKED"):
            with s.lease("account"):
                pass
