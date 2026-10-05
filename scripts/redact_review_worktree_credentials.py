"""Sanitize three independently verified legacy worktree literals, no values.

Run dry first. No Git history, service environment or other checkout is changed.
Recovery receipts deliberately contain hashes, not plaintext credential backups.
The worktrees need explicit provider configuration afterward.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

TARGETS = {
    ".claude/worktrees/ui-design-fixes/AgenticSys.py": "c09fa15600edf4865746804abe37d1c9414859a285a92cdb37676db0d8992c1d",
    ".claude/worktrees/datamind-report/AgenticSys.py": "fa163490d558f49e75fd33abcc43a8732c9be59c62762085176d2e795c2fc33c",
    ".claude/worktrees/benchmark-optimization/AgenticSys.py": "c09fa15600edf4865746804abe37d1c9414859a285a92cdb37676db0d8992c1d",
}
FINGERPRINT = "30a44efa1cf944ce95839ea4ec048fe0ad9e1f27c7a9bb16b423a03265e7a38e"


def sanitize(root, apply=False):
    root = Path(root).resolve()
    prepared, receipt = [], []
    for name, expected in TARGETS.items():
        path = root / name
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
            raise RuntimeError("Refusing a symlink target")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError("Target is not one regular private file")
        raw = path.read_bytes()
        before = hashlib.sha256(raw).hexdigest()
        if before != expected:
            raise RuntimeError("Target changed since the independent verification")
        matches = list(re.finditer(rb'\bsk-cp-[A-Za-z0-9_-]{20,1024}', raw))
        if len(matches) != 1 or hashlib.sha256(matches[0].group()).hexdigest() != FINGERPRINT:
            raise RuntimeError("Credential fingerprint did not match")
        match = matches[0]
        if raw[match.start()-1:match.start()] not in (b'"', b"'") or raw[match.end():match.end()+1] != raw[match.start()-1:match.start()]:
            raise RuntimeError("Credential is not one quoted literal")
        clean = raw[:match.start()] + raw[match.end():]
        compile(clean, name, "exec")
        prepared.append((path, clean, info.st_mode))
        receipt.append({"path": name, "before_sha256": before, "after_sha256": hashlib.sha256(clean).hexdigest(), "credential_sha256": FINGERPRINT})
    if apply:
        for path, clean, mode in prepared:
            fd, temporary = tempfile.mkstemp(prefix=".credential-redaction-", dir=path.parent)
            try:
                os.fchmod(fd, stat.S_IMODE(mode))
                with os.fdopen(fd, "wb") as handle:
                    handle.write(clean)
                    handle.flush()
                    os.fsync(handle.fileno())
                if hashlib.sha256(path.read_bytes()).hexdigest() != TARGETS[str(path.relative_to(root))]:
                    raise RuntimeError("Target changed before replacement")
                os.replace(temporary, path)
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    return {"applied": apply, "files": receipt, "provider_revocation": "unverified", "git_history": "unchanged"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(sanitize(args.root, args.apply), indent=2))
