"""Share guide work and retain safe, bounded CT-derived intermediate results.

The resample cache deliberately stops at the immutable local skin grid.  It
never caches a finished guide mesh or a persisted Session result, so a normal
regenerate still creates a new guide version and observes the current needle
selection.  The cache is process-local and scoped by the owning Session
memory object.
"""
from concurrent.futures import Future, TimeoutError
from copy import deepcopy
from threading import Lock
from collections import OrderedDict
from weakref import ref
import logging
import os

from utils.cancellation import raise_if_cancelled

_lock = Lock()
_inflight = {}
_skin_cache = OrderedDict()
_resample_cache = OrderedDict()
_resample_cache_bytes = 0

# A 0.2 mm local grid can contain hundreds of millions of voxels.  Keeping one
# immutable (mask + float32 signed-distance field) result is useful for a
# repeated guide generation, but an unbounded cache would turn an optimization
# into a process-wide memory leak.  The byte limit is intentionally
# configurable because clinical servers have different amounts of headroom.
RESAMPLE_CACHE_MAX_ENTRIES = 1
RESAMPLE_CACHE_DEFAULT_MAX_BYTES = 3_500_000_000
RESAMPLE_CACHE_DEFAULT_RESERVE_BYTES = 6 * 1024 ** 3


def _configured_bytes(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return max(0, int(raw))
    except ValueError:
        logging.getLogger(__name__).warning(
            "Ignoring invalid %s=%r", name, raw
        )
        return int(default)


def _available_memory_bytes():
    """Return Linux MemAvailable when exposed, otherwise leave admission open."""
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _value_nbytes(value):
    total = 0
    if isinstance(value, (tuple, list)):
        values = value
    else:
        values = (value,)
    for item in values:
        nbytes = getattr(item, "nbytes", None)
        if nbytes is not None:
            total += int(nbytes)
    return total


def _set_value_read_only(value):
    if isinstance(value, (tuple, list)):
        values = value
    else:
        values = (value,)
    for item in values:
        setflags = getattr(item, "setflags", None)
        if setflags is not None:
            setflags(write=False)


def _purge_dead_resample_entries():
    global _resample_cache_bytes
    expired = [
        item for item in _resample_cache
        if item[1]() is None
    ]
    for item in expired:
        _value, nbytes = _resample_cache.pop(item)
        _resample_cache_bytes -= int(nbytes)


def cached_resampled(memory, key, compute):
    """Reuse one immutable local skin-grid result when memory headroom allows.

    ``compute`` returns the same tuple as ``_resample_mask_to_local_grid``.
    Cache admission is conservative: it is disabled with a zero byte limit,
    rejects entries larger than the configured limit, and on Linux requires a
    configurable amount of free memory to remain after retaining the entry.
    A skipped admission never changes the computed value or its mutability.
    """
    global _resample_cache_bytes
    try:
        owner = ref(memory)
        hash(owner)
    except TypeError:
        return compute()
    scoped_key = (id(memory), owner, key)
    with _lock:
        _purge_dead_resample_entries()
        cached = _resample_cache.get(scoped_key)
        if cached is not None:
            _resample_cache.move_to_end(scoped_key)
            logging.getLogger(__name__).info(
                "Surgical guide local grid cache hit bytes=%d", cached[1]
            )
            return cached[0]

    value = compute()
    nbytes = _value_nbytes(value)
    max_bytes = _configured_bytes(
        "BRACHYBOT_GUIDE_RESAMPLE_CACHE_MAX_BYTES",
        RESAMPLE_CACHE_DEFAULT_MAX_BYTES,
    )
    if max_bytes <= 0 or nbytes <= 0 or nbytes > max_bytes:
        logging.getLogger(__name__).info(
            "Surgical guide local grid cache skipped bytes=%d limit=%d",
            nbytes,
            max_bytes,
        )
        return value
    available = _available_memory_bytes()
    reserve = _configured_bytes(
        "BRACHYBOT_GUIDE_RESAMPLE_CACHE_RESERVE_BYTES",
        RESAMPLE_CACHE_DEFAULT_RESERVE_BYTES,
    )
    if available is not None and available < nbytes + reserve:
        logging.getLogger(__name__).warning(
            "Surgical guide local grid cache skipped bytes=%d available=%d reserve=%d",
            nbytes,
            available,
            reserve,
        )
        return value

    # The generation code only reads these arrays after resampling.  Making a
    # cached value immutable prevents a future caller from corrupting the
    # shared result; a mutation attempt fails closed instead.
    _set_value_read_only(value)
    with _lock:
        _purge_dead_resample_entries()
        existing = _resample_cache.get(scoped_key)
        if existing is not None:
            _resample_cache.move_to_end(scoped_key)
            return existing[0]
        while len(_resample_cache) >= RESAMPLE_CACHE_MAX_ENTRIES:
            _old_key, (_old_value, old_bytes) = _resample_cache.popitem(last=False)
            _resample_cache_bytes -= int(old_bytes)
        _resample_cache[scoped_key] = (value, int(nbytes))
        _resample_cache_bytes += int(nbytes)
    logging.getLogger(__name__).info(
        "Surgical guide local grid cache stored bytes=%d", nbytes
    )
    return value


def cached_skin(memory, key, compute):
    """At most two skin envelopes; weak ownership never pins a whole Session."""
    try:
        owner = ref(memory)
        hash(owner)
    except TypeError:
        return compute()
    scoped_key = (id(memory), owner, key)
    with _lock:
        for expired in [item for item in _skin_cache if item[1]() is None]:
            del _skin_cache[expired]
        value = _skin_cache.get(scoped_key)
        if value is not None:
            _skin_cache.move_to_end(scoped_key)
            return value[0], dict(value[1]), value[2]
    raw, faces, body = compute()
    raw.setflags(write=False)
    body.setflags(write=False)
    with _lock:
        _skin_cache[scoped_key] = (raw, dict(faces), body)
        _skin_cache.move_to_end(scoped_key)
        while len(_skin_cache) > 2:
            _skin_cache.popitem(last=False)
    return raw, faces, body


def singleflight(memory, key, compute):
    # Keep the owner alive through the complete flight: object IDs cannot be
    # reused, and two accounts/Session memories can never share a result.
    scoped_key = (id(memory), key)
    with _lock:
        flight = _inflight.get(scoped_key)
        owner = flight is None
        if owner:
            flight = Future()
            _inflight[scoped_key] = flight
    if not owner:
        logging.getLogger(__name__).info("Surgical guide joined identical in-flight generation")
        while True:
            raise_if_cancelled()
            try:
                return deepcopy(flight.result(timeout=0.25))
            except TimeoutError:
                if flight.done():
                    # The computation itself may have raised TimeoutError.
                    return deepcopy(flight.result())
    try:
        raise_if_cancelled()
        result = compute()
        flight.set_result(result)
        return result
    except BaseException as exc:
        flight.set_exception(exc)
        raise
    finally:
        with _lock:
            if _inflight.get(scoped_key) is flight:
                del _inflight[scoped_key]
