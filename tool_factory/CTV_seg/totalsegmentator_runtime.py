"""Runtime discovery helpers for the installed TotalSegmentator CLI.

The server is often launched with an absolute Conda Python path while the
non-interactive process PATH still belongs to the system shell.  Looking up
only ``shutil.which('TotalSegmentator')`` would therefore report an installed
runtime as unavailable.  Both the model catalog and the liver CTV executor
must use this same resolver so the UI state and execution behavior cannot
disagree.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


_CLI_NAMES = ("TotalSegmentator", "totalsegmentator")


def find_totalsegmentator_executable() -> Optional[str]:
    """Return an executable TotalSegmentator path visible to this process."""
    for name in _CLI_NAMES:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    # The application launcher may select an absolute interpreter without
    # activating its environment, leaving the matching CLI outside PATH.
    try:
        environment_bin = Path(sys.executable).resolve().parent
    except Exception:
        environment_bin = None
    if environment_bin is None:
        return None

    # Keep the POSIX single-item tuple explicit. ``("")`` is a string and
    # would iterate zero times, which silently breaks Conda-only discovery.
    suffixes = ("", ".exe", ".cmd", ".bat") if os.name == "nt" else ("",)
    for name in _CLI_NAMES:
        for suffix in suffixes:
            candidate = environment_bin / f"{name}{suffix}"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


__all__ = ["find_totalsegmentator_executable"]
