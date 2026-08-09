"""Regression tests for deterministic device lease selection."""

import threading
from pathlib import Path
from unittest.mock import patch

from plans.device_manager import DeviceManager


def _manager_with_two_gpus():
    manager = DeviceManager.__new__(DeviceManager)
    manager._cuda_available = True
    manager._device_count = 2
    manager._preferred = {}
    manager._active_per_device = {}
    manager._lease_lock = threading.Lock()
    manager._leases = []
    return manager


def test_acquire_accepts_its_cached_canonical_cuda_device_name():
    manager = _manager_with_two_gpus()
    manager._preferred["dose"] = "cuda:1"

    with patch.object(manager, "_auto_pick", return_value="cuda:0") as auto_pick:
        selected = manager.acquire(caller="dose")

    assert selected == "cuda:1"
    assert manager._active_per_device == {"cuda:1": 1}
    auto_pick.assert_not_called()


def test_explicit_numeric_gpu_preference_remains_supported():
    manager = _manager_with_two_gpus()

    selected = manager.acquire(caller="ctv", prefer="0")

    assert selected == "cuda:0"
    assert manager._preferred["ctv"] == "cuda:0"


def test_ctv_inference_does_not_mutate_process_global_gpu_visibility():
    source = (
        Path(__file__).resolve().parents[1]
        / "tool_factory" / "CTV_seg" / "pancreatic_tumor_nnunet.py"
    ).read_text(encoding="utf-8")

    assert 'os.environ["CUDA_VISIBLE_DEVICES"] =' not in source
    assert "_dm.acquire_session(" in source
