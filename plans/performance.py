"""Request-local timing for the unchanged planning decision sequence.

Nested rows overlap and must not be summed. No patient arrays or model state
are retained here. ContextVars isolate simultaneous planning requests.
"""
from contextvars import ContextVar
from functools import wraps
import logging
import os
import threading
import time

_profile = ContextVar('planning_latency', default=None)
logger = logging.getLogger(__name__)


def _loadavg_1m() -> float:
    try:
        return float(os.getloadavg()[0])
    except (OSError, AttributeError, ValueError):
        return 0.0


def record_timing(name, seconds):
    profile = _profile.get()
    if profile is not None:
        row = profile.setdefault(name, {'calls': 0, 'seconds': 0.0})
        row['calls'] += 1
        row['seconds'] += seconds


def timed(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            profile = _profile.get()
            if profile is None:
                return function(*args, **kwargs)
            start = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                record_timing(name, time.perf_counter() - start)
        return run
    return decorate


def collect_planning_latency(function):
    @wraps(function)
    def run(*args, **kwargs):
        profile = {}
        token = _profile.set(profile)
        started = time.perf_counter()
        cpu_started = time.process_time()
        threads_started = threading.active_count()
        load_started = _loadavg_1m()
        try:
            result = function(*args, **kwargs)
            metadata = getattr(result, 'metadata', None)
            if isinstance(metadata, dict):
                wall = time.perf_counter() - started
                cpu = time.process_time() - cpu_started
                metadata['latency_profile'] = {
                    'total_seconds': wall,
                    'nested_timings': profile,
                    'contention': {
                        'loadavg_1m_start': load_started,
                        'loadavg_1m_end': _loadavg_1m(),
                        'process_cpu_seconds': cpu,
                        'wall_seconds': wall,
                        'avg_parallelism': (cpu / wall) if wall > 0 else 0.0,
                        'threads_start': threads_started,
                        'threads_end': threading.active_count(),
                    },
                }
            return result
        finally:
            wall = time.perf_counter() - started
            cpu = time.process_time() - cpu_started
            parallelism = (cpu / wall) if wall > 0 else 0.0
            logger.info(
                '[planning_latency] total_seconds=%.3f cpu_seconds=%.3f '
                'parallelism=%.2f load1=%.2f nested_timings=%s',
                wall, cpu, parallelism, _loadavg_1m(), profile,
            )
            _profile.reset(token)
    return run
