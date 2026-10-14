"""Read both durable legacy string and structured resource invalidation states."""
from collections.abc import Mapping


def resource_is_stale(value):
    if isinstance(value,Mapping):
        return value.get('stale') is True or value.get('status') in {'stale','invalidated'}
    return isinstance(value,str) and value in {'stale','invalidated'}
