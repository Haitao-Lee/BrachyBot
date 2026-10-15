"""Bounded, single-flight hydration for immutable owned clinical revisions."""
from __future__ import annotations

import copy
import sys
import numpy as np
import SimpleITK as sitk
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from web.timepoints import TimepointConflict

_LOCK = threading.RLock()
_CACHE = OrderedDict()
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="timepoint-hydrate")
_MAX_ENTRIES = 8
_MAX_BYTES = 2 * 1024**3
_MAX_PENDING = 8
_ERROR_RETRY_SECONDS = 5


@dataclass
class Hydration:
    ready: threading.Event = field(default_factory=threading.Event)
    values: Mapping | None = None
    error: Exception | None = None
    size: int = 0
    failed_at: float = 0


def _weight(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, sitk.Image):
        # Native image buffers are not included in Python wrapper size. The
        # view is zero-copy; charge the native allocation conservatively.
        return sys.getsizeof(value) + sitk.GetArrayViewFromImage(value).nbytes
    if isinstance(value, np.ndarray):
        # Large sidecars are read-only file mappings, not eagerly allocated
        # heap buffers. Charging their virtual length made a case with several
        # Planning histories evict itself immediately on completion. Every
        # subsequent 202 poll then restarted decoding and could never see ready.
        # The OS manages mapped pages; bound heap allocations/metadata here and
        # mappings by the existing entry/open-file limits instead.
        base = value
        while isinstance(base, np.ndarray):
            if isinstance(base, np.memmap):
                return sys.getsizeof(value)
            base = base.base
        return max(value.nbytes, sys.getsizeof(value))
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(_weight(item, seen) for item in value.values())
    if isinstance(value, (tuple, list)):
        return sys.getsizeof(value) + sum(_weight(item, seen) for item in value)
    return sys.getsizeof(value)


def clinical_hydration(store, control_agent, snapshot, context):
    raw = getattr(store, "raw", store)
    key = (str(raw.runtime_dir), context.owner_id, context.session_id,
           context.target.timepoint_id, context.target.clinical_revision, context.target.lifecycle_revision,
           (snapshot.get("image_collection") or {}).get("planning_reference_image_id"))
    with _LOCK:
        item = _CACHE.get(key)
        if item is not None and item.error is not None and time.monotonic() - item.failed_at >= _ERROR_RETRY_SECONDS:
            _CACHE.pop(key, None)
            item = None
        if item is not None:
            _CACHE.move_to_end(key)
            return item
        if sum(not row.ready.is_set() for row in _CACHE.values()) >= _MAX_PENDING:
            raise TimepointConflict("Too many timepoint resource loads are pending; retry shortly")
        item = Hydration()
        _CACHE[key] = item
    # Keep only owned immutable metadata in the worker closure, not a Flask
    # request, browser tab, mutable Session Agent or globally active pointer.
    source = (snapshot.get("agent") or {}).get("planning_results") or {}
    # Deferred snapshots contain RequestResults. Iterating its values would
    # detach every historical run before the background worker even starts.
    saved = dict(getattr(source, "source", source))
    def load():
        try:
            from web.resource_view import HydratedResults
            def charge(value):
                size = _weight(value)
                with _LOCK:
                    item.size += size
                    while sum(row.size for row in _CACHE.values()) > _MAX_BYTES:
                        oldest = next((entry for entry, row in _CACHE.items()
                            if row.ready.is_set() and entry != key), None)
                        if oldest is None:
                            break
                        _CACHE.pop(oldest)
            decoded = HydratedResults(saved, raw.workspace_root(context.owner_id, context.session_id), on_load=charge)
            decoded.overlay({"timepoint_context": {"timepoint_id": context.target.timepoint_id,
                "stage": context.target.stage, "preoperative_timepoint_id": context.target.preoperative_timepoint_id}})
            if (snapshot.get("image_collection") or {}).get("planning_reference_image_id"):
                from web.timepoint_images import TimepointImageService
                if snapshot["image_collection"].get("planning_reference_image_id"):
                    bridge = TimepointImageService(raw).planning_reference_bridge(
                        context.owner_id, context.session_id, context.target.timepoint_id)
                    decoded.overlay({name: value for name, value in bridge.items() if name not in
                        {"timepoint_clinical_revision", "display_image_id"}})
                    image = bridge["ct_image"]
                    decoded.overlay(dict(ct_spacing=image.GetSpacing(), ct_origin=image.GetOrigin(),
                        ct_direction=image.GetDirection(), ct_shape=list(image.GetSize()[::-1]),
                        ct_image_raw=image, ct_axis_map={"axial": 0, "sagittal": 2, "coronal": 1},
                        image_modality=bridge["planning_reference_receipt"]["modality"]))
            elif decoded.get("ct_data") is not None:
                from web.guide_service import GuidePlacementService
                hydrated = {**snapshot, "agent": {**snapshot.get("agent", {}), "planning_results": decoded}}
                decoded.overlay({"ct_image": GuidePlacementService(control_agent)._target_ct_image(hydrated)})
            context.assert_current(context.owner_id, context.session_id,
                raw._timepoint_catalog(context.owner_id, context.session_id),
                legacy_revision=raw.get_session(context.owner_id, context.session_id).revision)
            item.values = decoded
        except Exception as exc:
            item.error = exc
            item.failed_at = time.monotonic()
        finally:
            item.ready.set()
            with _LOCK:
                # Preserve success/error handoff for the next poll. Immediately
                # evicting an error caused missing sidecars to loop through 202
                # forever instead of returning an actionable failure. Errors
                # expire after a short retry window and remain entry-bounded.
                while len(_CACHE) > _MAX_ENTRIES or sum(row.size for row in _CACHE.values()) > _MAX_BYTES:
                    oldest = next((entry for entry, row in _CACHE.items()
                        if row.ready.is_set() and entry != key), None)
                    if oldest is None:
                        break
                    _CACHE.pop(oldest)
    _POOL.submit(load)
    return item
