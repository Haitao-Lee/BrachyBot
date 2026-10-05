"""Exercise the actual frontend helpers for report-dose child failures."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_report_dose_answer_preserves_read_results():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for frontend contract regression tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/report_dose_answer.cjs"), str(root)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
