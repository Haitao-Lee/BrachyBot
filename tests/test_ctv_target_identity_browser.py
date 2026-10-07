"""Actual target-identity JS in isolated Chromium; not a real-case UI smoke."""
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = source.index('function ' + name + '(')
    suffix = source[start:]
    end = re.search(r'\n(?:async )?function ', suffix)
    result = suffix[:end.start()] if end else suffix
    # The public helper export sits between the function declarations.
    return result.split('\nwindow.')[0]


@pytest.fixture(scope='module')
def page():
    from playwright.sync_api import sync_playwright
    chrome = Path('/home/lht/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=str(chrome), headless=True,
            args=['--no-sandbox'])
        page = browser.new_page()
        js = (ROOT / 'web/app/static/js/brachybot-viewer-volume.js').read_text()
        manual = (ROOT / 'web/app/static/js/brachybot-3d-manual.js').read_text()
        page.evaluate('window.ctvStructureCatalog = [];')
        page.add_script_tag(content=function(js, 'isCTVTargetLabel')
            + '\nwindow.isCTVTargetLabel = isCTVTargetLabel;\n'
            + function(manual, '_screenshot3DIdentityFor'))
        yield page
        browser.close()


def test_header_targets_include_nodal_and_arbitrary_promoted_masks(page):
    result = page.evaluate('''() => {
        ctvStructureCatalog = []; window._ctvTargetLabels = [1, 2, 17];
        window._ctvLabelMap = {1: 'GTVp', 2: 'GTVn', 17: 'my contour'};
        return [1, 2, 17, 3].map(id => ({target: isCTVTargetLabel(id),
            identities: _screenshot3DIdentityFor(`ctv_${id}`, {userData:{labelId:id}})}));
    }''')
    assert [row['target'] for row in result] == [True, True, True, False]
    assert all('structure:ctv:active' in row['identities'] for row in result[:3])
    assert 'structure:ctv:active' not in result[3]['identities']


def test_catalog_owns_classification_despite_renames_and_stale_header(page):
    result = page.evaluate('''() => {
        ctvStructureCatalog = [{target_label:2, classification:'ctv'}, {target_label:17, classification:'ctv'}];
        window._ctvTargetLabels = [1]; window._ctvLabelMap = {2:'artery', 17:'user rename'};
        return [1,2,17].map(id => isCTVTargetLabel(id));
    }''')
    assert result == [False, True, True]


def test_legacy_gtv_fallback_never_promotes_pancreatic_vessels(page):
    result = page.evaluate('''() => {
        ctvStructureCatalog = []; window._ctvTargetLabels = null;
        window._ctvLabelMap = {1:'primary', 2:'GTVnd (nodal)', 3:'vein', 4:'pancreas'};
        const gtv = isCTVTargetLabel(2);
        window._ctvLabelMap[2] = 'artery';
        return [gtv, isCTVTargetLabel(2), isCTVTargetLabel(3), isCTVTargetLabel(4)];
    }''')
    assert result == [True, False, False, False]
