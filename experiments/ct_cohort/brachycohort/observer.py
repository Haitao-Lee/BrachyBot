"""Read-only observations. Product consistency is not independent physics."""
from __future__ import annotations
import base64
import math
import shutil
import time
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from .core import Blocked, atomic_json, child, load_json, sha256, sanitize
from .preflight import equal_grid


def decode(value, root):
    """Decode explicit checkpoint arrays only; never pickle/import product code."""
    if isinstance(value, list):
        return [decode(v, root) for v in value]
    if not isinstance(value, dict):
        return value
    if "$array" in value:
        return np.load(child(root, value["$array"]), allow_pickle=False, mmap_mode="r")
    if "$ndarray_inline" in value:
        dtype = np.dtype(value["dtype"])
        shape = tuple(value["shape"])
        if dtype.hasobject or dtype.fields or any(type(i) is not int or i < 0 for i in shape):
            raise Blocked("INVALID_CHECKPOINT_ARRAY")
        data = base64.b64decode(value["$ndarray_inline"], validate=True)
        if len(data) != dtype.itemsize * math.prod(shape):
            raise Blocked("INVALID_CHECKPOINT_ARRAY_LENGTH")
        return np.frombuffer(data, dtype=dtype).reshape(shape)
    if "$tuple" in value:
        return tuple(decode(v, root) for v in value["$tuple"])
    if "$unsupported" in value or "$image" in value:
        return None
    return {k: decode(v, root) for k, v in value.items()}


def workspace(backend, session_id):
    if not session_id or not all(c.isalnum() or c in "_-" for c in session_id):
        raise Blocked("INVALID_SESSION_ID")
    roots = list((Path(backend) / "workspaces").glob("*/" + session_id))
    if len(roots) != 1:
        raise Blocked("OWNED_WORKSPACE_NOT_UNIQUE", session_id)
    root = roots[0].resolve()
    if (Path(backend) / "workspaces").resolve() not in root.parents:
        raise Blocked("WORKSPACE_ESCAPES_BACKEND")
    snap = load_json(root / "snapshot.json")
    if str(snap.get("session_id")) != session_id:
        raise Blocked("SNAPSHOT_CASE_MISMATCH")
    return root, snap


def verify_effective_target(backend, session_id, resolved, selected_ids):
    root, snapshot = workspace(backend, session_id)
    state = snapshot.get("agent", {}).get("planning_results", {})
    ids = state.get("ctv_source_object_ids") or []
    if not ids or set(ids) != set(selected_ids):
        raise Blocked("CTV_PROVENANCE_MISMATCH", f"expected={selected_ids}; observed={ids}")
    encoded = state.get("ctv_binary_array")
    if encoded is None:
        raise Blocked("CTV_EFFECTIVE_ARRAY_MISSING")
    observed = decode(encoded, root)
    expected_image = sitk.ReadImage(resolved["derived_label_path"])
    expected = sitk.GetArrayFromImage(expected_image)
    if observed is None or observed.ndim != 3:
        raise Blocked("CTV_EFFECTIVE_UNION_MISSING")
    if not np.isfinite(observed).all() or not np.isin(observed, [0, 1]).all():
        raise Blocked("CTV_EFFECTIVE_NOT_BINARY")
    spacing = state.get("ct_spacing")
    origin = state.get("ct_origin")
    direction = state.get("ct_direction")
    if spacing is None or origin is None or direction is None:
        raise Blocked("OBSERVED_CT_GRID_MISSING")
    image = sitk.GetImageFromArray(np.asarray(observed, dtype=np.uint8))
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    image.SetDirection(direction)
    if not physical_target_equal(expected_image, image):
        raise Blocked("CTV_EFFECTIVE_UNION_MISMATCH")
    return {"status": "PASS", "evidence_level": "external_artifact_verification",
            "session_id": session_id, "source_object_ids": ids,
            "target_voxels": int(np.count_nonzero(observed)), "target_hash": resolved["target_hash"],
            "snapshot_sha256": sha256(root / "snapshot.json"), "observed_grid": {
                "spacing_mm": spacing, "origin_lps_mm": origin, "direction_lps": direction,
                "size_xyz": list(image.GetSize())}}


def physical_target_equal(expected, observed):
    """Allow lossless axis permutation/flips, never silent interpolated targets."""
    if equal_grid(expected, observed):
        return np.array_equal(sitk.GetArrayFromImage(expected), sitk.GetArrayFromImage(observed))
    if expected.GetDimension() != 3 or observed.GetDimension() != 3:
        return False
    b1 = np.array(expected.GetDirection()).reshape(3, 3) @ np.diag(expected.GetSpacing())
    b2 = np.array(observed.GetDirection()).reshape(3, 3) @ np.diag(observed.GetSpacing())
    try:
        transform = np.linalg.solve(b1, b2)
        offset = np.linalg.solve(b1, np.array(observed.GetOrigin()) - np.array(expected.GetOrigin()))
    except np.linalg.LinAlgError:
        return False
    if not np.allclose(transform, np.rint(transform), atol=1e-4, rtol=0) or not np.allclose(offset, np.rint(offset), atol=1e-4, rtol=0):
        return False
    permutation = np.abs(np.rint(transform))
    if not np.array_equal(permutation.sum(0), [1, 1, 1]) or not np.array_equal(permutation.sum(1), [1, 1, 1]):
        return False
    import itertools
    corners = np.array(list(itertools.product(*[(0, n - 1) for n in observed.GetSize()])))
    mapped = corners @ transform.T + offset
    if not np.allclose(mapped.min(0), 0, atol=1e-4, rtol=0) or not np.allclose(mapped.max(0), np.array(expected.GetSize()) - 1, atol=1e-4, rtol=0):
        return False
    converted = sitk.Resample(expected, observed, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8)
    return np.array_equal(sitk.GetArrayFromImage(converted), sitk.GetArrayFromImage(observed))


def copy_workspace(backend, session_id, destination, guard):
    """An observer backup, not a hidden setup/mutation. Inputs need not be copied twice."""
    root, snap = workspace(backend, session_id)
    before = sha256(root / "snapshot.json")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for source in sorted(root.rglob("*")):
        if not source.is_file() or "inputs" in source.relative_to(root).parts:
            continue
        guard()
        rel = source.relative_to(root)
        target = child(destination, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        h = sha256(source)
        shutil.copy2(source, target)
        if sha256(source) != h or sha256(target) != h:
            raise Blocked("WORKSPACE_CHANGED_DURING_ARCHIVE", str(rel))
        files.append({"path": str(rel), "sha256": h, "bytes": target.stat().st_size})
    if sha256(root / "snapshot.json") != before:
        raise Blocked("CHECKPOINT_CHANGED_DURING_ARCHIVE")
    atomic_json(destination / "observer_backup_manifest.json", {"session_id": session_id, "files": files,
                "snapshot_sha256": before, "inputs_omitted": True})
    return snap


def terminal_task(payload, expected_task_id=None):
    task = payload.get("task")
    if not task:
        return False
    if expected_task_id and task.get("task_id") != expected_task_id:
        return False
    return task.get("status") in {"completed", "failed", "cancelled", "error"}


class Observer:
    def __init__(self, context, session_id, journal, guard):
        self.context, self.session_id, self.journal, self.guard = context, session_id, journal, guard

    async def get(self, path):
        self.guard()
        response = await self.context.request.get(path, headers={"X-BrachyBot-Session": self.session_id},
                                                  timeout=30000, max_redirects=0)
        if response.status not in (200, 202):
            raise Blocked("OBSERVATION_HTTP_ERROR", f"{path}: {response.status}")
        value = await response.json()
        await response.dispose()
        if value.get("session_id") and value["session_id"] != self.session_id:
            raise Blocked("OBSERVATION_CASE_MISMATCH")
        return value

    async def wait(self, path, predicate, seconds, stage, poll=2):
        import asyncio
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = await self.get(path)
            if predicate(last):
                self.journal.event(stage, "OBSERVED", payload=sanitize(last))
                return last
            await asyncio.sleep(min(poll, max(0, deadline - time.monotonic())))
        raise Blocked(stage + "_TIMEOUT", f"last observation: {sanitize(last)}"[:1500])
