"""Read-only delivered-file integrity, syntax and whitespace verification."""
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    checked, errors = 0, []
    entries = [(root, e) for e in manifest["files"]]
    entries += [(root.parents[1], e) for e in manifest.get("related_documents", [])]
    for base, entry in entries:
        p = (base / entry["path"]).resolve()
        if base.resolve() not in p.parents or not p.is_file():
            errors.append({"path": entry["path"], "error": "path_unavailable_or_unsafe"})
            continue
        data = p.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            errors.append({"path": entry["path"], "error": "hash_or_size_mismatch"})
        try:
            text = data.decode("utf-8")
            if p.suffix == ".py":
                ast.parse(text, filename=str(p))
            elif p.suffix == ".json":
                json.loads(text)
            elif p.suffix == ".toml":
                import tomllib
                tomllib.loads(text)
        except (UnicodeError, SyntaxError, ValueError) as exc:
            errors.append({"path": entry["path"], "error": type(exc).__name__, "detail": str(exc)})
        whitespace = subprocess.run(["git", "diff", "--no-index", "--check", "/dev/null", str(p)],
                                    capture_output=True, text=True)
        # --no-index reports ordinary differences with status 1 even when
        # --check emits no whitespace diagnostic (every delivered file is new).
        if whitespace.stdout.strip() or whitespace.stderr.strip() or whitespace.returncode not in (0, 1):
            errors.append({"path": entry["path"], "error": "whitespace", "detail": whitespace.stdout + whitespace.stderr})
        checked += 1
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "checked_files": checked, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
