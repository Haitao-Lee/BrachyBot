"""Export proposals, real serializers and browser save interactions (synthetic)."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agent_runtime.export_request import export_dialog_requested, validate_export_dialog_options
from agent_runtime.execution_authorization import tool_call_is_mutating
from agent_runtime.request_parse import mutating_execution_authorized
from agent_runtime.response_tools import ResponseToolMixin
from tool_factory.ui_controller import UIControllerTool
from web.export_service import ExportService, ExportJobManager, ExportError, export_filename, validate_export_selections
from web.surgical_guide import parse_stl, mesh_validation
from test_data_tree_export_system import _case
from test_report_plan_tables_browser import browser, page as report_page

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('message', [
    '导出报告', '导出导板', '导出当前针道和粒子模型的stl',
    '仅导出报告，不要重新规划', '把整个session所有数据导出',
    '以CSV格式导出当前DVH', '以JSON格式导出标注',
    'Export the guide as STL', 'Export all Session data',
    'Export only the needles and seeds as STL; do not replan',
    'Export the spinal cord mask in NIfTI format',
    '把报告另存为PDF', 'Download the guide as STL',
])
def test_semantic_export_proposals_survive_the_real_provider_boundary(message):
    class Agent(ResponseToolMixin):
        memory = SimpleNamespace(conversation=[{'role': 'user', 'content': message}])
        def _current_human_message(self):
            return message
    call = {'tool': 'ui_controller', 'params': {'actions': [
        {'target': 'data.export', 'command': 'run', 'value': {'names': ['Spinal cord'], 'format': 'nifti'}}]}}
    assert export_dialog_requested(message)
    result = Agent()._normalize_tool_params([call])
    assert result and result[0]['params']['actions'][0]['target'] == 'data.export'
    assert not tool_call_is_mutating('ui_controller', result[0]['params'])
    for producer in ('planning_pipeline', 'report_auto_fill', 'surgical_guide'):
        assert not mutating_execution_authorized(message, producer, params={'action': 'generate'})


@pytest.mark.parametrize('message', ['怎么导出报告？', '不要导出导板', '如果我同意再导出报告',
    '他刚才说“导出整个Session”', 'How do I export the guide?', 'The report was exported already'])
def test_export_mentions_are_not_commands(message):
    assert not export_dialog_requested(message)
    class Agent(ResponseToolMixin):
        memory = SimpleNamespace(conversation=[{'role': 'user', 'content': message}])
        def _current_human_message(self): return message
    assert not Agent()._normalize_tool_params([{'tool': 'ui_controller', 'params': {'actions': [
        {'target': 'data.export', 'command': 'run', 'value': {'all': True}}]}}])


@pytest.mark.parametrize('value', [{'all': 'true'}, {'path': '/tmp/out'}, {'confirm': True},
    {'object_ids': 'all'}, {'all': True, 'names': ['CTV']}, {'filenames': []}, {'format': ''}])
def test_chooser_options_are_strict(value):
    with pytest.raises(ValueError):
        validate_export_dialog_options(value)
    result = UIControllerTool()._execute(actions=[{'target': 'data.export', 'command': 'run', 'value': value}])
    assert not result.success


def test_chooser_acceptance_is_not_an_execution_or_save_receipt():
    result = UIControllerTool()._execute(actions=[{'target': 'data.export', 'command': 'run', 'value': {'all': True}}])
    assert result.success
    assert result.metadata['executed'] == 0
    assert result.metadata['execution_claim'] == 'accepted_pending_browser'
    assert not tool_call_is_mutating('ui_controller', {'actions': [{'target': 'data.export', 'command': 'run'}]})
    assert tool_call_is_mutating('ui_controller', {'actions': [{'target': 'data.export', 'command': 'run'}, {'target': 'plan.reset', 'command': 'run'}]})


@pytest.mark.parametrize('name', ['../bad.stl', 'C:\\bad.stl', '/tmp/bad.stl', 'CON.stl', 'bad.', '', 'bad\x00.stl', 'not-pdf.pdf'])
def test_invalid_user_filenames(name):
    with pytest.raises(ExportError):
        export_filename(name, '.stl')


def test_selection_validation_rejects_unknown_duplicate_and_wrong_formats(tmp_path):
    store, user, session, agent = _case(tmp_path)
    catalog = ExportService(store).catalog(user['id'], session.id, agent)
    good = {'object_id': 'seed:seed_1', 'format': 'stl', 'filename': '粒子.stl'}
    assert validate_export_selections(catalog, [good]) == [good]
    for selections in ([good, good], [good, {'object_id': 'missing'}],
                       [{'object_id': 'seed:seed_1', 'format': 'pdf'}], 'all', [None]):
        with pytest.raises(ExportError):
            validate_export_selections(catalog, selections)


@pytest.mark.parametrize('object_id', ['needle:needle_1', 'seed:seed_1'])
def test_real_stl_matches_patient_geometry_and_is_closed(tmp_path, object_id):
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    item = next(item for item in service.catalog(user['id'], session.id, agent) if item.object_id == object_id)
    path = service.export_object(user['id'], session.id, agent, item, 'stl', tmp_path / 'out', filename='model.stl')
    vertices, faces = parse_stl(path.read_bytes())
    assert mesh_validation(vertices, faces)['watertight']
    assert np.isfinite(vertices).all()
    assert np.allclose(vertices[:, :2].mean(axis=0), [4, 5])
    if object_id.startswith('needle'):
        assert np.allclose([vertices[:, 2].min(), vertices[:, 2].max()], [10, 40])
    else:
        assert np.allclose([vertices[:, 2].min(), vertices[:, 2].max()], [17.75, 22.25])


@pytest.mark.parametrize('kind', ['nan', 'zero_direction', 'zero_length', 'stale_guide', 'legacy_guide', 'open_guide'])
def test_invalid_models_are_not_exported_or_regenerated(tmp_path, kind):
    store, user, session, agent = _case(tmp_path)
    memory = agent.memory
    oid = 'seed:seed_1'
    if kind == 'nan': memory.retrieve('manual_seeds')[0]['position'][0] = float('nan')
    if kind == 'zero_direction': memory.retrieve('manual_seeds')[0]['direction'] = [0, 0, 0]
    if kind == 'zero_length':
        oid = 'needle:needle_1'
        memory.retrieve('manual_needles')[0]['points'] = [[4, 5, 40], [4, 5, 40]]
    if kind.endswith('guide'):
        oid = 'surgical_guide:active'
        if kind == 'stale_guide': memory.retrieve('surgical_guide')['status'] = 'stale'
        if kind == 'legacy_guide': memory.retrieve('surgical_guide').pop('validation')
        if kind == 'open_guide': memory.retrieve('surgical_guide')['faces'].pop()
    service = ExportService(store)
    item = next(item for item in service.catalog(user['id'], session.id, agent) if item.object_id == oid)
    with pytest.raises((ExportError, ValueError)):
        service.export_object(user['id'], session.id, agent, item, 'stl', tmp_path / 'out')


def test_job_preserves_names_checksums_and_settings(tmp_path):
    import hashlib
    store, user, session, agent = _case(tmp_path)
    manager = ExportJobManager(store, lambda _user, _sid: agent)
    job = manager.create(user, session.id, [
        {'object_id': 'seed:seed_1', 'format': 'stl', 'filename': 'Seed-one.stl'},
        {'object_id': 'session:settings', 'format': 'json', 'filename': 'settings.json'}], session.title, bundle_name='My-plan')
    deadline = time.monotonic() + 10
    while job.status in manager._ACTIVE_STATES and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status == 'completed', job.failures
    assert Path(job.export_root).name == 'My-plan'
    record = next(row for row in job.files if row['object_id'] == 'seed:seed_1')
    path = Path(job.export_root) / record['relative_path']
    assert path.name == 'Seed-one.stl'
    assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record['coordinate_system'] == 'LPS' and record['unit'] == 'mm'
    manifest = json.loads((Path(job.export_root) / 'session_manifest.json').read_text())
    assert manifest['native_workspace_backup'] is False


def test_linked_dicom_export_reuses_physical_dose_and_channel_ownership(tmp_path):
    import zipfile
    import pydicom
    store, user, session, agent = _case(tmp_path)
    service = ExportService(store)
    item = next(item for item in service.catalog(user['id'], session.id, agent) if item.object_id == 'dicom_rt:plan')
    path = service.export_object(user['id'], session.id, agent, item, 'dicom_rt', tmp_path / 'out')
    with zipfile.ZipFile(path) as archive:
        docs = [pydicom.dcmread(__import__('io').BytesIO(archive.read(name))) for name in archive.namelist() if name.endswith('.dcm')]
    assert {doc.Modality for doc in docs} == {'RTSTRUCT', 'RTPLAN', 'RTDOSE'}
    dose = next(doc for doc in docs if doc.Modality == 'RTDOSE')
    assert dose.DoseUnits == 'GY'
    assert np.allclose(dose.pixel_array * float(dose.DoseGridScaling), agent.memory.retrieve('dose_distribution_physical_gy'), atol=.01)
    agent.memory.retrieve('manual_seeds')[0]['needle_id'] = 'unknown'
    with pytest.raises(ExportError, match='ownership'):
        service.export_object(user['id'], session.id, agent, item, 'dicom_rt', tmp_path / 'invalid')


@pytest.fixture
def save_page(browser):
    context = browser.new_context(viewport={'width': 1200, 'height': 950})
    page = context.new_page()
    page.goto('about:blank')
    page.set_content('<!doctype html><html lang="en"><body><button id="opener">Open</button></body></html>')
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_script_tag(content="""
      var activeSessionId='case'; window._i18nLang='en';
      window.effectiveUiLanguage=()=>window._i18nLang;
      window.escHtml=s=>String(s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
      window.calls=[]; window.created=0;
      const fmt=(key,extension)=>({key,extension,label:key.toUpperCase()});
      window.catalog={groups:[{object_id:'group:planning',name:'Planning',parent_id:null}],objects:[
        {object_id:'needle:n1',parent_id:'group:planning',name:'Needle 1',data_type:'needle',default_format:'json',formats:[fmt('json','.json'),fmt('stl','.stl')]},
        {object_id:'seed:s1',parent_id:'group:planning',name:'Seed 1',data_type:'seed',default_format:'json',formats:[fmt('json','.json'),fmt('stl','.stl')]}
      ]};
      window.fetch=async(url,opts={})=>{
        calls.push({url,opts});
        if(url==='/api/data/catalog')return new Response(JSON.stringify(catalog));
        if(url==='/api/data/exports') {created++;return new Response(JSON.stringify({job:{job_id:'job'}}));}
        if(url==='/api/data/exports/job')return new Response(JSON.stringify({job:{job_id:'job',status:'completed',completed:1,total:1,folder_name:'My-plan',files:[{object_id:'needle:n1',relative_path:'Planning/Needle-one.stl'}]}}));
        return new Response('solid needle\\nendsolid needle');
      };
    """)
    page.add_script_tag(path=str(ROOT / 'web/app/static/js/brachybot-data-export.js'))
    page.add_style_tag(content=':root{--bg-1:#101727;--bg-2:#141d30;--bg-3:#1a243b;--border:#33415c;--border-soft:#28364b;--text:#edf2fb;--text-secondary:#a6b1c6;--primary:#527aff;--font-mono:monospace;}body{background:#0c1220;font:14px Arial;}')
    page.add_style_tag(path=str(ROOT / 'web/app/static/css/brachybot-data-export.css'))
    yield page
    context.close()
    assert not errors, errors


def open_dialog(page, options):
    return page.evaluate('o=>openSessionExportDialog(o)', options)


def test_real_dialog_preserves_subset_and_defers_generation(save_page):
    page = save_page
    result = open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    assert result['status'] == 'awaiting_user_confirmation' and result['saved'] is False
    assert page.evaluate('created') == 0
    assert page.locator('tr[data-object-id="needle:n1"] input[type=checkbox]').is_checked()
    assert not page.locator('tr[data-object-id="seed:s1"] input[type=checkbox]').is_checked()
    page.locator('[data-export-close]').click()
    assert page.locator('[role=dialog]').count() == 0
    assert page.evaluate('created') == 0


@pytest.mark.parametrize('options', [{'object_ids': ['missing']}, {'names': ['Not-a-real-structure']}, {'data_types': ['oar']}, {'data_types': ['needle'], 'format': 'obj'}])
def test_unresolved_or_unsupported_selection_never_becomes_export_all(save_page, options):
    open_dialog(save_page, options)
    assert save_page.locator('tr[data-object-id] input[type=checkbox]:checked').count() == 0
    assert save_page.locator('[data-export-start]').is_disabled()


def test_native_file_picker_cancel_precedes_any_generation(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    page.evaluate("() => {Object.defineProperty(window,'isSecureContext',{value:true}); window.showSaveFilePicker=async()=>{throw new DOMException('cancel','AbortError')}}")
    page.locator('[data-export-start]').click()
    page.wait_for_function('document.querySelector("[data-export-summary]").textContent.includes("cancelled")')
    assert page.evaluate('created') == 0


def test_native_save_writes_selected_blob_and_not_zip(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    page.locator('tr[data-object-id="needle:n1"] [data-export-filename]').fill('Needle-one.stl')
    page.evaluate("""Object.defineProperty(window,'isSecureContext',{value:true});
        window.written='';window.showSaveFilePicker=async()=>({createWritable:async()=>({write:async b=>{window.written=await b.text()},close:async()=>{},abort:async()=>{}})})""")
    page.locator('[data-export-start]').click()
    page.wait_for_function('document.querySelector("[data-export-summary]").textContent.includes("Saved:")')
    assert page.evaluate('written').startswith('solid needle')
    assert page.evaluate('JSON.parse(calls.find(c=>c.url==="/api/data/exports").opts.body).selections') == [
        {'object_id': 'needle:n1', 'format': 'stl', 'filename': 'Needle-one.stl'}]


def test_global_locale_and_keyboard_behaviour(save_page):
    page = save_page
    page.locator('#opener').focus()
    open_dialog(page, {'all': True})
    page.evaluate("window._i18nLang='zh';window.dispatchEvent(new Event('i18nchange'))")
    assert page.locator('[data-export-folder]').inner_text() == '选择文件夹'
    assert page.locator('thead th').last.inner_text() == '文件名'
    page.keyboard.press('Escape')
    assert page.locator('[role=dialog]').count() == 0
    assert page.evaluate('document.activeElement.id') == 'opener'


def test_dialog_pdf_is_explicit_print_not_saved_receipt(save_page):
    page = save_page
    page.evaluate("window.reportForm={};window.exportReportPDF=async o=>{window.pdfOptions=o;return {success:true,status:'print_dialog_opened',saved:false}}")
    open_dialog(page, {'data_types': ['report'], 'format': 'pdf'})
    page.locator('[data-export-start]').click()
    page.wait_for_function('window.pdfOptions?.confirmed===true')
    assert page.evaluate('created') == 0
    assert 'cannot verify' in page.locator('[data-export-summary]').inner_text()


def test_busy_dialog_cannot_be_replaced_and_timer_moves(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    page.evaluate("() => {window.originalFetch=window.fetch;window.fetch=async(u,o)=>u==='/api/data/exports'?new Promise(r=>window.release=r):originalFetch(u,o)}")
    page.locator('[data-export-start]').click()
    page.wait_for_timeout(300)
    before = page.locator('[data-export-elapsed]').inner_text()
    result = open_dialog(page, {'all': True})
    assert result['success'] is False
    page.wait_for_timeout(300)
    assert page.locator('[data-export-elapsed]').inner_text() != before
    page.locator('[data-export-cancel]').click()
    page.evaluate('release(new Response(JSON.stringify({job:{job_id:"job"}})))')
    page.wait_for_function('calls.some(c=>c.url.endsWith("/cancel"))')


def test_synthetic_dialog_layout(save_page, tmp_path):
    open_dialog(save_page, {'data_types': ['needle', 'seed'], 'format': 'stl', 'bundle_name': 'Implant-models'})
    assert save_page.locator('[role=dialog]').evaluate('(n)=>n.scrollWidth<=n.clientWidth')
    save_page.screenshot(path=str(tmp_path / 'save-data-dialog.png'))


def test_download_fallback_has_correct_filename_and_honest_completion(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'STL'})
    with page.expect_download() as event:
        page.locator('[data-export-start]').click()
    download = event.value
    assert download.suggested_filename == 'Needle-one.stl'
    assert download.failure() is None
    assert 'Download requested' in page.locator('[data-export-summary]').inner_text()
    assert 'Saved:' not in page.locator('[data-export-summary]').inner_text()


def test_native_writer_failure_aborts_without_claiming_saved(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    page.evaluate("""() => {Object.defineProperty(window,'isSecureContext',{value:true});
        window.aborted=false;window.showSaveFilePicker=async()=>({createWritable:async()=>({write:async()=>{throw new Error('Disk full')},close:async()=>{},abort:async()=>{aborted=true}})})} """)
    page.locator('[data-export-start]').click()
    page.wait_for_function('aborted')
    assert 'Disk full' in page.locator('[data-export-summary]').inner_text()
    assert 'Saved:' not in page.locator('[data-export-summary]').inner_text()


def test_directory_export_does_not_overwrite_existing_folder(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'format': 'stl'})
    page.evaluate("""() => {Object.defineProperty(window,'isSecureContext',{value:true});
        window.folderCalls=[];window.showDirectoryPicker=async()=>({name:'Destination',getDirectoryHandle:async(n,o)=>{folderCalls.push({n,o});return {}}})} """)
    page.locator('[data-export-folder]').click()
    page.locator('[data-export-start]').click()
    page.wait_for_function('document.querySelector("[data-export-summary]").textContent.includes("already exists")')
    assert page.evaluate('folderCalls.some(c=>c.o?.create)') is False
    assert page.evaluate('created') == 0  # Collision is caught before expensive serialization.


def test_late_chat_save_dialog_does_not_open_in_another_case(save_page):
    page = save_page
    page.evaluate("""() => {window.fetch=()=>new Promise(r=>window.catalogReply=r);
        window.opening=openSessionExportDialog({sessionId:'case',requireCurrentSession:true})} """)
    page.evaluate("activeSessionId='another';catalogReply(new Response(JSON.stringify(catalog)))")
    result = page.evaluate('opening')
    assert result['stale'] is True
    assert page.locator('[role=dialog]').count() == 0


def test_large_real_scene_has_no_old_512_object_ceiling(tmp_path):
    store, user, session, agent = _case(tmp_path)
    item = ExportService(store).catalog(user['id'], session.id, agent)[0]
    from dataclasses import replace
    catalog = [replace(item, object_id=f'image:{i}') for i in range(600)]
    selections = [{'object_id': item.object_id, 'format': 'nifti'} for item in catalog]
    assert len(validate_export_selections(catalog, selections)) == 600


def test_volume_with_mismatched_geometry_is_not_silently_relabelled(tmp_path):
    from web.export_service import _write_nifti
    store, user, session, agent = _case(tmp_path)
    with pytest.raises(ExportError, match='grids differ'):
        _write_nifti(np.zeros((1, 2, 3), dtype=np.uint8), tmp_path / 'bad.nii.gz', agent.memory)


def test_saved_guide_version_is_not_substituted_with_the_active_alias(tmp_path):
    from copy import deepcopy
    store, user, session, agent = _case(tmp_path)
    old = deepcopy(agent.memory.retrieve('surgical_guide'))
    old['version'] = 1
    old['vertices'] = (np.asarray(old['vertices']) + [100, 0, 0]).tolist()
    agent.memory.store('surgical_guide_versions', [old])
    service = ExportService(store)
    item = next(row for row in service.catalog(user['id'], session.id, agent) if row.object_id == 'surgical_guide:version:1')
    path = service.export_object(user['id'], session.id, agent, item, 'stl', tmp_path / 'out')
    vertices, _ = parse_stl(path.read_bytes())
    assert vertices[:, 0].min() == 100
    assert agent.memory.retrieve('surgical_guide')['version'] == 2


def test_browser_guide_version_selector_preserves_identity(save_page):
    page = save_page
    page.evaluate("catalog.objects=[1,2].map(v=>({object_id:'guide:'+v,name:'Guide '+v,data_type:'surgical_guide',metadata:{version:v},formats:[{key:'stl',label:'STL',extension:'.stl'}],default_format:'stl'}))")
    open_dialog(page, {'data_types': ['surgical_guide'], 'guide_version': 1, 'format': 'stl'})
    assert page.locator('tr[data-object-id="guide:1"] input[type=checkbox]').is_checked()
    assert not page.locator('tr[data-object-id="guide:2"] input[type=checkbox]').is_checked()


def test_structural_exclusions_and_mixed_formats_share_one_chooser(save_page):
    page = save_page
    open_dialog(page, {'all': True, 'exclude_data_types': ['seed'], 'formats_by_type': {'needle': 'stl'}})
    assert page.locator('tr[data-object-id="needle:n1"] input[type=checkbox]').is_checked()
    assert not page.locator('tr[data-object-id="seed:s1"] input[type=checkbox]').is_checked()
    assert page.locator('tr[data-object-id="needle:n1"] select').input_value() == 'stl'
    page.locator('[data-export-close]').click()
    open_dialog(page, {'data_types': ['needle', 'seed'], 'formats_by_type': {'needle': 'stl', 'seed': 'json'}})
    assert page.locator('tr[data-object-id="needle:n1"] select').input_value() == 'stl'
    assert page.locator('tr[data-object-id="seed:s1"] select').input_value() == 'json'


def test_later_model_proposal_cannot_silently_replace_an_open_chooser(save_page):
    page = save_page
    open_dialog(page, {'data_types': ['needle'], 'requireCurrentSession': True})
    result = open_dialog(page, {'data_types': ['seed'], 'requireCurrentSession': True})
    assert result['success'] is False
    assert page.locator('tr[data-object-id="needle:n1"] input[type=checkbox]').is_checked()


def test_shared_transport_receipt_never_claims_dialog_means_saved(save_page):
    source = (ROOT / 'web/app/static/js/brachybot-chat-todo.js').read_text()
    helper = 'function _verifiedExportDialogReply' + source.split('function _verifiedExportDialogReply', 1)[1].split('function _verifiedTreeVisibilityReply', 1)[0]
    save_page.add_script_tag(content=helper)
    result = save_page.evaluate("""_verifiedExportDialogReply([
        {tool:'ui_controller',metadata:{actions:[{target:'data.export',command:'run'}]}},
        {tool:'ui-action-1',parent_tool:'ui_controller'}], [{success:true,status:'awaiting_user_confirmation',saved:false}], 'en')""")
    assert result['onlyChoosers'] is True
    assert 'No files have been generated or saved' in result['text']


def test_save_and_close_publish_their_terminal_state_to_the_original_owner(save_page):
    page = save_page
    page.evaluate("() => {window.outcomes=[];window.opening=openSessionExportDialog({data_types:['needle'],format:'stl',onState:r=>outcomes.push(r)})}")
    page.evaluate('opening')
    page.locator('[data-export-close]').click()
    assert page.evaluate('outcomes.at(-1).status') == 'cancelled'
    page.evaluate("() => {window.opening=openSessionExportDialog({data_types:['needle'],format:'stl',onState:r=>outcomes.push(r)});Object.defineProperty(window,'isSecureContext',{value:true});window.showSaveFilePicker=async()=>({createWritable:async()=>({write:async()=>{},close:async()=>{},abort:async()=>{}})})}")
    page.evaluate('opening')
    page.locator('[data-export-start]').click()
    page.wait_for_function('outcomes.at(-1).status==="saved"')
    assert page.evaluate('outcomes.at(-1).saved') is True


@pytest.mark.parametrize('outcome', ['saved', 'cancelled', 'download_requested'])
def test_real_orchestrator_tracks_late_save_receipts_without_false_dependency_release(save_page, outcome):
    page = save_page
    source = (ROOT / 'web/app/static/js/brachybot-ui-api.js').read_text()
    section = 'const _UI_ACTION_RUNNING_STATES' + source.split('const _UI_ACTION_RUNNING_STATES', 1)[1].split('window._executeUIActionsWithProgress', 1)[0]
    page.add_script_tag(content="""
        window._uiActionSessionIsCurrent=()=>true;
        window._executeUIAction=(a,o)=>openSessionExportDialog({...a.value,requireCurrentSession:true,onState:o.onExportState});
        window.traceEvents=[];document.addEventListener('brachy:ui-action-progress',e=>traceEvents.push(e.detail));
    """)
    page.add_script_tag(content=section)
    page.evaluate("""() => {window.batch=_executeUIActionsWithProgress([
        {target:'data.export',command:'run',value:{data_types:['needle'],format:'stl'}}],
        {sessionId:'case',requestId:'save-request'})} """)
    initial = page.evaluate('batch')
    assert initial[0]['status'] == 'awaiting_user_confirmation'
    if outcome == 'cancelled': page.locator('[data-export-close]').click()
    else:
        if outcome == 'saved':
            page.evaluate("""() => {Object.defineProperty(window,'isSecureContext',{value:true});
                window.showSaveFilePicker=async()=>({createWritable:async()=>({write:async()=>{},close:async()=>{},abort:async()=>{}})})} """)
        page.locator('[data-export-start]').click()
    page.wait_for_function('expected=>traceEvents.at(-1)?.metadata?.exportState===expected', arg=outcome)
    event = page.evaluate('traceEvents.at(-1)')
    assert event['session_id'] == 'case' and event['request_id'] == 'save-request'
    assert event['status'] == ('cancelled' if outcome == 'cancelled' else 'done')
    assert page.evaluate('_uiActionStepLedger("case|save-request").get("step-1")') == ('completed' if outcome == 'saved' else outcome)
    assert page.evaluate('batch.then(r=>r[0].status)') == outcome


def test_manual_replacement_cancels_the_original_chooser_receipt(save_page):
    page = save_page
    page.evaluate("() => {window.outcomes=[];window.first=openSessionExportDialog({data_types:['needle'],onState:r=>outcomes.push(r)})}")
    page.evaluate('first')
    open_dialog(page, {'data_types': ['seed']})
    assert page.evaluate('outcomes.at(-1).status') == 'cancelled'


def test_unresolved_chat_scope_does_not_default_to_the_entire_scene(save_page):
    result = open_dialog(save_page, {'requireCurrentSession': True})
    assert result['selected_count'] == 0
    assert save_page.locator('tr[data-object-id] input[type=checkbox]:checked').count() == 0
    assert save_page.locator('[data-export-start]').is_disabled()


def test_markdown_serialization_does_not_mutate_the_operator_report(report_page):
    page = report_page
    before = page.evaluate('JSON.stringify(reportForm, (k,v)=>v instanceof Set?[...v]:v)')
    data = page.evaluate('async()=>{const b=await exportReportMarkdown({returnBlob:true});return {type:b.type,text:await b.text()}}')
    assert data['type'] == 'text/markdown'
    assert data['text'].startswith('# ')
    assert page.evaluate('JSON.stringify(reportForm, (k,v)=>v instanceof Set?[...v]:v)') == before


def test_partial_workspace_restoration_cannot_masquerade_as_export_all(tmp_path):
    store, user, session, agent = _case(tmp_path)
    agent._workspace_data_ready = False
    # Data Tree metadata can still render while resources hydrate.
    assert ExportService(store).public_catalog(user['id'], session.id, agent)['resources_ready'] is False
    with pytest.raises(ExportError, match='restoring'):
        ExportJobManager(store, lambda _user, _sid: agent).create(user, session.id,
            [{'object_id': 'image:ct', 'format': 'nifti'}], session.title)


def test_failed_dialog_opening_replaces_a_false_success_claim(save_page):
    source = (ROOT / 'web/app/static/js/brachybot-chat-todo.js').read_text()
    helper = 'function _verifiedExportDialogReply' + source.split('function _verifiedExportDialogReply', 1)[1].split('function _verifiedTreeVisibilityReply', 1)[0]
    save_page.add_script_tag(content=helper)
    result = save_page.evaluate("""_verifiedExportDialogReply([{tool:'ui_controller',metadata:{actions:[{target:'data.export'}]}}],
        [{success:false,error:'Case resources are still restoring'}], 'en')""")
    assert result['onlyChoosers'] is True
    assert 'did not complete' in result['text'] and 'restoring' in result['text']


def test_old_report_owner_cannot_export_as_the_new_case(save_page):
    save_page.evaluate("window.reportForm={sessionId:'another-case'}")
    with pytest.raises(Exception, match='does not belong'):
        open_dialog(save_page, {'data_types': ['report'], 'format': 'pdf'})
    assert save_page.evaluate('created') == 0


def test_a_second_refused_export_does_not_disappear_from_the_final_reply(save_page):
    source = (ROOT / 'web/app/static/js/brachybot-chat-todo.js').read_text()
    helper = 'function _verifiedExportDialogReply' + source.split('function _verifiedExportDialogReply', 1)[1].split('function _verifiedTreeVisibilityReply', 1)[0]
    save_page.add_script_tag(content=helper)
    result = save_page.evaluate("""_verifiedExportDialogReply([{tool:'ui_controller',metadata:{actions:[{target:'data.export'},{target:'report.export'}]}}],
        [{success:true,export_dialog:true,status:'awaiting_user_confirmation'}, {success:false,error:'A save dialog is already open'}], 'en')""")
    assert result['success'] is False
    assert 'Other exports were not submitted' in result['text']


def test_json_preserves_numpy_numbers_and_rejects_nonfinite_data(tmp_path):
    path = tmp_path / 'dvh.json'
    ExportService._write_json(path, {'bins': np.array([1., 2.]), 'count': np.int64(3)})
    assert json.loads(path.read_text()) == {'bins': [1., 2.], 'count': 3}
    with pytest.raises(ValueError):
        ExportService._write_json(tmp_path / 'bad.json', {'bins': np.array([float('nan')])})


def test_browser_report_can_write_to_the_selected_folder(save_page):
    page = save_page
    page.evaluate("window.reportForm={sessionId:'case'};window.exportReportHTML=async()=>new Blob(['<h1>report</h1>'],{type:'text/html'})")
    open_dialog(page, {'data_types': ['report'], 'format': 'html'})
    page.evaluate("""() => {
      Object.defineProperty(window,'isSecureContext',{value:true});window.writtenFiles=[];
      window.showDirectoryPicker=async()=>({name:'Destination',getDirectoryHandle:async(n,o)=>{
        if(!o?.create)throw new DOMException('missing','NotFoundError');
        const folder={getDirectoryHandle:async()=>folder,getFileHandle:async name=>({createWritable:async()=>({
          write:async blob=>writtenFiles.push({name,text:await blob.text()}),close:async()=>{},abort:async()=>{}
        })})}; return folder;
      }});
    }""")
    page.locator('[data-export-folder]').click()
    page.locator('[data-export-start]').click()
    page.wait_for_function('writtenFiles.length===1')
    assert page.evaluate('writtenFiles[0].text') == '<h1>report</h1>'
    assert 'File saved' in page.locator('[data-export-summary]').inner_text()


def test_one_job_projects_structure_masks_once_and_detects_catalog_change(tmp_path, monkeypatch):
    import web.export_service as module
    store, user, session, agent = _case(tmp_path)
    original = module.build_effective_structures
    projections = []
    def project(memory):
        projections.append(True)
        return original(memory)
    monkeypatch.setattr(module, 'build_effective_structures', project)
    manager = ExportJobManager(store, lambda _user, _sid: agent)
    job = manager.create(user, session.id, [
        {'object_id': 'structure:ctv:1', 'format': 'nifti'},
        {'object_id': 'structure:oar:2', 'format': 'nifti'}], session.title)
    deadline = time.monotonic() + 10
    while job.status in manager._ACTIVE_STATES and time.monotonic() < deadline: time.sleep(.01)
    assert job.status == 'completed', job.failures
    assert len(projections) == 2  # admission projection + fenced job projection
