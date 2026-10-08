"""Registry/source knowledge and workspace persistence for measurement removal."""
from pathlib import Path

from agent_runtime.ui_control_manual import coverage, usage_packet
from tool_factory.ui_controller import UIControllerTool, CONTROL_REGISTRY
from tool_factory.ui_inspector import UIInspectorTool


def test_clear_control_is_source_bound_and_not_a_mask_or_planning_clear():
    assert not coverage()['unknown_controls']
    packet=usage_packet('清除测量',language='zh')
    card=next(c for c in packet['cards'] if c['key']=='viewer.measurements.clear')
    assert '不删除手绘掩膜' in card['limits_and_exit']
    inspector=UIInspectorTool()._execute(component='toolClearMeasurements')
    assert inspector.data['results'][0]['action']['target']=='viewer.annotations'
    assert inspector.data['results'][0]['action']['command']=='clear_measurements'
    assert CONTROL_REGISTRY['viewer.annotations']['commands']==['undo','redo','clear_measurements']
    result=UIControllerTool()._execute(actions=[{'target':'viewer.annotations','command':'clear_measurements'}])
    assert result.success  # A browser plan, not a mutation completion receipt.


def test_annotation_empty_array_persists_and_restore_does_not_resurrect_old_rows(tmp_path):
    from test_data_tree_export_system import _case
    store,user,session,agent=_case(tmp_path)
    snapshot=store.load_snapshot(user['id'],session.id)
    ui=snapshot['ui']
    state=ui['state'] if isinstance(ui.get('state'),dict) else ui
    assert state['viewer']['annotations']
    state['viewer']['annotations']=[]
    store.save_snapshot_patch(user['id'],session.id,{'ui':ui},reason='viewer.annotations.remove')
    saved=store.load_snapshot(user['id'],session.id)
    restored=saved['ui'].get('state',saved['ui'])
    assert restored['viewer']['annotations']==[]


def test_clear_button_uses_versioned_existing_styles_and_preserves_other_delete_routes():
    root=Path(__file__).resolve().parents[1]
    markup=(root/'web/app/index.html').read_text()
    assert 'id="toolClearMeasurements"' in markup
    assert 'data-i18n-zh="清除测量"' in markup
    assert 'brachybot-manual-annotation.js?v=34' in markup
    source=(root/'web/app/static/js/brachybot-viewer-volume.js').read_text()
    assert "ids.every(id => id.startsWith('annotation:'))" in source
    assert "'/data/objects/batch-delete'" in source
