"""Request-local timing for the unchanged planning decision sequence.

Nested rows overlap and must not be summed. No patient arrays or model state
are retained here. ContextVars isolate simultaneous planning requests.
"""
from contextvars import ContextVar
from functools import wraps
import logging
import time

_profile = ContextVar('planning_latency', default=None)
logger = logging.getLogger(__name__)


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
        start = time.perf_counter()
        try:
            result = function(*args, **kwargs)
            metadata = getattr(result, 'metadata', None)
            if isinstance(metadata, dict):
                metadata['latency_profile'] = {
                    'total_seconds': time.perf_counter() - start,
                    'nested_timings': profile,
                }
            return result
        finally:
            logger.info('[planning_latency] total_seconds=%.3f nested_timings=%s',
                        time.perf_counter() - start, profile)
            _profile.reset(token)
    return run
