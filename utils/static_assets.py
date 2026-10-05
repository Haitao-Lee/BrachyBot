"""Reject source/backup artifacts before Flask's unauthenticated static route."""
from pathlib import PurePosixPath
import re

def is_public_asset(path):
    parts = PurePosixPath(str(path)).parts
    if not parts or any(p.startswith(".") for p in parts):
        return False
    name = parts[-1].lower()
    if re.search(r"\.(bak[^.]*|orig|rej|tmp|log|py|env|sqlite3?|db)(\.|$)|~$", name):
        return False
    return PurePosixPath(name).suffix in {".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp", ".gif", ".woff", ".woff2", ".ttf", ".wasm", ".map"}
