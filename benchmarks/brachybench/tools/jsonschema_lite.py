"""Minimal dependency-free JSON-Schema-ish validator.

``jsonschema`` is not available in the target environment, and the schema set
is small and frozen (DESIGN §7), so a tiny declarative checker is both
portable and auditable.  Supported keywords: ``type``, ``required``,
``properties``, ``items``, ``enum``, ``pattern``, ``minimum``, ``minItems``,
``additionalProperties`` (bool), ``oneOf`` (by ``const`` discriminator),
``$ref`` (local ``#/$defs/<name>`` only).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

Error = Tuple[str, str]  # (json_pointer, message)

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _is_type(instance: Any, t: str) -> bool:
    if t == "null":
        return instance is None
    if instance is None:
        return False
    if t == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if t == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    return isinstance(instance, _TYPES[t])


def validate(instance: Any, schema: Dict[str, Any], root: Dict[str, Any] = None, path: str = "") -> List[Error]:
    root = root if root is not None else schema
    errs: List[Error] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"only local #/$defs refs supported, got {ref!r}")
        name = ref.split("/")[-1]
        if name not in root.get("$defs", {}):
            raise ValueError(f"unresolved $ref {ref!r} (no $defs/{name})")
        return validate(instance, root["$defs"][name], root, path)

    if "const" in schema:
        if instance != schema["const"]:
            errs.append((path, f"expected const {schema['const']!r}, got {instance!r}"))
        return errs

    if "oneOf" in schema:
        sub_errs = [validate(instance, s, root, path) for s in schema["oneOf"]]
        matched = [i for i, e in enumerate(sub_errs) if not e]
        # Standard oneOf semantics: EXACTLY one branch must match.  Merely
        # "at least one" would let an under-specified value satisfy several
        # branches at once.
        if len(matched) != 1:
            errs.append((
                path,
                f"oneOf requires exactly one matching branch, {len(matched)} "
                f"matched; per-branch errors: {[e[:1] for e in sub_errs]}",
            ))
        return errs

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(instance, one) for one in types):
            errs.append((path, f"expected {'/'.join(types)}, got {type(instance).__name__}"))
            return errs
        # single-type schemas still get the bool-vs-int / bool-vs-number guard
        if types == ["integer"] and isinstance(instance, bool):
            errs.append((path, "expected integer, got bool"))
            return errs
        if types == ["number"] and isinstance(instance, bool):
            errs.append((path, "expected number, got bool"))
            return errs

    if "enum" in schema and instance not in schema["enum"]:
        errs.append((path, f"{instance!r} not in enum {schema['enum']}"))

    if "pattern" in schema and isinstance(instance, str):
        if not re.search(schema["pattern"], instance):
            errs.append((path, f"{instance!r} does not match /{schema['pattern']}/"))

    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            errs.append((path, f"{instance} < minimum {schema['minimum']}"))

    if "minItems" in schema and isinstance(instance, list):
        if len(instance) < schema["minItems"]:
            errs.append((path, f"len {len(instance)} < minItems {schema['minItems']}"))

    if isinstance(instance, dict):
        # P2: standard JSON-Schema ``required`` semantics -- presence only.
        # Treating null/"" as "missing" silently rejected legitimate values and
        # diverged from the published spec.
        req = schema.get("required", [])
        for k in req:
            if k not in instance:
                errs.append((path or "$", f"missing required property {k!r}"))
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs.extend(validate(v, props[k], root, f"{path}/{k}"))
            elif schema.get("additionalProperties") is False:
                errs.append((f"{path}/{k}", "additional property not allowed"))

    if isinstance(instance, list) and "items" in schema:
        for i, v in enumerate(instance):
            errs.extend(validate(v, schema["items"], root, f"{path}/{i}"))

    return errs


def format_errors(errs: List[Error]) -> str:
    return "\n".join(f"  {p or '$'}: {m}" for p, m in errs)
