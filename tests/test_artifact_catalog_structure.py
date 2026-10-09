"""Durable artifact grouping and source-ownership metadata."""
from web.artifact_catalog import screenshot_attachment_index,legacy_screenshot_metadata
from web.export_service import ExportService
from test_data_tree_export_system import _case


def test_source_and_annotated_image_share_an_authoritative_capture():
    snapshot={'chat':{'attachments':[{'id':'c1','request_id':'r1','session_id':'case',
        'url':'/api/sessions/case/screenshots/chat_screenshot_x.png',
        'annotated_url':'/api/sessions/case/screenshots/annotated_chat_screenshot_x_hash.png',
        'planning_id':'old-plan','data_version':2,'target':'viewer-3d','created_at':123}]}}
    index=screenshot_attachment_index(snapshot,'case')
    assert len(index)==2
    assert index['chat_screenshot_x.png']['capture_source_id']==index['annotated_chat_screenshot_x_hash.png']['capture_source_id']=='c1'
    assert index['chat_screenshot_x.png']['planning_id']=='old-plan'
    assert index['annotated_chat_screenshot_x_hash.png']['capture_variant']=='annotated'


def test_foreign_urls_or_explicit_foreign_attachment_owner_never_group_as_ours():
    snapshot={'chat':{'attachments':[
        {'id':'foreign','session_id':'other','url':'/api/sessions/case/screenshots/x.png'},
        {'id':'foreignurl','session_id':'case','url':'/api/sessions/other/screenshots/y.png'},
    ]}}
    assert screenshot_attachment_index(snapshot,'case')=={}


def test_legacy_pairing_is_only_for_known_generated_filename_shape():
    original=legacy_screenshot_metadata('chat_screenshot_a12.png')
    marked=legacy_screenshot_metadata('annotated_chat_screenshot_a12_89ab.png')
    assert original['capture_source_id']==marked['capture_source_id']
    assert legacy_screenshot_metadata('unrelated_report.png')['artifact_family']=='unclassified_image'


def test_registry_wins_over_a_stale_message_copy_and_no_question_content_is_added():
    newest={'id':'c1','session_id':'case','url':'/api/screenshots/x.png','request_id':'new',
            'question':'sensitive content is not needed for catalog grouping'}
    old={**newest,'request_id':'old'}
    result=screenshot_attachment_index({'chat':{'attachments':[newest],'messages':[{'attachments':[old]}]}},'case')
    assert result['x.png']['request_id']=='new'
    assert 'question' not in result['x.png']


def test_catalog_keeps_original_owner_not_active_plan_and_existing_files(tmp_path):
    store,user,session,agent=_case(tmp_path)
    root=store.workspace_root(user['id'],session.id)
    original='chat_screenshot_a12.png';marked='annotated_chat_screenshot_a12_hash.png'
    for name in [original,marked]:(root/'screenshots'/name).write_bytes(b'PNG-test')
    store.save_snapshot_patch(user['id'],session.id,{'chat':{'attachments':[
        {'id':'c1','request_id':'r1','session_id':session.id,'planning_id':'old-plan','data_version':2,
         'url':f'/api/sessions/{session.id}/screenshots/{original}',
         'annotated_url':f'/api/sessions/{session.id}/screenshots/{marked}','target':'viewer-3d'}]}})
    catalog=ExportService(store).public_catalog(user['id'],session.id,agent)
    rows={r['object_id']:r for r in catalog['objects']}
    assert rows['screenshot:'+original]['planning_id']=='old-plan'
    assert rows['screenshot:'+original]['data_version']==2
    assert rows['screenshot:'+marked]['metadata']['capture_variant']=='annotated'
    assert rows['screenshot:dose.png']['planning_id'] is None
    assert (root/'screenshots'/original).read_bytes()==b'PNG-test'
    assert 'figure:figure.png' in rows and 'screenshot:figure.png' not in rows
