"""Metadata-only host/GPU samples. No account, process command-line or patient dump."""
import asyncio
import csv
import io
import os
import subprocess
import time

from .core import utc


async def sample(journal, stop):
    try:
        import psutil
    except ImportError:
        journal.event("resources", "UNKNOWN", reason="PSUTIL_MISSING")
        return
    while not stop.is_set():
        entry = {"utc": utc(), "runner_rss_bytes": psutil.Process(os.getpid()).memory_info().rss,
                 "host_ram_available_bytes": psutil.virtual_memory().available,
                 "host_cpu_percent": psutil.cpu_percent()}
        try:
            value = await asyncio.to_thread(subprocess.run,
                    ["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=4, check=True)
            entry["gpus"] = [{"index": int(r[0]), "memory_used_mib": float(r[1]),
                              "memory_total_mib": float(r[2]), "utilization_percent": float(r[3])}
                             for r in csv.reader(io.StringIO(value.stdout))]
        except (OSError, subprocess.SubprocessError, ValueError):
            entry["gpus"] = None
        journal.event("resources", "SAMPLED", sample=entry)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
