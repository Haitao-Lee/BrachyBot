"""Thread-safe bounded immutable per-seed inference cache."""
from collections import OrderedDict
import hashlib
import json
import threading
import numpy as np


def dose_input_identity(case_identity, image, settings, model_identity):
    """Hash actual model input once per recomputation, not once per seed."""
    import SimpleITK as sitk
    voxels = np.ascontiguousarray(sitk.GetArrayViewFromImage(image))
    content = hashlib.sha256(memoryview(voxels).cast("B")).hexdigest()
    return (str(case_identity), str(model_identity), content, str(voxels.dtype),
            tuple(image.GetSize()), tuple(image.GetSpacing()), tuple(image.GetOrigin()),
            tuple(image.GetDirection()), json.dumps(settings, sort_keys=True, default=str, allow_nan=False))


class DoseSeedCache:
    def __init__(self, max_entries=128, max_bytes=512 * 1024**2):
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._lock = threading.RLock()
        self._items = OrderedDict()
        self._bytes = 0

    def get(self, key):
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key, value):
        array = np.asarray(value, dtype=np.float32).copy()
        array.setflags(write=False)
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old.nbytes
            if array.nbytes <= self.max_bytes:
                self._items[key] = array
                self._bytes += array.nbytes
            while len(self._items) > self.max_entries or self._bytes > self.max_bytes:
                _, old = self._items.popitem(last=False)
                self._bytes -= old.nbytes
        return array
