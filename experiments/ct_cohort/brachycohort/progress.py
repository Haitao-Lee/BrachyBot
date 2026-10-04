"""Durable case-level progress and linked retries, not planner iteration checkpoints."""
from pathlib import Path

from .core import Blocked, atomic_json, digest, load_json, sha256, utc


def chain(recipe_root, recipe_hash):
    paths = list(Path(recipe_root).glob("*/attempt.json"))
    if not paths:
        if Path(recipe_root).exists() and list(Path(recipe_root).iterdir()):
            raise Blocked("RECIPE_ATTEMPT_DIRECTORY_UNRESOLVED", recipe_hash)
        return []
    records = {p.parent.name: (p.parent, load_json(p)) for p in paths}
    first = [key for key, (_, record) in records.items() if not record.get("retry_of")]
    if len(first) != 1:
        raise Blocked("RECIPE_ATTEMPT_CHAIN_INVALID", recipe_hash)
    order, seen, key = [], set(), first[0]
    while key:
        if key in seen:
            raise Blocked("RECIPE_ATTEMPT_CHAIN_INVALID")
        seen.add(key)
        root, record = records[key]
        # Legacy single-attempt records remain readable; retries require the full recipe.
        if len(paths) > 1 and (record.get("recipe_hash") != recipe_hash or
                              digest(record.get("recipe")) != recipe_hash):
            raise Blocked("RECIPE_ATTEMPT_CHAIN_INVALID")
        if record.get("retry_of"):
            parent = records[record["retry_of"]][0]
            proof = settlement(parent)
            if not proof or proof["state"] != "RETRY_READY" or record.get("first_attempt_id") != first[0]:
                raise Blocked("RECIPE_RETRY_NOT_AUTHORIZED")
        order.append((root, record))
        children = [k for k, (_, r) in records.items() if r.get("retry_of") == key]
        if len(children) > 1:
            raise Blocked("RECIPE_ATTEMPT_CHAIN_INVALID")
        key = children[0] if children else None
    if seen != set(records):
        raise Blocked("RECIPE_ATTEMPT_CHAIN_INVALID")
    return order


def needs_reconciliation(root):
    terminal = Path(root) / "terminal_result.json"
    if not terminal.is_file():
        return True
    result = load_json(terminal)
    return bool(result.get("interrupted") or result.get("cancellation_state") == "CANCEL_PENDING" or
                result.get("reconciliation") and result.get("cancellation_state") != "TASK_TERMINAL")


def settlement(root):
    pointer = Path(root) / "recovery_state.json"
    if not pointer.is_file():
        return None
    ref = load_json(pointer)
    artifact = Path(ref["path"]).resolve()
    allowed = (Path(root) / "recoveries").resolve()
    if allowed not in artifact.parents or sha256(artifact) != ref["sha256"] or \
            sha256(Path(root) / "attempt.json") != ref["attempt_sha256"]:
        raise Blocked("RECOVERY_LINK_CHANGED")
    evidence = load_json(artifact)
    if evidence.get("attempt_id") != Path(root).name or evidence.get("state") not in {"SETTLED", "RETRY_READY"}:
        raise Blocked("RECOVERY_IDENTITY_MISMATCH")
    if evidence.get("recipe_hash") != load_json(Path(root) / "attempt.json").get("recipe_hash"):
        raise Blocked("RECOVERY_RECIPE_MISMATCH")
    if not evidence.get("no_server_work_submitted") and not evidence.get("server_observation"):
        raise Blocked("RECOVERY_SERVER_EVIDENCE_MISSING")
    return evidence


def save_settlement(root, destination, result):
    atomic_json(Path(destination) / "recovery.json", result)
    atomic_json(Path(root) / "recovery_state.json", {"path": str(Path(destination) / "recovery.json"),
                "sha256": sha256(Path(destination) / "recovery.json"),
                "attempt_sha256": sha256(Path(root) / "attempt.json"), "settled_at": utc()})


def state(storage, recipe_hash):
    items = chain(storage.path("runs/" + recipe_hash), recipe_hash)
    if not items:
        return "PENDING"
    root, record = items[-1]
    proof = settlement(root)
    if proof:
        return "PENDING" if proof["state"] == "RETRY_READY" else "TERMINAL"
    if needs_reconciliation(root):
        raise Blocked("AUTHORITATIVE_RECONCILIATION_REQUIRED", str(root))
    result = load_json(root / "terminal_result.json")
    if result.get("recipe_hash") != recipe_hash:
        raise Blocked("TERMINAL_RECIPE_MISMATCH")
    return "TERMINAL"
