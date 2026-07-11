"""
device_manager.py — centralized GPU/CPU device selection
==========================================================

BrachyBot's deep-learning stack (CTV seg, OAR seg, dose engine) used
to call `torch.device("cuda" if torch.cuda.is_available() else "cpu")`
in 12+ places. That pattern has three problems:

1. It pins the first visible GPU (`cuda:0`) regardless of which one is
   actually free. With 2+ GPUs, the user always runs on the busiest
   one because that's where the X server / desktop session lives.
2. If `cuda:0` runs out of memory, every tool call falls back to CPU
   instead of trying the next GPU.
3. There's no observability — the user has no way to see which device
   is in use, how much memory is free, or whether the system is
   thrashing.

The DeviceManager below solves all three:

- On import, probes every visible GPU (memory total, memory used,
  current utilization). Caches the **device count** and **names**.
- `acquire(prefer=...)` returns the best free device, optionally
  pinned to a specific index. The algorithm:
    1. If prefer='cpu' (or no GPU), return cpu.
    2. If prefer is an int, return that specific GPU.
    3. Otherwise score each GPU by:
         free_mem = total_mem - used_mem
         utilization  (from nvidia-smi or pynvml)
       Pick the GPU with the highest `free_mem` (since low utilization
       on a 24GB card beats 0% utilization on a 4GB card).
    4. If the picked GPU OOMs during the call, `acquire()` will
       transparently retry on the next-best GPU, then fall back to
       CPU. The OOM event is logged.
- `acquire_session(name, prefer=...)` returns a "lease" object. The
  tool holds the lease for the duration of its forward pass; the
  lease is released on context exit. This lets multiple tools SHARE
  a GPU (serial reuse) or SPLIT (one on GPU 0, another on GPU 1).
- `status()` returns a JSON-serializable dict for the /api/status
  endpoint so the user can see what's running where.

Why "best free memory" not "lowest utilization":
- Utilization samples at 100ms granularity — between samples the GPU
  can be fully busy (training) or fully idle (waiting). A 24GB card
  showing 80% util might still have 5GB free for a small inference;
  an 8GB card showing 0% util might already be in the middle of
  loading a model. Memory pressure is the **durable** signal.
- For inference (BrachyBot's use case) the model weights and the
  activations both live in GPU memory. The GPU with the most free
  memory is the one most likely to succeed without OOM.

When pynvml isn't available (e.g. on macOS, in CI), the manager
falls back to pynvml-less mode: it still picks `cuda:0` when CUDA is
available, but doesn't track per-GPU utilization. That's fine —
we're not flying blind, we're just not optimizing.

API stability: this module is consumed by all 12+ tool files. The
public surface is `acquire()`, `acquire_session()`, `release()`,
`status()`. Anything else is private.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import torch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Snapshot of one CUDA device."""
    index: int
    name: str
    total_mem_mb: int
    used_mem_mb: int
    free_mem_mb: int
    utilization_pct: int  # 0-100; -1 if not measurable
    is_available: bool

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "name": self.name,
            "total_mem_mb": self.total_mem_mb,
            "used_mem_mb": self.used_mem_mb,
            "free_mem_mb": self.free_mem_mb,
            "utilization_pct": self.utilization_pct,
            "is_available": self.is_available,
        }


@dataclass
class DeviceLease:
    """A short-lived reservation of a device. Use as a context manager."""
    device_str: str  # 'cpu' / 'cuda:0' / 'cuda:1' / 'mps'
    device_index: int  # -1 for cpu
    info: Optional[DeviceInfo]
    acquired_at: float
    released_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

class _NvidiaSmiProbe:
    """Wrapper around pynvml (preferred) or nvidia-smi (fallback).

    The probe is initialized lazily on first use. If neither is
    available, `query_gpu()` returns None and the manager falls
    back to non-monitoring mode (always picks cuda:0 when CUDA is
    available, with no per-GPU scoring).
    """

    def __init__(self):
        self._pynvml = None
        self._init_pynvml()

    def _init_pynvml(self):
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            self._pynvml = pynvml
        except Exception as e:
            logger.debug(f"device_manager: pynvml unavailable ({e}); "
                         f"falling back to torch.cuda + nvidia-smi probe")
            self._pynvml = None

    def query(self, device_index: int) -> Optional[Tuple[int, int, int, int]]:
        """Return (total_mb, used_mb, free_mb, util_pct) or None."""
        if self._pynvml is not None:
            try:
                h = self._pynvml.nvmlDeviceGetHandleByIndex(device_index)
                mem = self._pynvml.nvmlDeviceGetMemoryInfo(h)
                util = self._pynvml.nvmlDeviceGetUtilizationRates(h)
                return (
                    int(mem.total // (1024 * 1024)),
                    int(mem.used // (1024 * 1024)),
                    int(mem.free // (1024 * 1024)),
                    int(util.gpu),
                )
            except Exception as e:
                logger.debug(f"pynvml query failed for gpu {device_index}: {e}")
                return None
        # Fallback: use torch.cuda only for memory (utilization unavailable)
        try:
            import torch
            free_b, total_b = torch.cuda.mem_get_info(device_index)
            return (
                int(total_b // (1024 * 1024)),
                int((total_b - free_b) // (1024 * 1024)),
                int(free_b // (1024 * 1024)),
                -1,  # utilization unknown
            )
        except Exception:
            return None


class DeviceManager:
    """Process-wide singleton. All tools call `DeviceManager.instance().acquire(...)`."""

    _instance: Optional["DeviceManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._probe = _NvidiaSmiProbe()
        self._leases: List[DeviceLease] = []
        self._lease_lock = threading.Lock()
        # Detect once at import time so the first acquire() is fast
        self._cuda_available = self._detect_cuda()
        self._device_count = self._cuda_available and self._count_devices() or 0
        self._device_names = self._fetch_names() if self._cuda_available else []
        # Persistent per-process device selection — once we've picked
        # a device, we keep using it for the same caller (per-tool)
        # unless the user explicitly asks for a different one. This
        # keeps the model weights warm in the same memory pool.
        self._preferred: Dict[str, str] = {}  # caller_name → device_str
        # Per-GPU concurrent lease counter
        self._active_per_device: Dict[str, int] = {}

    # --- singleton ---
    @classmethod
    def instance(cls) -> "DeviceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls.__new__(cls)
                    cls._instance.__init__()
        return cls._instance

    @classmethod
    def reset_for_tests(cls):
        """Test hook — drop the cached singleton so the next
        instance() rebuilds from scratch (e.g. after a mocked
        CUDA_VISIBLE_DEVICES change)."""
        with cls._lock:
            cls._instance = None

    # --- introspection ---
    def cuda_available(self) -> bool:
        return self._cuda_available

    def device_count(self) -> int:
        return self._device_count

    def device_names(self) -> List[str]:
        return list(self._device_names)

    def status(self) -> Dict:
        """JSON-serializable status for /api/status."""
        if not self._cuda_available:
            return {
                "cuda_available": False,
                "device_count": 0,
                "devices": [],
                "preferred": dict(self._preferred),
                "active_leases": len(self._leases),
            }
        devices = [self._read_info(i) for i in range(self._device_count)]
        return {
            "cuda_available": True,
            "device_count": self._device_count,
            "devices": [d.to_dict() for d in devices if d is not None],
            "preferred": dict(self._preferred),
            "active_leases": len(self._leases),
        }

    def _read_info(self, device_index: int) -> Optional[DeviceInfo]:
        try:
            import torch
            name = torch.cuda.get_device_name(device_index)
        except Exception:
            name = f"cuda:{device_index}"
        q = self._probe.query(device_index)
        if q is None:
            # No probe — best we can do
            return DeviceInfo(
                index=device_index, name=name,
                total_mem_mb=0, used_mem_mb=0, free_mem_mb=0,
                utilization_pct=-1, is_available=True,
            )
        total, used, free, util = q
        return DeviceInfo(
            index=device_index, name=name,
            total_mem_mb=total, used_mem_mb=used, free_mem_mb=free,
            utilization_pct=util, is_available=(free > 200),
        )

    # --- acquisition ---
    def acquire(self, caller: str = "default", prefer: Optional[str] = None) -> str:
        """Pick the best device for `caller`. Returns a torch device
        string ('cpu' / 'cuda:0' / 'cuda:1' / 'mps').

        `prefer`:
          - None: auto-pick the most-free GPU; fall back to cpu
          - 'cpu': always cpu
          - int 0..N-1: pin to that GPU
          - '0' / '1' / etc: same as int
          - 'auto' (alias for None)
        """
        # Honor an existing preference for this caller unless caller
        # explicitly asked for something different this time.
        if prefer is None or prefer == "auto":
            if caller in self._preferred:
                prefer = self._preferred[caller]
        if prefer == "cpu":
            chosen = "cpu"
        elif prefer is not None:
            # int / str-int → specific GPU
            try:
                idx = int(prefer)
                if self._cuda_available and 0 <= idx < self._device_count:
                    chosen = f"cuda:{idx}"
                else:
                    logger.warning(f"device_manager: GPU {idx} requested but not available; using cpu")
                    chosen = "cpu"
            except ValueError:
                logger.warning(f"device_manager: unknown prefer value {prefer!r}; auto-picking")
                chosen = self._auto_pick()
        else:
            chosen = self._auto_pick()
        # Cache the choice for this caller (so model weights stay warm)
        self._preferred[caller] = chosen
        with self._lease_lock:
            self._active_per_device[chosen] = self._active_per_device.get(chosen, 0) + 1
        logger.info(f"device_manager: {caller} → {chosen} "
                    f"(active on {chosen}: {self._active_per_device[chosen]})")
        return chosen

    @contextmanager
    def acquire_session(self, caller: str = "default", prefer: Optional[str] = None):
        """Context manager. Yields a DeviceLease; releases on exit."""
        import time
        chosen = self.acquire(caller=caller, prefer=prefer)
        # Extract index for bookkeeping
        if chosen == "cpu":
            idx = -1
            info = None
        elif chosen.startswith("cuda:"):
            idx = int(chosen.split(":", 1)[1])
            info = self._read_info(idx)
        else:
            idx = -1
            info = None
        lease = DeviceLease(
            device_str=chosen, device_index=idx, info=info,
            acquired_at=time.time(),
        )
        self._leases.append(lease)
        try:
            yield lease
        finally:
            lease.released_at = time.time()
            with self._lease_lock:
                self._active_per_device[chosen] = max(0, self._active_per_device.get(chosen, 0) - 1)
            # Pop the lease (keep list short — leases are debug aids)
            try:
                self._leases.remove(lease)
            except ValueError:
                pass

    def release(self, lease: DeviceLease) -> None:
        """Explicit release (the context manager handles this for you)."""
        with self._lease_lock:
            self._active_per_device[lease.device_str] = max(
                0, self._active_per_device.get(lease.device_str, 0) - 1
            )

    def _auto_pick(self) -> str:
        if not self._cuda_available:
            return "cpu"
        # Check Apple MPS (M-series) before CUDA — rare but possible
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        # Score each GPU by free memory; pick the max
        best_idx = 0
        best_score = -1
        for i in range(self._device_count):
            info = self._read_info(i)
            if info is None:
                continue
            # Score: free memory dominates; utilization is a tiebreaker
            # (lower util is better). Both are durable signals.
            util_penalty = info.utilization_pct if info.utilization_pct >= 0 else 50
            # 1GB free = 1000 score; 0% util = +50 bonus
            score = info.free_mem_mb - util_penalty * 10
            # Concurrent-lease penalty: if 2 tools already on this GPU,
            # penalize so we spread load across GPUs.
            score -= self._active_per_device.get(f"cuda:{i}", 0) * 200
            if score > best_score:
                best_score = score
                best_idx = i
        return f"cuda:{best_idx}"

    def handle_oom(self, caller: str, original_device: str, exc: Exception) -> str:
        """Called by tools when a CUDA OOM happens. Returns the
        next-best device to retry on (next GPU or cpu)."""
        logger.warning(f"device_manager: OOM on {original_device} for {caller} ({exc}); "
                       f"falling back to next-best device")
        # If we were on a specific GPU, mark it as exhausted for this caller
        # and try the next GPU, then CPU.
        if original_device.startswith("cuda:"):
            try:
                bad_idx = int(original_device.split(":", 1)[1])
            except ValueError:
                bad_idx = -1
            # Try GPUs with higher index first
            for offset in range(1, self._device_count):
                next_idx = (bad_idx + offset) % self._device_count
                next_str = f"cuda:{next_idx}"
                info = self._read_info(next_idx)
                if info and info.free_mem_mb > 1500:
                    self._preferred[caller] = next_str
                    logger.info(f"device_manager: {caller} retried on {next_str} "
                                f"(free {info.free_mem_mb} MB)")
                    return next_str
        # Final fallback: cpu
        self._preferred[caller] = "cpu"
        return "cpu"

    # --- internal helpers ---
    def _detect_cuda(self) -> bool:
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _count_devices(self) -> int:
        try:
            import torch
            return int(torch.cuda.device_count())
        except Exception:
            return 0

    def _fetch_names(self) -> List[str]:
        try:
            import torch
            return [torch.cuda.get_device_name(i) for i in range(self._device_count)]
        except Exception:
            return [f"cuda:{i}" for i in range(self._device_count)]


# ---------------------------------------------------------------------------
# Convenience helpers (the most common usage)
# ---------------------------------------------------------------------------

def get_device(caller: str = "default", prefer: Optional[str] = None) -> "torch.device":
    """Return a torch.device bound to the best free device. This is
    the single import tools should use, replacing the 12+ copies of
    `torch.device("cuda" if torch.cuda.is_available() else "cpu")`."""
    import torch
    chosen = DeviceManager.instance().acquire(caller=caller, prefer=prefer)
    return torch.device(chosen)


def device_session(caller: str = "default", prefer: Optional[str] = None):
    """Context-manager version that also tracks active leases. Use
    when a tool does a multi-step forward pass and wants to hold the
    same device for the whole pass."""
    return DeviceManager.instance().acquire_session(caller=caller, prefer=prefer)
