"""Terminology, localization, and functional-scope guards for English copy."""
from pathlib import Path
import re

import pytest

from test_planning_distance_annotations_browser import browser, page, install

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/'web/app/static/js'


@pytest.mark.parametrize('obsolete', [
    r'\bGuide mouths?\b',r'\bDose current\b',r'\bhas updated\b',r'\bcaptures preparing\b',
    r'\bIn Lowest Dose\b',r'\bOut Highest Dose\b',r'D2 \(max(?: dose)?\)',
    r'Developed by SJTU &&',r'Particle Implantation \(5-step',
])
def test_obsolete_or_misleading_fixed_english_is_not_user_facing(obsolete):
    matches=[]
    for path in [ROOT/'web/app/index.html',*JS.glob('brachybot-*.js')]:
        text=path.read_text()
        if re.search(obsolete,text):matches.append(str(path.relative_to(ROOT)))
    assert not matches,matches


def test_guide_entry_label_names_the_channel_without_changing_distance_or_identifiers(page):
    packet=install(page)
    text=page.locator('.planning-distance-overlay').text_content()
    assert 'Guide channel entry' in text and '50.0 mm' in text
    assert 'Guide mouth' not in text
    guide=next(r for r in page.evaluate('state.annotations') if r.get('kind')=='guide_entry_tip_distance')
    assert guide['anchor_definition']=='generated_primary_sleeve_outer_mouth_axis_center'
    assert guide['tip_distance_mm']==50 and guide['units']=='mm'
    page.evaluate('window._i18nLang="zh";window.dispatchEvent(new CustomEvent("i18nchange"))')
    assert '导板入口' in page.locator('.planning-distance-overlay').text_content()
    assert 'Guide channel entry' not in page.locator('.planning-distance-overlay').text_content()
    assert len(packet['records'])==3


def test_english_report_labels_distinguish_skin_entry_tip_and_off_axis_distance(page):
    # Use the product report dictionary without recreating its implementation.
    page.add_script_tag(path=str(JS/'brachybot-report-plan-tables.js'))
    labels=page.evaluate('_reportTableText("en")')
    assert labels['start']=='Skin entry point' and labels['end']=='Needle tip'
    assert labels['depth']=='Distance from needle tip'
    assert labels['offset']=='Off-axis distance'
    assert 'center' in labels['gap'] and 'not an intraoperative measurement' in labels['sampled']


def test_d2_is_not_mislabeled_as_dmax_on_any_metric_surface():
    for name in ['brachybot-chat-core.js','brachybot-ui-api.js','brachybot-dvh-planning.js']:
        source=(JS/name).read_text()
        assert 'D2 (dose to the hottest 2%)' in source
        assert 'D2 (max dose)' not in source and 'D2 (max)' not in source
    core=(ROOT/'agent_runtime/core.py').read_text()
    assert 'D2 (dose to the hottest 2% of the target volume, in Gy)' in core
    assert 'D2 (max dose in Gy)' not in core


def test_dose_surface_mode_labels_are_localized_in_each_lifecycle_path():
    for name in ['brachybot-viewer-layout.js','brachybot-workspace.js','brachybot-ui-api.js','brachybot-3d-manual.js']:
        source=(JS/name).read_text()
        assert "'剂量着色','Dose coloring'" in source
    assert "'结构颜色','Structure colors'" in (JS/'brachybot-viewer-layout.js').read_text()
    guidance=(ROOT/'agent_runtime/chat_workflows.py').read_text()
    assert 'Switch the 3D Viewer back to Structure colors' in guidance
    assert 'Toggle Normal Surface' not in guidance
    from agent_runtime.ui_control_manual import catalog
    surface=next(card for card in catalog() if card['key']=='viewer.surface')
    assert surface['names']['en']=='Dose coloring / Structure colors'
    assert 'dose is not recalculated' in surface['result']['en']


def test_landing_page_and_translation_dictionary_have_matching_nonapproval_copy():
    html=(ROOT/'web/app/index.html').read_text();core=(JS/'brachybot-chat-core.js').read_text()
    for source in [html,core]:
        assert 'AI · Brachytherapy · Planning support' in source
        assert 'Clinical-grade' not in source
        assert 'OAR-aware safe trajectories' not in source
        assert 'Sub-millimeter sliding-window inference aggregates per-seed dose in seconds.' not in source


