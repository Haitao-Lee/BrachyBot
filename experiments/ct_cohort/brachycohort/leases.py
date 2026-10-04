"""Recover dead local runner leases, never time-expire a live/foreign owner."""
import os
import socket
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import Blocked, atomic_json, child, digest, load_json, utc


def identity(name):
    import psutil
    return {"name": name, "pid": os.getpid(), "host": socket.gethostname(),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "process_created_at": psutil.Process().create_time(), "token": uuid.uuid4().hex,
            "created_at": utc()}


def dead_owner(owner):
    """PID reuse and host reboot are proofs; age/heartbeat absence is not."""
    import psutil
    if not isinstance(owner, dict) or owner.get("host") != socket.gethostname():
        return False
    pid = owner.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if owner.get("boot_id") and owner["boot_id"] != boot:
        return True
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        return False
    expected = owner.get("process_created_at")
    return type(expected) in (float, int) and abs(created - expected) > .001


@contextmanager
def local_guard(path):
    """Short, kernel-released guard shared by this UID's experiments on this host."""
    import fcntl
    directory = Path("/tmp") / ("brachycohort-lease-guards-" + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Blocked("UNSAFE_LOCAL_LEASE_GUARD")
    fd = os.open(directory / digest(str(path.resolve())), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise Blocked("UNSAFE_LOCAL_LEASE_GUARD")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


@contextmanager
def recoverable_lease(path, name, guard):
    path = Path(path)
    owner = identity(name)
    prepared = path.with_name(path.name + ".claim-" + owner["token"])
    with local_guard(path):
        guard()
        if path.exists():
            try:
                prior = load_json(path / "owner.json")
            except (OSError, ValueError):
                raise Blocked("EXPERIMENT_LOCKED", "Missing/unreadable owner; no unsafe lock theft") from None
            if not isinstance(prior, dict) or prior.get("name") != name or not dead_owner(prior):
                raise Blocked("EXPERIMENT_LOCKED", str(path))
            history = child(path.parent, "retired")
            history.mkdir(exist_ok=True)
            retired = history / (path.name + "-" + uuid.uuid4().hex)
            path.rename(retired)
            atomic_json(retired / "reclaimed.json", {"reclaimed_at": utc(), "new_owner": owner,
                        "reason": "proven_dead_local_runner_not_server_task_completion"})
        # An exposed active lease always has its identity, even if killed here.
        prepared.mkdir()
        atomic_json(prepared / "owner.json", owner)
        try:
            prepared.rename(path)
        except OSError:
            (prepared / "owner.json").unlink()
            prepared.rmdir()
            raise Blocked("EXPERIMENT_LOCKED", str(path)) from None
    try:
        yield path
    finally:
        with local_guard(path):
            guard()  # Never clean up through a detached NAS mount.
            current = load_json(path / "owner.json")
            if current.get("token") != owner["token"]:
                raise Blocked("LEASE_OWNER_CHANGED")
            history = child(path.parent, "retired")
            history.mkdir(exist_ok=True)
            # Atomic retirement avoids an owner-less active directory if killed on exit.
            path.rename(history / (path.name + "-released-" + owner["token"]))
