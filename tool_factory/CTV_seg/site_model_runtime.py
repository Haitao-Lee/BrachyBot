"""Cancellable inference and cross-process per-card serialization for supplied CTV scripts."""
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from utils.cancellation import raise_if_cancelled

def inference_env():
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONEXECUTABLE',
                'PYTHONNOUSERSITE', 'CUDA_VISIBLE_DEVICES'):
        env.pop(key, None)
    env.update(PYTHONUNBUFFERED='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', nnUNet_compile='False')
    return env

@contextmanager
def gpu_lock(gpu, timeout=900):
    import fcntl
    # User-wide path also coordinates separate server processes/checkouts.
    directory = Path(tempfile.gettempdir()) / f'brachybot-ctv-gpu-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / f'gpu-{int(gpu)}.lock').open('a') as stream:
        deadline = time.monotonic() + timeout
        while True:
            raise_if_cancelled()
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('CTV GPU queue timeout')
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)

def communicate_cancellable(proc, timeout):
    deadline = time.monotonic() + timeout
    while True:
        raise_if_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'CTV inference exceeded {timeout}s')
        try:
            return proc.communicate(timeout=min(0.5, remaining))[0]
        except subprocess.TimeoutExpired:
            continue

def is_cuda_oom(error):
    value = str(error).lower()
    return 'outofmemoryerror' in value or ('cuda' in value and 'out of memory' in value)

def on_gpu(caller, callback):
    from plans.device_manager import device_session, DeviceManager
    preferred = os.environ.get('BRACHYBOT_CTV_GPU') or None
    for attempt in range(2):
        with device_session(caller=caller, prefer=preferred) as lease:
            if not str(lease.device_str).startswith('cuda:'):
                raise RuntimeError('An NVIDIA CUDA GPU is required for this CTV model.')
            gpu = int(str(lease.device_str).split(':')[1])
            try:
                with gpu_lock(gpu):
                    return callback(str(gpu))
            except Exception as exc:
                if attempt or not is_cuda_oom(exc) or DeviceManager.instance().device_count() < 2:
                    raise
                # No precision/fold downgrade: retry the same command on the other GPU.
                preferred = str(1 if gpu == 0 else 0)
