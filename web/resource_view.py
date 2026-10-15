"""Demand-detached results for an HTTP request, with exact mutation baselines.

Unrequested historical plans stay in the immutable hydration handoff. Every
value exposed to the caller has independent containers and read-only array
views, just like an eager scoped clinical view. Writers still compare all keys
at their normal checkpoint; this changes allocation timing, not publication.
"""
from collections.abc import Mapping, MutableMapping
import threading
import time


class HydratedResults(Mapping):
    """Immutable revision handoff, decoding only the requested artifact key.

    A lock belongs to one key: a slow historical plan or failed guide cannot
    hold the CT, masks or current implant geometry behind its I/O. RequestResults
    still detaches each value before exposing it to mutable clinical callers.
    """
    def __init__(self, source, root, *, on_load=None):
        self.source = dict(source)
        self.root = root
        self.loaded = {}
        self.errors = {}
        self.locks = {key: threading.RLock() for key in self.source}
        self.on_load = on_load
        self.fragments = {}
        self.fragment_lock = threading.RLock()

    def __iter__(self):
        return iter(self.source)

    def __len__(self):
        return len(self.source)

    def __contains__(self, key):
        return key in self.source

    def __getitem__(self, key):
        if key not in self.source:
            raise KeyError(key)
        with self.locks[key]:
            if key in self.loaded:
                return self.loaded[key]
            failure = self.errors.get(key)
            if failure is not None and time.monotonic() - failure[0] < 5:
                raise failure[1]
            from web.workspace_store import _decode_artifacts
            from web.timepoint_chat import _detached
            try:
                value = _detached(_decode_artifacts(self.source[key], self.root))
            except Exception as exc:
                self.errors[key] = (time.monotonic(), exc)
                raise
            self.errors.pop(key, None)
            self.loaded[key] = value
            if self.on_load is not None:
                self.on_load(value)
            return value

    def overlay(self, values):
        # Called only while constructing the handoff, before it is published.
        for key, value in values.items():
            self.source[key] = None
            self.locks.setdefault(key, threading.RLock())
            self.loaded[key] = value
            if self.on_load is not None:
                self.on_load(value)

    def project(self, key, fields):
        """Read selected immutable plan fields without decoding its dose/history."""
        from web.timepoint_chat import _detached
        if key in self.loaded:
            value = self.loaded[key]
            return {name: _detached(value[name]) for name in fields if name in value} if isinstance(value, Mapping) else {}
        encoded = self.source.get(key)
        if not isinstance(encoded, Mapping):
            return {}
        with self.fragment_lock:
            fragment = self.fragments.get(key)
            if fragment is None:
                fragment = self.fragments[key] = HydratedResults(encoded, self.root, on_load=self.on_load)
        return {name: _detached(fragment[name]) for name in fields if name in fragment}


class ResultBaseline(MutableMapping):
    def __init__(self, results):
        self.results = results
        self.keys_at_start = set(results)
        self.tokens = {}

    def __getitem__(self, key):
        if key not in self.keys_at_start:
            raise KeyError(key)
        if key not in self.tokens:
            self.results[key]  # Capture before any caller can mutate the value.
        return self.tokens[key]

    def __setitem__(self, key, value):
        self.keys_at_start.add(key)
        self.tokens[key] = value

    def __delitem__(self, key):
        self.keys_at_start.remove(key)
        self.tokens.pop(key, None)

    def __iter__(self):
        return iter(self.keys_at_start)

    def __len__(self):
        return len(self.keys_at_start)

    def __contains__(self, key):
        return key in self.keys_at_start


class RequestResults(MutableMapping):
    def __init__(self, source, *, metadata_only=False):
        self.source = source if isinstance(source, HydratedResults) else dict(source)
        self.metadata_only = metadata_only
        self.owned = {}
        self.removed = set()
        self.baseline = ResultBaseline(self)

    def __getitem__(self, key):
        if key in self.removed:
            raise KeyError(key)
        if key not in self.owned:
            from web.timepoint_chat import _detached, _state_token
            value = self.source[key]
            if self.metadata_only:
                from web.workspace_store import _restore_hydration_metadata
                value = _restore_hydration_metadata(value)
            value = _detached(value)
            self.owned[key] = value
            if key in self.baseline and key not in self.baseline.tokens:
                self.baseline.tokens[key] = _state_token(value)
        return self.owned[key]

    def __setitem__(self, key, value):
        if key in self.baseline and key not in self.baseline.tokens:
            self[key]
        self.removed.discard(key)
        self.owned[key] = value

    def __delitem__(self, key):
        if key not in self:
            raise KeyError(key)
        if key in self.baseline and key not in self.baseline.tokens:
            self[key]
        self.owned.pop(key, None)
        self.removed.add(key)

    def __iter__(self):
        return (key for key in dict.fromkeys((*self.source, *self.owned))
                if key not in self.removed)

    def __len__(self):
        return sum(1 for _ in self)

    def __contains__(self, key):
        return key not in self.removed and (key in self.source or key in self.owned)

    def materialized_items(self):
        return self.owned.items()

    def project(self, key, fields):
        """Read-only projection; mutable users continue through __getitem__."""
        from web.timepoint_chat import _detached
        if key not in self:
            return {}
        if key not in self.owned and isinstance(self.source, HydratedResults):
            return self.source.project(key, fields)
        value = self.owned[key] if key in self.owned else self.source[key]
        if not isinstance(value, Mapping):
            return {}
        projected = {name: value[name] for name in fields if name in value}
        if key not in self.owned and self.metadata_only:
            from web.workspace_store import _restore_hydration_metadata
            projected = _restore_hydration_metadata(projected)
        return _detached(projected)

    def copy(self):
        from web.timepoint_chat import _detached
        return {key: _detached(self[key]) for key in self}
