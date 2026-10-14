"""Execute production export frontend transport contracts."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest


def test_export_callbacks_retain_submission_owner_after_navigation():
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node is required for export callback contracts')
    result=subprocess.run([node,str(Path(__file__).with_name('export-timepoint-owner.test.cjs'))],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'ownership contracts passed' in result.stdout
