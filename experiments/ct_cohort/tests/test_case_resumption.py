"""Small fault-injection regressions; no real CT cohort/model/GPU execution."""
import asyncio
import copy
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from brachycohort.core import Blocked, atomic_json, digest, load_json, sha256
from brachycohort.cohort import execution_recipe
from brachycohort.progress import chain, save_settlement, settlement, state
from brachycohort.recovery import recover_case, recover_pending, wait_case_idle
from test_core import config
from test_census_scheduling import candidate, frame_cfg, frozen, record_terminal
from test_protocol_and_collection import frozen_documents


def started(storage, cfg, doc, value, name="first", retry_of=None):
    from brachycohort.cohort import execution_recipe
    row, profile, ph, _ = value
    rec = execution_recipe(row, ph, cfg, "browser-chat", doc)
    rh = digest(rec)
    root = storage.path("runs/" + rh + "/" + name)
    record = {"recipe": rec, "recipe_hash": rh, "row": row, "profile": profile,
              "resumability_version": 1, **({"retry_of": retry_of, "first_attempt_id": "first"} if retry_of else {})}
    atomic_json(root / "attempt.json", record)
    return root, record


def proof(root, state="RETRY_READY", **extra):
    rec = load_json(root / "attempt.json")
    dest = root / "recoveries" / "proof"
    result = {"attempt_id": root.name, "recipe_hash": rec["recipe_hash"], "state": state,
              "no_server_work_submitted": True, **extra}
    save_settlement(root, dest, result)
    return result


@pytest.mark.parametrize("dead", [True, False])
def test_dead_runner_lock_recovery_preserves_live_owner(config, monkeypatch, dead):
    from brachycohort.core import Storage
    from brachycohort import leases
    storage = Storage(config)
    storage.initialize()
    path = storage.path("locks/" + digest("gpu"))
    atomic_json(path / "owner.json", {"name": "gpu", "host": socket.gethostname(), "pid": 99999999})
    monkeypatch.setattr(leases, "dead_owner", lambda _: dead)
    if dead:
        with storage.lease("gpu"):
            assert load_json(path / "owner.json")["token"]
        assert not path.exists()
        assert list((path.parent / "retired").glob("*/reclaimed.json"))
    else:
        with pytest.raises(Blocked, match="EXPERIMENT_LOCKED"):
            with storage.lease("gpu"):
                pass
        assert load_json(path / "owner.json")["pid"] == 99999999


def test_owner_proof_uses_host_boot_and_pid_creation(monkeypatch):
    import psutil
    from brachycohort.leases import dead_owner, identity
    owner = identity("test")
    assert not dead_owner(owner)
    assert not dead_owner({**owner, "host": "another-host"})
    assert dead_owner({**owner, "boot_id": "previous-boot"})
    assert dead_owner({**owner, "process_created_at": owner["process_created_at"] - 100})
    assert not dead_owner({"pid": owner["pid"], "host": owner["host"]})  # live legacy PID is ambiguous
    def missing(_):
        raise psutil.NoSuchProcess(99999999)
    monkeypatch.setattr(psutil, "Process", missing)
    assert dead_owner(owner)


def test_killed_validation_runner_lease_is_recovered(tmp_path):
    """Kill only our synthetic child; no product/server/model process is involved."""
    import select
    import subprocess
    import sys
    from brachycohort.leases import recoverable_lease
    path = tmp_path / "synthetic-gpu-lock"
    code = ("import signal,sys; from pathlib import Path; from brachycohort.leases import recoverable_lease; "
            "lease=recoverable_lease(Path(sys.argv[1]),'synthetic',lambda:None); lease.__enter__(); "
            "print('LOCKED',flush=True); signal.pause()")
    child = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 15)[0]
        assert child.stdout.readline().strip() == "LOCKED"
        owner = load_json(path / "owner.json")
        child.kill()
        child.wait(timeout=15)
        with recoverable_lease(path, "synthetic", lambda: None):
            assert load_json(path / "owner.json")["pid"] != owner["pid"]
        assert list((path.parent / "retired").glob("*/reclaimed.json"))
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)
        child.stdout.close()


@pytest.mark.parametrize("owner", [None, []])
def test_malformed_lease_owner_is_not_stolen(tmp_path, owner):
    from brachycohort.leases import recoverable_lease
    path = tmp_path / "lock"
    atomic_json(path / "owner.json", owner)
    with pytest.raises(Blocked, match="EXPERIMENT_LOCKED"):
        with recoverable_lease(path, "test", lambda: None):
            pass
    assert load_json(path / "owner.json") == owner


def test_interrupted_before_case_creation_becomes_only_current_case_retry(storage, frame_cfg, approved_profile, monkeypatch):
    from brachycohort.cohort import pending_cases
    values = [candidate(i, approved_profile) for i in range(3)]
    doc = frozen(identifiers=["r0", "r1", "r2"])
    record_terminal(storage, frame_cfg, doc, values[0])
    first = storage.path("runs/" + digest(execution_recipe(values[0][0], values[0][2], frame_cfg, "browser-chat", doc)) + "/attempt/terminal_result.json")
    old = sha256(first)
    root, rec = started(storage, frame_cfg, doc, values[1])
    monkeypatch.setattr("brachycohort.runner.original_sources_unchanged", lambda *_: None)
    result = asyncio.run(recover_case(root, frame_cfg, storage, doc))
    assert result["state"] == "RETRY_READY" and not result["planning_resubmitted"]
    assert load_json(root / "terminal_result.json")["workflow_completion"] == "UNKNOWN"
    cases, skipped = pending_cases(frame_cfg, storage, doc, {v[0]["row_id"]: v for v in values}, "browser-chat", 1)
    assert skipped == 1 and cases[0][0]["row_id"] == "r1"
    assert sha256(first) == old


def test_repeated_interruption_chain_and_first_attempt_denominator(storage, frame_cfg, approved_profile):
    from brachycohort.analysis import results
    value = candidate(1, approved_profile)
    doc = frozen(identifiers=["r1"])
    first, record = started(storage, frame_cfg, doc, value)
    atomic_json(first / "terminal_result.json", {"recipe_hash": record["recipe_hash"], "attempt_id": "first",
                "row_id": "r1", "dataset": "synthetic", "cluster_id": "c1", "arm": "browser-chat",
                "status": "INTERRUPTED", "interrupted": True, "workflow_completion": "UNKNOWN", "elapsed_s": None})
    original = sha256(first / "terminal_result.json")
    proof(first)
    second, _ = started(storage, frame_cfg, doc, value, "second", "first")
    proof(second)
    third, _ = started(storage, frame_cfg, doc, value, "third", "second")
    proof(third, "SETTLED", recovered_software_completion="PASS", destination=str(third / "recoveries/proof"))
    assert len(chain(first.parent, record["recipe_hash"])) == 3
    assert state(storage, record["recipe_hash"]) == "TERMINAL"
    rows = results(storage.base)
    assert len(rows) == 1 and rows[0]["workflow_completion"] == "UNKNOWN"
    assert rows[0]["eventual_software_completion"] == "PASS" and rows[0]["recovery_attempts"] == 2
    assert sha256(first / "terminal_result.json") == original


def test_recovery_evidence_tamper_blocks_resume(storage, frame_cfg, approved_profile):
    root, _ = started(storage, frame_cfg, frozen(), candidate(1, approved_profile))
    proof(root)
    atomic_json(root / "recoveries/proof/recovery.json", {"state": "SETTLED"})
    with pytest.raises(Blocked, match="RECOVERY_LINK_CHANGED"):
        settlement(root)


def test_unlinked_duplicate_or_unauthorized_retry_is_blocked(storage, frame_cfg, approved_profile):
    value = candidate(1, approved_profile)
    doc = frozen()
    root, rec = started(storage, frame_cfg, doc, value)
    started(storage, frame_cfg, doc, value, "second", "first")
    with pytest.raises(Blocked, match="RECIPE_RETRY_NOT_AUTHORIZED"):
        chain(root.parent, rec["recipe_hash"])


@pytest.mark.parametrize("operation, task, allowed", [
    ("running", None, False), ("ready", "running", False), (None, "completed", False),
    ("ready", "completed", True), ("ready", None, True)])
async def test_wait_checks_both_server_fences(monkeypatch, operation, task, allowed):
    from brachycohort import recovery
    now = [0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: now[0])
    async def sleep(_):
        now[0] += 2
    monkeypatch.setattr(recovery.asyncio, "sleep", sleep)
    async def get(path):
        return {"task": {"session_id": "s", "task_id": "t", "status": task} if task else None} if path.endswith("task") else {"workspace": {"operation": {"state": operation}}}
    driver = SimpleNamespace(session_id="s", observer=SimpleNamespace(get=get), journal=SimpleNamespace(event=lambda *_a, **_k: None))
    if allowed:
        assert (await wait_case_idle(driver, "t", 10))["operation"] == "ready"
    else:
        with pytest.raises(Blocked, match="RECOVERY_SERVER_STILL_BUSY"):
            await wait_case_idle(driver, "t", 5)


async def test_task_identity_change_never_replays(monkeypatch):
    async def get(_):
        return {"task": {"session_id": "s", "task_id": "foreign", "status": "completed"}}
    driver = SimpleNamespace(session_id="s", observer=SimpleNamespace(get=get))
    with pytest.raises(Blocked, match="RECOVERY_TASK_CHANGED"):
        await wait_case_idle(driver, "original", 10)


async def test_recovery_recipe_change_blocks_before_browser(storage, frame_cfg, approved_profile):
    value = candidate(1, approved_profile)
    doc = frozen(identifiers=["r1"])
    started(storage, frame_cfg, doc, value)
    changed = copy.deepcopy(value)
    changed[0]["target_hash"] = "different"
    with pytest.raises(Blocked, match="RECOVERY_RECIPE_CHANGED"):
        await recover_pending(frame_cfg, storage, doc, {"r1": changed})


async def test_ctrl_c_records_interruption_without_cancelling_server(storage, frame_cfg, approved_profile, monkeypatch):
    from brachycohort import runner
    value = candidate(1, approved_profile)
    doc = frozen(identifiers=["r1"])
    entered = asyncio.Event()
    class Driver:
        def __init__(self, *args):
            self.root = args[-1]
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create_case(self):
            rec = load_json(self.root / "attempt.json")
            atomic_json(self.root / "session.json", {"session_id": "s", "recipe_hash": rec["recipe_hash"]})
            return "s"
        async def upload_and_promote(self, _):
            entered.set()
            await asyncio.Event().wait()
        async def cancel_and_reconcile(self):
            pytest.fail("Runner interruption must not assume/cancel the original server task")
    async def sample(_journal, stop):
        await stop.wait()
    monkeypatch.setattr(runner, "Browser", Driver)
    monkeypatch.setattr(runner, "original_sources_unchanged", lambda *_: None)
    monkeypatch.setattr("brachycohort.resources.sample", sample)
    task = asyncio.create_task(runner.attempt(frame_cfg, storage, *value[:3], "browser-chat", doc))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    outcome = load_json(next(storage.path("runs").glob("*/*/terminal_result.json")))
    assert outcome["status"] == "INTERRUPTED" and outcome["workflow_completion"] == "UNKNOWN"
    assert outcome["session_id"] == "s" and outcome["reconciliation"]


async def test_same_run_command_recovers_current_case_then_advances(storage, frozen_documents, approved_profile, monkeypatch):
    from contextlib import contextmanager
    from brachycohort import runner
    from brachycohort.gates import gates
    cfg, docs, save = frozen_documents
    cfg.update(experiment_id="test", product_revision="test", random_seed=0)
    docs["protocol"].update(study_kind="descriptive_stress", arms=["browser-chat"], row_ids=["r0", "r1", "r2"])
    docs["budget"]["max_attempts"] = 4
    save()
    doc = gates(cfg, storage, execute=True)
    values = [candidate(i, approved_profile) for i in range(3)]
    first = record_terminal(storage, cfg, doc, values[0])
    original_hash = sha256(first / "terminal_result.json")
    interrupted, _ = started(storage, cfg, doc, values[1])
    @contextmanager
    def lease(*_a, **_k):
        yield
    storage.lease, storage.initialize = lease, lambda: None
    monkeypatch.setattr(runner, "candidates", lambda *_: iter(values))
    monkeypatch.setattr(runner, "original_sources_unchanged", lambda *_: None)
    monkeypatch.setattr(runner, "validate_live_service", lambda *_: None)
    monkeypatch.setattr(runner, "validate_account_quota", lambda *_: None)
    called = []
    async def attempt(cfg, storage, row, profile, ph, mode, frozen):
        value = next(v for v in values if v[0]["row_id"] == row["row_id"])
        recipe_hash = digest(execution_recipe(row, ph, cfg, mode, frozen))
        prior = chain(storage.path("runs/" + recipe_hash), recipe_hash)
        root, rec = started(storage, cfg, frozen, value, "retry" if prior else "fresh", prior[-1][0].name if prior else None)
        outcome = {"recipe_hash": recipe_hash, "attempt_id": root.name, "status": "FAILED"}
        atomic_json(root / "terminal_result.json", outcome)
        called.append(row["row_id"])
        return outcome
    monkeypatch.setattr(runner, "attempt", attempt)
    assert (await runner.run(cfg, storage, 1))["reconciled_cases"] == 1
    assert called == ["r1"]  # does not restart r0 or skip the interrupted case
    assert (await runner.run(cfg, storage, 100))["new_attempts"] == 1
    assert called == ["r1", "r2"]
    assert (await runner.run(cfg, storage, None))["new_attempts"] == 0
    assert sha256(first / "terminal_result.json") == original_hash


async def test_legacy_lost_identity_never_guesses_case(storage, frame_cfg, approved_profile, monkeypatch):
    root, rec = started(storage, frame_cfg, frozen(), candidate(1, approved_profile))
    rec.pop("resumability_version")
    atomic_json(root / "attempt.json", rec)
    monkeypatch.setattr("brachycohort.runner.original_sources_unchanged", lambda *_: None)
    with pytest.raises(Blocked, match="LEGACY_INTERRUPTION_IDENTITY_UNRESOLVED"):
        await recover_case(root, frame_cfg, storage, frozen())
    assert not (root / "recovery_state.json").exists()
