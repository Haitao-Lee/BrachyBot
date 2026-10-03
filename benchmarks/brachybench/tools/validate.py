#!/usr/bin/env python3
"""Schema validation CLI (DESIGN §7 / §25.4).

    # validate every task under benchmarks/brachybench/tasks
    python validate.py tasks --root ../../brachybench

    # validate one EXT acquisition manifest
    python validate.py acquisition --file ../../external/acquisition/EXT-1.yaml

    # validate a run manifest
    python validate.py run-manifest --file <run>/run_manifest.json

Exits non-zero on any schema error (CI gate).  No third-party dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.jsonschema_lite import format_errors, validate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(HERE, "..", "schema")

SCHEMAS = {
    "task": os.path.join(SCHEMA_DIR, "task.schema.json"),
    "cws": os.path.join(SCHEMA_DIR, "cws.schema.json"),
    "run_manifest": os.path.join(SCHEMA_DIR, "run_manifest.schema.json"),
    "acquisition": os.path.join(SCHEMA_DIR, "acquisition.schema.json"),
}


def load_schema(name: str) -> Dict[str, Any]:
    with open(SCHEMAS[name], encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# tiny YAML subset reader (mapping / list / scalar / block scalar only).
# Keeps us dependency-free while remaining sufficient for the acquisition
# manifest template of DESIGN appendix J.
# ---------------------------------------------------------------------------


def _strip_comment(v: str) -> str:
    """Drop a trailing ``# comment`` from a value (quote-aware)."""
    out = []
    in_q = ""
    for ch in v:
        if in_q:
            out.append(ch)
            if ch == in_q:
                in_q = ""
            continue
        if ch in ("'", '"'):
            in_q = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def _unbalanced(t: str) -> bool:
    """BA-16: reject unclosed brackets/quotes instead of silently scalarising."""
    depth = 0
    in_q = ""
    for ch in t:
        if in_q:
            if ch == in_q:
                in_q = ""
            continue
        if ch in ("'", '"'):
            in_q = ch
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0 or in_q != ""


def _parse_flow(tok: str) -> Any:
    """Inline flow collections: ``[a, b]`` and ``{k: v, k2: v2}``.

    BA-16: malformed flow (unclosed bracket/quote) **raises**; the previous
    behaviour of returning the raw string made a broken manifest validate as
    OK.
    """
    t = tok.strip()
    if _unbalanced(t):
        raise ValueError(f"malformed YAML flow / quoted scalar: {t!r}")
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar_or_flow(x) for x in _split_flow(inner)]
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        out: Dict[str, Any] = {}
        if not inner:
            return out
        for part in _split_flow(inner):
            if ":" not in part:
                raise ValueError(f"flow mapping entry without ':' : {part!r}")
            k, v = part.split(":", 1)
            out[k.strip()] = _parse_scalar_or_flow(v)
        return out
    return _parse_scalar(t)


def _split_flow(inner: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    buf: List[str] = []
    in_q: str = ""
    for ch in inner:
        if in_q:
            buf.append(ch)
            if ch == in_q:
                in_q = ""
            continue
        if ch in ("'", '"'):
            in_q = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
            buf.append(ch)
            continue
        if ch in "]}":
            depth -= 1
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf and "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


def _parse_scalar_or_flow(tok: str) -> Any:
    t = tok.strip()
    if t.startswith(("[", "{")):
        return _parse_flow(t)
    return _parse_scalar(t)


def _parse_scalar(tok: str) -> Any:
    t = tok.strip()
    if t in ("null", "~", ""):
        return None
    if t in ("true", "false"):
        return t == "true"
    if t.startswith(("'", '"')) and t.endswith(("'", '"')) and len(t) >= 2:
        return t[1:-1]
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d+", t):
        return float(t)
    return t


def parse_yaml_lite(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    # stack of (indent, container)
    stack: List[Tuple[int, Any]] = [(-1, root)]
    pending_key: Tuple[Any, int] = None  # (container, key_indent)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        container = stack[-1][1]

        if line.startswith("- "):
            item = line[2:].strip()
            if not isinstance(container, list):
                # auto-promote a dict slot into a list
                raise ValueError(f"list item outside a list at line {i}: {raw!r}")
            # a flow collection as a list item ("- {k: v}") must be parsed as a
            # whole; splitting it on the first ':' produced a bogus key and
            # then tripped the BA-16 unbalanced check.
            if item.startswith(("[", "{")):
                container.append(_parse_flow(item))
                if isinstance(container[-1], dict):
                    stack.append((indent, container[-1]))
                continue
            if ":" in item and not item.startswith(("'", '"')):
                d: Dict[str, Any] = {}
                k, v = item.split(":", 1)
                d[k.strip()] = _parse_flow(v)
                container.append(d)
                stack.append((indent, d))
            else:
                container.append(_parse_flow(item))
            continue

        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), _strip_comment(v)
            if v == "|" or v == ">":
                # block scalar
                buf: List[str] = []
                while i < len(lines):
                    nxt = lines[i]
                    if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                        break
                    buf.append(nxt.strip() if v == ">" else nxt)
                    i += 1
                container[k] = "\n".join(buf)
            elif v == "":
                # nested mapping OR list follows
                # look ahead to decide
                j = i
                is_list = False
                while j < len(lines):
                    peek = lines[j]
                    if not peek.strip() or peek.lstrip().startswith("#"):
                        j += 1
                        continue
                    pind = len(peek) - len(peek.lstrip(" "))
                    if pind <= indent:
                        break
                    is_list = peek.strip().startswith("- ")
                    break
                child: Any = [] if is_list else {}
                container[k] = child
                stack.append((indent, child))
            else:
                if _unbalanced(v):
                    raise ValueError(f"malformed YAML value at line {i}: {raw!r}")
                container[k] = _parse_flow(v)
            continue

        raise ValueError(f"unparsed line {i}: {raw!r}")
    return root


_PLACEHOLDER = re.compile(r"<[^>]{2,}>")


def _find_placeholders(node, path: str = ""):
    """BA-17: collect ``<angle-bracket>`` stubs that must be replaced before F25."""
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            out |= _find_placeholders(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out |= _find_placeholders(v, f"{path}/{i}")
    elif isinstance(node, str):
        if _PLACEHOLDER.search(node):
            out.add(path or "$")
    return out


def load_doc(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        return json.loads(text)
    return parse_yaml_lite(text)


def cmd_tasks(root: str) -> int:
    schema = load_schema("task")
    tdir = os.path.join(root, "tasks")
    if not os.path.isdir(tdir):
        print(f"no tasks dir: {tdir}", file=sys.stderr)
        return 1
    bad = 0
    seen: set = set()
    n = 0
    for dirpath, _, files in os.walk(tdir):
        for fn in sorted(files):
            if not fn.endswith(".json"):
                continue
            p = os.path.join(dirpath, fn)
            n += 1
            doc = load_doc(p)
            errs = validate(doc, schema)
            if doc.get("id") in seen:
                errs.append(("$", f"duplicate task id {doc.get('id')!r}"))
            seen.add(doc.get("id"))
            if errs:
                bad += 1
                print(f"FAIL {os.path.relpath(p, root)}", file=sys.stderr)
                print(format_errors(errs), file=sys.stderr)
    print(f"tasks: {n} checked, {bad} failed")
    return 1 if bad else 0


def cmd_one(kind: str, path: str) -> int:
    schema = load_schema(kind)
    doc = load_doc(path)
    errs = validate(doc, schema)
    if kind == "acquisition":
        # cross-field rule (§25.4): non-empty paid_apis forces R0-Gated/R1
        paid = (doc.get("runner") or {}).get("paid_apis") or []
        grade = doc.get("grade_R")
        if paid and grade == "R0":
            errs.append(("/grade_R", "paid_apis non-empty forces grade_R in {R0-Gated, R1}"))
        # BA-17: a schema-valid manifest full of angle-bracket placeholders is
        # NOT a completeness pass -- it is an unfilled stub.  Report it.
        placeholders = _find_placeholders(doc)
        if placeholders:
            errs.append((
                "/acquisition",
                "unfilled placeholder(s): " + ", ".join(sorted(placeholders)[:8])
                + (" ..." if len(placeholders) > 8 else "")
                + "  (F25/F26/F27 incomplete)",
            ))
    if kind == "task":
        oracle = doc.get("oracle") or {}
        if oracle.get("kind") == "judge" and not oracle.get("assist_only"):
            errs.append(("/oracle/assist_only", "oracle.kind==judge requires assist_only=true (§8.2)"))
        if oracle.get("kind") == "keyword":
            errs.append(("/oracle/kind", "oracle.kind==keyword is forbidden (§12.4)"))
        track = doc.get("track")
        if track in ("B", "D1", "D2", "D3", "E", "F", "H", "K", "L", "M") and oracle.get("kind") == "judge":
            errs.append(("/oracle/kind", f"judge may not judge track {track} (§8.2 four bans)"))
    if errs:
        print(f"FAIL {path}", file=sys.stderr)
        print(format_errors(errs), file=sys.stderr)
        return 1
    print(f"OK {path}")
    return 0


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tasks")
    p.add_argument("--root", required=True)
    for name in ("acquisition", "run-manifest", "cws", "task"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "tasks":
        return cmd_tasks(args.root)
    kind = {"run-manifest": "run_manifest"}.get(args.cmd, args.cmd)
    return cmd_one(kind, args.file)


if __name__ == "__main__":
    raise SystemExit(main())
