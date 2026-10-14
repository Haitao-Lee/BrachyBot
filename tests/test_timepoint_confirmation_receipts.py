"""Server-owned target receipts are exact, read-set fenced and retry-safe."""
from types import SimpleNamespace
from uuid import uuid4
import threading

import pytest

from agent_runtime.timepoint_targets import PendingTimepointCall, confirm_pending_timepoint_call
from web.timepoint_chat import capture_chat_scope
from web.timepoints import TimepointConflict
from web.workspace_store import WorkspaceStore


def test_receipt_cannot_be_consumed_by_foreign_owner_or_rebound_to_another_request(tmp_path, monkeypatch):
    monkeypatch.setenv('BRACHYBOT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    store = WorkspaceStore(tmp_path / 'runtime')
    uid = store.create_user('receipt-owner', 'test-only-hash')['id']
    sid = store.create_session(uid, 'Synthetic case').id
    store.migrate_default_timepoint(uid, sid)
    tid = store.create_timepoint(uid, sid, 'Different scan', expected_revision=store.list_timepoints(uid, sid)['catalog_revision'])['created_timepoint_id']
    scope = capture_chat_scope(store, uid, sid)
    context = store.capture_timepoint_context(uid, sid, tid)
    params = {'timepoint_id': tid, 'metric_type': 'dose_metrics'}
    pending = PendingTimepointCall.create(scope, 'query_metrics', params, context)
    root = SimpleNamespace(_workspace_store=store, _pending_timepoint_calls={pending.receipt_id: pending}, _turn_state_lock=threading.RLock())
    req = uuid4().hex
    with pytest.raises(TimepointConflict):
        confirm_pending_timepoint_call(root, pending.receipt_id, owner_id='foreign-owner', session_id=sid, request_id=req)
    assert pending.receipt_id in root._pending_timepoint_calls
    receipt = confirm_pending_timepoint_call(root, pending.receipt_id, owner_id=uid, session_id=sid, request_id=req)
    assert receipt.permits(scope, 'query_metrics', params, store, req)
    assert not receipt.permits(scope, 'query_metrics', {**params, 'metric_type': 'oar_metrics'}, store, req)
    assert confirm_pending_timepoint_call(root, pending.receipt_id, owner_id=uid, session_id=sid, request_id=req) is receipt
    with pytest.raises(TimepointConflict):
        confirm_pending_timepoint_call(root, pending.receipt_id, owner_id=uid, session_id=sid, request_id=uuid4().hex)
    store.save_timepoint_results(uid, sid, tid, {'changed_source': True}, expected_clinical_revision=context.target.clinical_revision)
    with pytest.raises(TimepointConflict):
        receipt.permits(scope, 'query_metrics', params, store, req)
