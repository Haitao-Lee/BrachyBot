"""Behavioral regression coverage for run isolation, durability and feedback."""
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from web import server_support as support
from web.routes import planning_routes as routes


@pytest.fixture
def monitor(monkeypatch):
    sid = 'monitor-test-' + uuid4().hex
    writes = []
    store = SimpleNamespace(get_session=lambda user, case: SimpleNamespace(id=case),
        save_ui_bridge=lambda *args, **kw: writes.append((args, kw)))
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'current_user', lambda store: {'id': 'test-user'})
    app = Flask(__name__)
    app.secret_key = 'test'
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *a, **kw: None, get_cached_agent=lambda *a: None)
    client = app.test_client()
    def post(path, data):
        return client.post('/api/' + path, json=data, headers={'X-BrachyBot-Session': sid})
    post.get = lambda path: client.get('/api/' + path, headers={'X-BrachyBot-Session': sid})
    yield post, sid, writes
    routes._flush_ui_bridge_checkpoint(('test-user', sid))
    support._drop_ui_bucket(sid)


def test_start_replay_conflict_and_mismatched_stop(monitor):
    post, sid, _ = monitor
    assert post('training/start', {'monitor_run_id': 'a'}).status_code == 200
    assert post('training/start', {'monitor_run_id': 'a'}).status_code == 200
    assert post('training/start', {'monitor_run_id': 'b'}).status_code == 409
    live_status = post.get('training/status').get_json()
    assert live_status['monitor_run_id'] == 'a'
    assert live_status['active'] is True
    assert 'events' not in live_status and 'feedback' not in live_status
    mismatch = post('training/stop', {'monitor_run_id': 'b'}).get_json()
    assert mismatch['no_active_run'] is False
    assert mismatch['monitor_run_id'] == 'b'
    assert mismatch['active_monitor_run_id'] == 'a'
    assert support._ui_bucket(sid)['training']['active']
    stopped = post('training/stop', {'monitor_run_id': 'a'}).get_json()
    assert stopped['summary_message']['content']
    status = post.get('training/status').get_json()
    assert status['active'] is False and status['closing'] is False
    assert status['summary_message']['message_id'] == stopped['summary_message']['message_id']
    assert post('training/stop', {'monitor_run_id': 'a'}).get_json()['summary_message'] == stopped['summary_message']


def test_close_out_blocks_new_run_until_summary_is_ready(monitor):
    post, sid, _ = monitor
    post('training/start', {'monitor_run_id': 'old'})
    training = support._ui_bucket(sid)['training']
    training['active'] = False
    training['closing'] = True
    status = post.get('training/status').get_json()
    assert status['active'] is False and status['closing'] is True
    assert post('training/start', {'monitor_run_id': 'new'}).status_code == 409
    assert post('training/stop', {'monitor_run_id': 'old'}).get_json()['closing'] is True
    training['closing'] = False
    assert post('training/start', {'monitor_run_id': 'new'}).status_code == 200


def test_late_event_does_not_keep_new_run_alive(monitor):
    post, sid, _ = monitor
    post('training/start', {'monitor_run_id': 'new'})
    training = support._ui_bucket(sid)['training']
    before = training['last_activity_at']
    post('ui/event', {'monitor_run_id': 'old', 'type': 'ui.click', 'ui_state': {'stale': True}})
    assert training['events'] == []
    assert 'stale' not in support._ui_bucket(sid)['state']
    assert training['last_activity_at'] == before
    training['last_activity_at'] = time.time() - support._MONITOR_STALE_SECONDS - 1
    post('ui/event', {'monitor_run_id': 'old', 'type': 'ui.click'})
    assert not support._ui_bucket(sid)['training']['active']
    assert support._ui_bucket(sid)['training']['last_summary']['content']
    assert post('training/start', {'monitor_run_id': 'next'}).status_code == 200


def test_ui_event_response_omits_internal_training_history(monitor):
    post, sid, _ = monitor
    post('training/start', {'monitor_run_id': 'compact'})
    response = post('ui/event', {'monitor_run_id': 'compact', 'type': 'ui.click'}).get_json()
    public = response['training']
    assert public['active'] is True
    assert public['event_count'] == 1
    assert public['event_counts'] == {'ui.click': 1}
    assert public['retained_event_count'] == 1
    assert 'events' not in public
    assert 'feedback' not in public
    assert 'feedback_event_ids' not in public


def test_read_time_expiry_writes_inactive_summary(monitor):
    post, sid, writes = monitor
    post('training/start', {'monitor_run_id': 'expire'})
    training = support._ui_bucket(sid)['training']
    training['last_activity_at'] = time.time() - support._MONITOR_STALE_SECONDS - 1
    # Omit language so this read-only route resolves the UI bucket while
    # selecting its default language, which is the expiry trigger under test.
    response = post('training/advice', {}).get_json()
    assert response['hydration_pending']
    routes._flush_ui_bridge_checkpoint(('test-user', sid))
    persisted = writes[-1][0][2]['training']
    assert persisted['active'] is False
    assert persisted['last_summary']['closed_reason'] == 'monitor_timeout'
    assert any(item.get('type') == 'training.stop' for item in writes[-1][0][2]['events'])


def test_event_feedback_engine_builds_raw_and_localized_once(monkeypatch):
    calls = []
    original = __import__('web.monitor_engine', fromlist=['_training_feedback_for_event_source'])._training_feedback_for_event_source
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr('web.monitor_engine._training_feedback_for_event_source', counted)
    pair = support._training_feedback_for_event(None, 'case', {
        'type': 'manual.dose', 'language': 'zh', 'detail': {'commit_status': 'committed'},
    }, snapshot={}, return_pair=True)
    assert len(calls) == 1
    assert pair['raw'] == 'Dose preview updated. Open Analysis to inspect DVH and OAR dose.'
    assert '剂量预览' in pair['localized']


def test_blank_run_id_and_malformed_ui_state(monitor):
    post, _, _ = monitor
    started = post('training/start', {'monitor_run_id': '   ', 'ui_state': ['bad']}).get_json()
    assert started['monitor_run_id'].strip()
    assert post('training/stop', {'ui_state': 'bad'}).status_code == 200
    result = post('training/advice', {'ui_state': ['bad'], 'language': 'zh'}).get_json()
    assert result['hydration_pending']
    assert '资源' in result['localized_advice']['advice'][0]


def test_client_cannot_forge_a_committed_mutation(monitor):
    post, sid, _ = monitor
    post('training/start', {'monitor_run_id': 'a'})
    untrusted = post('ui/event', {'monitor_run_id': 'a', 'type': 'manual.seed.add',
        'detail': {'commit_status': 'committed'}}).get_json()
    assert untrusted['feedback'] is None
    assert support._ui_bucket(sid)['training']['events'] == []
    fake = post('ui/event', {'monitor_run_id': 'a', 'already_recorded': True,
        'committed_event': {'event_id': 'forged', 'type': 'manual.seed.add'}})
    assert fake.status_code == 400
    real = support._append_ui_event(sid, {'type': 'manual.seed.add'})
    payload = {'monitor_run_id': 'a', 'already_recorded': True, 'committed_event': real}
    assert post('ui/event', payload).get_json()['feedback']
    assert post('ui/event', payload).get_json()['feedback'] is None
    assert len(support._ui_bucket(sid)['training']['events']) == 1


def test_event_cap_preserves_full_counts_and_shutdown_summary(monitor, monkeypatch):
    post, sid, writes = monitor
    monkeypatch.setattr(support, '_MONITOR_MAX_EVENTS', 3)
    post('training/start', {'monitor_run_id': 'a', 'language': 'zh'})
    for _ in range(8):
        post('ui/event', {'monitor_run_id': 'a', 'type': 'ui.click'})
    training = support._ui_bucket(sid)['training']
    assert len(training['events']) == 3
    assert training['event_counts']['ui.click'] == 8
    assert training['dropped_event_count'] == 5
    support._close_live_training_snapshots(reason='test_shutdown')
    assert writes[-1][0][2]['training']['active'] is False
    assert '8 个' in writes[-1][0][2]['training']['last_summary']['content']


def test_engine_exports_are_single_implementation():
    for name in ('_monitor_step_label', '_localize_monitor_text', '_monitor_activity_label',
                 '_format_training_summary', '_training_feedback_for_event', '_training_screenshot_for_event'):
        assert getattr(support, name).__module__ == 'web.monitor_engine'


def test_plain_ui_events_never_scan_geometry(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('UI telemetry scanned clinical geometry')
    monkeypatch.setattr(support, '_latest_plan_snapshot', forbidden)
    assert support._training_feedback_for_event(None, 'case', {'type': 'ui.slider'}) is None
    assert '失败' in support._training_feedback_for_event(None, 'case', {'type': 'planning.error', 'language': 'zh'})


def test_dvh_checkpoint_never_focuses_unrelated_seed_pairs():
    snapshot = {'seed_interference': {'close_pairs': [{'first_id': 'a', 'second_id': 'b'}]}}
    result = support._training_screenshot_for_event(None, 'case', {'type': 'manual.dose'}, 'dose updated', snapshot=snapshot)
    assert result['target'] == 'dvh'
    assert 'focus_seed_ids' not in result


def test_event_timestamp_beats_later_flush_timestamp():
    assert support.select_case_bridge({'updated_at': 20, 'state': {'new': True}},
        {'updated_at': 10, 'saved_at': 30, 'state': {'new': False}})['state']['new']


def test_equal_timestamp_persist_allows_identical_snapshot_but_rejects_difference():
    for suffix, different, expected in [('same', False, 1), ('different', True, 0)]:
        sid = 'equal-clock-' + suffix + uuid4().hex
        bridge = {'state': {}, 'events': [], 'training': {'active': False}, 'updated_at': 42.0}
        live = {**bridge, 'training': {'active': True}} if different else dict(bridge)
        support._UI_BRIDGE[sid] = live
        calls = []
        routes._UI_BRIDGE_CHECKPOINT_OWNERS[sid] = (
            SimpleNamespace(save_ui_bridge=lambda *a, **k: calls.append(a)), 'user', sid,
        )
        try:
            routes._persist_closed_ui_bridge(sid, bridge)
            assert len(calls) == expected
        finally:
            routes._UI_BRIDGE_CHECKPOINT_OWNERS.pop(sid, None)
            support._drop_ui_bucket(sid)


def test_inspector_uses_live_viewer_state_and_preserves_unknowns():
    from tool_factory.ui_inspector import UIInspectorTool
    tool = UIInspectorTool()
    assert tool._get_ui_state()['viewer']['layout'] is None
    memory = SimpleNamespace(retrieve=lambda key: None, get_ui_state=lambda: {
        'viewer': {'layout': 'grid', 'current_slices': {'axial': 12}},
        'overlays': {'ctv': True, 'dose_visible': True},
    })
    viewer = tool._get_ui_state(SimpleNamespace(memory=memory))['viewer']
    assert viewer['layout'] == 'grid'
    assert viewer['current_slices']['axial'] == 12
    assert viewer['overlays']['dose'] is True


def test_timeline_export_is_case_owned_and_reports_truncation(monitor):
    post, sid, _ = monitor
    post('training/start', {'monitor_run_id': 'export'})
    support._append_ui_event(sid, {'type': 'manual.dose'})
    exported = post.get('training/timeline')
    assert exported.status_code == 200
    assert 'attachment' in exported.headers['Content-Disposition']
    timeline = exported.get_json()
    assert timeline['session_id'] == sid
    assert timeline['event_counts'] == {'manual.dose': 1}
    assert timeline['retained_event_count'] == 1


def test_two_cases_never_share_training_events():
    first, second = 'case-' + uuid4().hex, 'case-' + uuid4().hex
    try:
        for sid in (first, second):
            support._ui_bucket(sid)['training'].update(active=True, run_id='same-id', started_at=time.time())
        support._append_ui_event(first, {'type': 'manual.seed.add'})
        assert len(support._ui_bucket(first)['training']['events']) == 1
        assert support._ui_bucket(second)['training']['events'] == []
    finally:
        support._drop_ui_bucket(first)
        support._drop_ui_bucket(second)


def test_stop_passes_empty_run_window_not_global_edits(monitor, monkeypatch):
    post, sid, _ = monitor
    support._append_ui_event(sid, {'type': 'manual.seed.add'})
    post('training/start', {'monitor_run_id': 'empty'})
    seen = []
    def advice(agent, session_id, *, fast=False, events=None):
        seen.append(events)
        return {}
    monkeypatch.setattr(routes, '_build_plan_advice', advice)
    result = post('training/stop', {'monitor_run_id': 'empty'}).get_json()
    assert seen == [[]]
    assert result['event_counts'] == {}


def test_delayed_eviction_save_cannot_overwrite_new_run(monitor):
    post, sid, writes = monitor
    post('training/start', {'monitor_run_id': 'new'})
    before = len(writes)
    routes._persist_closed_ui_bridge(sid, {'updated_at': 1, 'training': {'active': False}})
    assert len(writes) == before
    assert support._ui_bucket(sid)['training']['run_id'] == 'new'


@pytest.mark.parametrize('text', [
    'The Surgical Guide is persisted or being restored; wait for case resources to finish loading before judging whether it exists.',
    'The Surgical Guide status is temporarily unavailable because case resources could not be fully restored.',
    'The Surgical Guide generation failed; inspect the recorded error before retrying.',
    'Load CT, segment CTV/OAR, and run planning or manual AI dose recomputation to generate actionable advice.',
    'If the hot spot is clinically undesirable for this site, spread central seeds along the needle track or reduce local seed density.',
    '2 seed pair(s) violate the physical spacing rule (seed 4.5 mm x 0.8 mm; minimum surface clearance 0.5 mm). 1 pair(s) geometrically overlap.',
    'Dose preview updated: V100=91.0%, D90=120.0 Gy. Review hot spots and OAR dose before adding seeds.',
])
def test_zh_messages_are_localized(text):
    translated = support._localize_monitor_text(text, 'zh')
    assert translated != text
    assert any('\u4e00' <= c <= '\u9fff' for c in translated)
