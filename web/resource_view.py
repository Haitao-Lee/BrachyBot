"""Demand-detached results for an HTTP request, with exact mutation baselines.

Unrequested historical plans stay in the immutable hydration handoff. Every
value exposed to the caller has independent containers and read-only array
views, just like an eager scoped clinical view. Writers still compare all keys
at their normal checkpoint; this changes allocation timing, not publication.
"""
from collections.abc import MutableMapping


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
        self.source = dict(source)
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

    def copy(self):
        from web.timepoint_chat import _detached
        return {key: _detached(self[key]) for key in self}
