import os
from pathlib import Path
import shutil
import subprocess
import pytest


def test_observation_interactions_in_real_headless_browser():
    node=os.environ.get('BRACHYBOT_NODE') or shutil.which('node')
    if not node:pytest.skip('Node.js is required for implant browser validation')
    module=os.environ.get('PLAYWRIGHT_MODULE','playwright')
    if subprocess.run([node,'-e','require(process.argv[1])',module],capture_output=True).returncode:
        pytest.skip('Playwright is required for implant browser validation')
    result=subprocess.run([node,str(Path(__file__).with_name('implant-observations-browser.test.cjs'))],capture_output=True,text=True,timeout=75)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'late-target fences passed' in result.stdout


def test_legacy_planning_pointer_handlers_yield_to_observation_editing():
    root=Path(__file__).resolve().parents[1]/'web/app/static/js'
    source=(root/'brachybot-3d-manual.js').read_text(encoding='utf-8')
    for name in ('beginNeedleHandleDrag','handlePlanningPointerDown'):
        start=source.index('const '+name+' = (event) => {')
        assert 'BrachyBotImplants?.owns3DPointer(event)' in source[start:start+250]
    annotation=(root/'brachybot-manual-annotation.js').read_text(encoding='utf-8')
    start=annotation.index('function _ensureSeed2DInteraction(')
    assert 'BrachyBotImplants?.interactionMode()' in annotation[start:start+1800]
