"""Present server filesystem locations as reversible, non-absolute tokens.

The browser must never learn where the server keeps a case.  Every outbound
path is rewritten to a short token form, and the very same token form is
accepted back on input, so a value the user sees can round-trip through the
API without exposing (or requiring) the real filesystem layout.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

WORKSPACE_TOKEN = "<workspace>"
RUNTIME_TOKEN = "<runtime>"
APP_TOKEN = "<app>"
GENERIC_TOKEN = "<path>"

# Absolute paths that are neither the case workspace, the runtime tree, nor the
# app tree still must not leak their directory structure.  Only recognised
# system roots are rewritten; a bare "/" or an inline fraction is left alone.
_GENERIC_PATH_RE = re.compile(
    r"(?<![\w:/])"
    r"(/(?:home|workspace|tmp|var|opt|usr|mnt|media|data|root|srv|etc|proc|sys)"
    r"(?:/[^\s\"'`()\[\]{}<>,;，。；、）】:]*)*)"
)
_TRAILING = ".,;:!?，。；：！？"


@dataclass(frozen=True)
class DisplayRoots:
    """Absolute prefixes that map to stable tokens for the browser."""

    workspace_root: str = ""
    runtime_dir: str = ""
    app_root: str = ""

    def pairs(self) -> List[Tuple[str, str]]:
        """Return ``(prefix, token)`` pairs, longest prefix first."""
        items: List[Tuple[str, str]] = []
        if self.workspace_root:
            items.append((os.path.normpath(self.workspace_root), WORKSPACE_TOKEN))
        if self.runtime_dir:
            items.append((os.path.normpath(self.runtime_dir), RUNTIME_TOKEN))
        if self.app_root:
            items.append((os.path.normpath(self.app_root), APP_TOKEN))
        items.sort(key=lambda pair: len(pair[0]), reverse=True)
        return items

    def resolve_map(self) -> List[Tuple[str, str]]:
        return [(token, prefix) for prefix, token in self.pairs()]


def _replace_root_prefix(text: str, prefix: str, token: str) -> str:
    """Rewrite every occurrence of ``prefix`` to ``token`` plus its tail."""
    pattern = re.compile(
        r"(?<![\w:/])"
        + re.escape(prefix)
        + r"(?![\w.-])"
        + r"((?:[/\\][^\s\"'`()\[\]{}<>,;，。；、）】:]*)?)"
    )

    def _replacement(match: "re.Match[str]") -> str:
        tail = (match.group(1) or "").replace("\\", "/").lstrip("/")
        return token + ("/" + tail if tail else "")

    return pattern.sub(_replacement, text)


def _generic_replacement(match: "re.Match[str]") -> str:
    raw = match.group(1)
    candidate = raw.rstrip(_TRAILING)
    tail = raw[len(candidate):]
    name = candidate.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not name:
        return match.group(0)
    return f"{GENERIC_TOKEN}/{name}{tail}"


def relativize_text(value: Any, roots: Optional[DisplayRoots] = None) -> str:
    """Rewrite absolute paths inside one string to reversible tokens."""
    text = str(value or "")
    if not text:
        return text
    for prefix, token in (roots or DisplayRoots()).pairs():
        text = _replace_root_prefix(text, prefix, token)
    return _GENERIC_PATH_RE.sub(_generic_replacement, text)


def relativize_value(value: Any, roots: Optional[DisplayRoots] = None) -> Any:
    """Recursively rewrite absolute paths in JSON-shaped values."""
    if isinstance(value, str):
        return relativize_text(value, roots)
    if isinstance(value, dict):
        return {key: relativize_value(item, roots) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [relativize_value(item, roots) for item in value]
    return value


def _find_unique_basename(name: str, roots: DisplayRoots) -> str:
    """Return the sole file/dir named ``name`` under the known roots, if any.

    Roots are searched most-specific first and the search stops at the first
    root that yields a hit, so a broader root cannot re-find the same file and
    turn a unique match into a false ambiguity.
    """
    for root in (roots.workspace_root, roots.runtime_dir, roots.app_root):
        if not root or not os.path.isdir(root):
            continue
        matches: List[str] = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if name in filenames or name in dirnames:
                    matches.append(os.path.join(dirpath, name))
                    if len(matches) > 1:
                        return ""
        except OSError:
            continue
        if matches:
            return matches[0]
    return ""


def resolve_user_path(value: Any, roots: Optional[DisplayRoots] = None) -> Any:
    """Restore a tokenized path to its absolute form.

    Tokens under a known root are joined back to it.  The generic
    ``<path>/name`` fallback is resolved by a unique basename match, and is
    returned unchanged when it cannot be resolved unambiguously.
    """
    if not isinstance(value, str) or not value:
        return value
    roots = roots or DisplayRoots()
    for token, prefix in roots.resolve_map():
        if value == token:
            return prefix
        if value.startswith(token + "/") or value.startswith(token + "\\"):
            rest = value[len(token) + 1:].replace("\\", "/")
            return os.path.normpath(os.path.join(prefix, *rest.split("/")))
    if value.startswith(GENERIC_TOKEN + "/") or value.startswith(GENERIC_TOKEN + "\\"):
        name = value[len(GENERIC_TOKEN) + 1:].replace("\\", "/")
        found = _find_unique_basename(name, roots)
        return found or value
    return value


def contains_display_token(value: Any) -> bool:
    """Return whether any string in a JSON-shaped value carries a token."""
    if isinstance(value, str):
        return value.startswith("<")
    if isinstance(value, dict):
        return any(contains_display_token(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_display_token(item) for item in value)
    return False


def restore_value_in_place(value: Any, roots: Optional[DisplayRoots] = None) -> Any:
    """Resolve tokens inside a parsed request body that must keep its identity.

    Mutates dicts/lists in place (so a borrowed, cached request body sees the
    resolved values) and returns the same container.
    """
    if isinstance(value, dict):
        for key in list(value.keys()):
            value[key] = restore_value_in_place(value[key], roots)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = restore_value_in_place(item, roots)
        return value
    return resolve_user_path(value, roots)


def _find_dot_runtime_ancestor(path: str) -> str:
    current = os.path.normpath(path)
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        if os.path.basename(parent) == ".runtime":
            return parent
        current = parent


def roots_from_workspace(
    workspace_root: str,
    *,
    runtime_dir: str = "",
    app_root: str = "",
) -> DisplayRoots:
    """Derive the runtime/app prefixes from a case workspace root."""
    workspace = os.path.normpath(os.path.realpath(workspace_root)) if workspace_root else ""
    runtime = os.path.normpath(runtime_dir) if runtime_dir else ""
    app = os.path.normpath(app_root) if app_root else ""
    if workspace and not runtime:
        runtime = _find_dot_runtime_ancestor(workspace)
    if runtime and not app:
        app = os.path.dirname(runtime)
    elif workspace and not app:
        app = os.path.dirname(workspace)
    return DisplayRoots(workspace_root=workspace, runtime_dir=runtime, app_root=app)


def roots_from_config(config: Any) -> DisplayRoots:
    """Build display roots from an agent config mapping when available."""
    config = config if isinstance(config, dict) else {}
    workspace = str(config.get("_workspace_root") or config.get("workspace_root") or "")
    return roots_from_workspace(workspace)
