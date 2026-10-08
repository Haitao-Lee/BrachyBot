"""Real checkpoint/restart contracts using synthetic conversations only."""
import copy
import json
from types import SimpleNamespace as NS

import pytest

from agent_runtime.context_accounting import sanitize_accounting
from agent_runtime.core import AgentMemory
from agent_runtime.llm_runtime import LLMRuntimeMixin
from web.workspace_store import WorkspaceStore


def agent(window=1_048_576, model='deepseek-v4'):
    obj = LLMRuntimeMixin()
    obj.config = {}
    obj.brain_router = NS(provider_meta={'test': {'model': model, 'max_context_tokens': window}},
                          default_provider='test')
    obj.memory = AgentMemory('synthetic-case')
    return obj


def record(obj, prompt=40_000, output=2_000):
    obj._enforce_context_budget([{'role': 'user', 'content': 'Synthetic question. ' * 100}])
    obj._record_context_usage({'prompt_tokens': prompt, 'completion_tokens': output})


def workspace(tmp_path, obj):
    store = WorkspaceStore(tmp_path / 'runtime')
    user = store.create_user('context-owner', 'synthetic-hash')
    case = store.create_session(user['id'], 'Synthetic accounting case')
    obj.memory.session_id = case.id
    store.snapshot_agent(user['id'], case.id, obj, reason='accounting.test')
    return store, user['id'], case.id


def test_measured_context_survives_real_disk_restart_and_metadata_hydration(tmp_path):
    first = agent()
    first._begin_context_turn()
    for index in range(16):
        first.memory.add_message('user' if index % 2 == 0 else 'assistant', f'Synthetic message {index}.')
    record(first)
    before = first.context_status()
    store, owner, case = workspace(tmp_path, first)
    reopened = WorkspaceStore(tmp_path / 'runtime')
    fresh = agent()
    reopened.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    restored = fresh.context_status()
    for key in ('used_tokens', 'window', 'source', 'measured', 'estimated', 'ratio',
                'observed_at_ms', 'revision', 'epoch', 'session_total_tokens',
                'turn_total_tokens', 'llm_calls', 'retained_history_tokens'):
        assert restored[key] == before[key], key
    assert restored['restored_snapshot']
    assert len(fresh.memory.conversation) == 16
    assert fresh._context_window_manager().calibration == first._context_window_manager().calibration


def test_new_request_can_be_smaller_without_any_history_loss():
    obj = agent()
    obj._begin_context_turn()
    for index in range(30):
        obj.memory.add_message('user', f'Synthetic history {index}.')
    record(obj, 40_000, 1_000)
    before = obj.context_status()
    obj._begin_context_turn()
    assert obj.context_status()['observed_at_ms'] == before['observed_at_ms']
    assert obj.context_status()['turn_total_tokens'] == 0
    record(obj, 30_000, 1_000)
    after = obj.context_status()
    assert after['used_tokens'] == 31_000 < before['used_tokens']
    assert after['change_reason'] == 'request_selection'
    assert after['session_total_tokens'] == 72_000
    assert len(obj.memory.conversation) == 30
    assert after['history_compactions'] == 0


def test_direct_read_turn_cannot_republish_previous_turn_consumption():
    obj = agent()
    obj._begin_context_turn()
    record(obj)
    obj._begin_context_turn()
    meta = obj._accounted_llm_meta({'usage': {'prompt_tokens': 99999}, 'llm_calls': 1})
    assert meta['llm_calls'] == 0
    assert meta['usage']['total_tokens'] == 0
    assert meta['context_status']['used_tokens'] == 42_000
    assert meta['context_status']['session_total_tokens'] == 42_000


def test_message_count_alone_no_longer_triggers_history_folding():
    obj = agent()
    obj._begin_context_turn()
    for index in range(200):
        obj.memory.add_message('user', f'Short synthetic question {index}.')
    assert obj.memory.needs_compaction()  # Old age-based heuristic would fold.
    assert not obj._maybe_compact_retained_context()
    assert len(obj.memory.conversation) == 200
    assert obj.memory.compaction_count == 0


def test_real_token_pressure_folds_and_announces_history():
    obj = agent(4096, 'synthetic-small-model')
    obj._begin_context_turn()
    for index in range(16):
        obj.memory.add_message('user', str(index) + 'Synthetic long text. ' * 200)
    assert obj._maybe_compact_retained_context()
    obj._enforce_context_budget([{'role': 'user', 'content': 'Small next prompt'}])
    status = obj.context_status()
    assert len(obj.memory.conversation) == 6
    assert status['compressed'] and not status['manual']
    assert status['folded_messages'] == 10
    assert status['history_compactions'] == 1


def test_missing_usage_is_a_persisted_lower_bound_not_zero_or_old_measurement(tmp_path):
    obj = agent()
    obj._begin_context_turn()
    record(obj, 20_000, 100)
    obj._begin_context_turn()
    obj._enforce_context_budget([{'role': 'user', 'content': 'A new estimated request'}])
    obj._record_context_usage({'completion_tokens': 200})
    status = obj.context_status()
    assert status['estimated'] and not status['measured']
    assert status['input_tokens'] is None
    assert status['session_total_tokens'] == 20_300
    assert not status['session_usage_complete']
    store, owner, case = workspace(tmp_path, obj)
    fresh = agent()
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    after = fresh.context_status()
    assert after['used_tokens'] == status['used_tokens']
    assert after['estimated'] and after.get('input_tokens') is None
    assert after['session_missing_usage_calls'] == 1


def test_actual_fallback_model_window_restores_without_default_route_relabeling(tmp_path):
    obj = agent()
    obj._begin_context_turn()
    obj._record_context_usage({'prompt_tokens': 20_000, 'completion_tokens': 200,
                               'context_window': 32_768, 'model': 'fallback-model', 'provider': 'fallback'})
    store, owner, case = workspace(tmp_path, obj)
    fresh = agent()
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    status = fresh.context_status()
    assert status['window'] == 32_768
    assert status['model'] == 'fallback-model'
    assert status['used_tokens'] == 20_200
    assert status['ratio'] == 20_200 / 32_768
    fresh._begin_context_turn()
    record(fresh, 30_000, 200)
    assert fresh.context_status()['window'] == 1_048_576
    assert fresh.context_status()['change_reason'] == 'model_route_changed'


def test_calibration_is_not_reused_for_different_configured_model(tmp_path):
    obj = agent()
    obj._begin_context_turn()
    record(obj)
    assert obj._context_window_manager().calibration != 1
    store, owner, case = workspace(tmp_path, obj)
    fresh = agent(131_072, 'different-model')
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    assert fresh._context_window_manager().calibration == 1
    # The historical request still belongs to its original window.
    assert fresh.context_status()['window'] == 1_048_576


def test_missing_route_identity_does_not_reuse_previous_fallback_model_window():
    obj = agent()
    obj._begin_context_turn()
    obj._record_context_usage({'prompt_tokens': 20_000, 'completion_tokens': 200,
                               'context_window': 32_768, 'model': 'fallback-model'})
    obj._begin_context_turn()
    obj._record_context_usage({})
    after = obj.context_status()
    assert after['window'] == 1_048_576
    assert after['estimated'] and not after['measured']
    assert after['model'] == 'deepseek-v4'


def test_background_array_hydration_never_rolls_back_live_accounting(tmp_path):
    first = agent()
    first._begin_context_turn()
    record(first, 20_000, 100)
    store, owner, case = workspace(tmp_path, first)
    live = agent()
    store.hydrate_agent(owner, case, live, include_planning_results=False, load_ct=False)
    live._begin_context_turn()
    record(live, 30_000, 200)
    live_state = copy.deepcopy(live.memory.context_accounting)
    live._workspace_hydration_in_progress = True
    store.hydrate_agent(owner, case, live, load_ct=False)
    assert live.memory.context_accounting == live_state
    assert live.context_status()['session_total_tokens'] == 50_300


def test_small_atomic_ledger_survives_restart_before_heavy_snapshot(tmp_path, monkeypatch):
    from web.server import _persist_agent_change

    obj = agent()
    obj._begin_context_turn()
    record(obj, 20_000, 100)
    store, owner, case = workspace(tmp_path, obj)
    obj._workspace_hydration_in_progress = True
    monkeypatch.setattr(store, 'schedule_agent_checkpoint', lambda *a, **k: pytest.fail('numeric ledger entered heavy checkpoint'))
    obj.memory.set_persistence_callback(lambda reason: _persist_agent_change(store, owner, case, obj, reason))
    obj._begin_context_turn()
    record(obj, 30_000, 200)
    # Old full snapshot has not changed; the bounded ledger is authoritative.
    assert store.load_snapshot(owner, case)['agent']['context_accounting']['session_total_tokens'] == 20_100
    reopened = WorkspaceStore(tmp_path / 'runtime')
    fresh = agent()
    reopened.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    assert fresh.context_status()['session_total_tokens'] == 50_300
    assert fresh.context_status()['used_tokens'] == 30_200


def test_late_numeric_write_cannot_rollback_revision_or_explicit_reset(tmp_path):
    from agent_runtime.context_accounting import new_accounting_epoch

    obj = agent()
    obj._begin_context_turn()
    record(obj, 20_000, 100)
    store, owner, case = workspace(tmp_path, obj)
    stale = copy.deepcopy(obj.memory.context_accounting)
    assert store.save_context_accounting(owner, case, stale)
    record(obj, 30_000, 200)
    assert store.save_context_accounting(owner, case, obj.memory.context_accounting)
    assert not store.save_context_accounting(owner, case, stale)
    reset = new_accounting_epoch()
    assert store.save_context_accounting(owner, case, reset)
    assert not store.save_context_accounting(owner, case, stale)
    assert store.load_context_accounting(owner, case)['epoch'] == reset['epoch']


def test_clear_commits_a_reset_tombstone_before_heavy_checkpoint(tmp_path, monkeypatch):
    from web.server import _persist_agent_change

    obj = agent()
    obj._begin_context_turn()
    obj.memory.add_message('user', 'Synthetic history that must stay cleared.')
    record(obj)
    store, owner, case = workspace(tmp_path, obj)
    monkeypatch.setattr(store, 'schedule_agent_checkpoint', lambda *a, **k: None)
    obj.memory.set_persistence_callback(lambda reason: _persist_agent_change(store, owner, case, obj, reason))
    obj.memory.clear_conversation()
    fresh = agent()
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    assert fresh.context_status()['session_total_tokens'] == 0
    assert not fresh.context_status()['measured']
    assert fresh.memory.conversation == []


def test_compact_ledger_cannot_read_or_write_another_owners_case(tmp_path):
    from web.workspace_store import WorkspaceNotFound

    obj = agent()
    obj._begin_context_turn()
    record(obj)
    store, owner, case = workspace(tmp_path, obj)
    other = store.create_user('other-context-owner', 'synthetic-hash')['id']
    with pytest.raises(WorkspaceNotFound):
        store.save_context_accounting(other, case, obj.memory.context_accounting)
    assert store.load_context_accounting(other, case) == {}


def test_manual_compression_keeps_consumption_and_persists_the_new_basis(tmp_path):
    obj = agent()
    obj._begin_context_turn()
    for index in range(16):
        obj.memory.add_message('user', f'Synthetic old {index}. ' * 20)
    record(obj)
    obj.compress_context_now()
    before = obj.context_status()
    store, owner, case = workspace(tmp_path, obj)
    fresh = agent()
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    after = fresh.context_status()
    assert after['source'] == 'retained_history_estimate'
    assert after['manual'] and after['compressed']
    assert after['session_total_tokens'] == 42_000
    assert after['used_tokens'] == before['used_tokens']


def test_clear_history_invalidates_previous_request_epoch():
    obj = agent()
    obj._begin_context_turn()
    record(obj)
    before = obj.context_status()
    obj.memory.clear_conversation()
    after = obj.context_status()
    assert after['epoch'] != before['epoch']
    assert after['source'] == 'retained_history_estimate'
    assert after['used_tokens'] == 0
    assert after['session_total_tokens'] == 0
    assert after['updated_at_ms'] >= before['updated_at_ms']
    assert after['revision'] > 0


def test_visual_child_counts_in_parent_turn_and_session_once():
    obj = agent()
    obj._active_turn_context = {'request_id': 'human-request'}
    obj._begin_context_turn()
    record(obj, 20_000, 100)
    obj._active_turn_context = {'request_id': 'child', 'parent_request_id': 'human-request',
                                'internal_followup': True}
    obj._begin_context_turn()
    record(obj, 30_000, 200)
    assert obj.context_status()['turn_total_tokens'] == 50_300
    assert obj.context_status()['session_total_tokens'] == 50_300
    obj._active_turn_context = {'request_id': 'next-human'}
    obj._begin_context_turn()
    assert obj.context_status()['turn_total_tokens'] == 0
    assert obj.context_status()['session_total_tokens'] == 50_300


def test_unrelated_visual_parent_cannot_merge_other_turn_usage():
    obj = agent()
    obj._active_turn_context = {'request_id': 'other-human'}
    obj._begin_context_turn()
    record(obj, 20_000, 100)
    obj._active_turn_context = {'request_id': 'child', 'parent_request_id': 'old-human',
                                'internal_followup': True}
    obj._begin_context_turn()
    record(obj, 30_000, 200)
    assert obj.context_status()['turn_total_tokens'] == 30_200
    assert obj.context_status()['session_total_tokens'] == 50_300


def test_idle_status_reuses_estimate_and_does_not_schedule_writes(monkeypatch):
    obj = agent()
    obj._begin_context_turn()
    obj.memory.add_message('user', 'Synthetic history. ' * 1000)
    record(obj)
    calls = []
    obj.memory.set_persistence_callback(calls.append)
    obj.context_status()
    monkeypatch.setattr('agent_runtime.llm_runtime.estimate_messages', lambda *a, **k: pytest.fail('unexpected repeated history tokenization'))
    record_status = obj.context_status()
    assert record_status['retained_history_tokens'] > 0
    assert calls == []


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -1, True, 'wrong', 1.5])
def test_disk_boundary_rejects_invalid_counts_and_arbitrary_content(bad):
    obj = agent()
    obj._begin_context_turn()
    record(obj)
    state = copy.deepcopy(obj.memory.context_accounting)
    state.update(prompt='private text', api_key='private-key', session_total_tokens=bad)
    state['snapshot'].update(messages=['private'], used_tokens=bad)
    cleaned = sanitize_accounting(state)
    assert cleaned['session_total_tokens'] == 0
    assert 'snapshot' not in cleaned
    assert cleaned['session_missing_usage_calls'] > 0
    assert 'private' not in json.dumps(cleaned)


def test_legacy_session_is_explicitly_estimated_without_fabricating_old_usage(tmp_path):
    old = agent()
    old.memory.add_message('user', 'Legacy synthetic question.')
    store, owner, case = workspace(tmp_path, old)
    fresh = agent()
    store.hydrate_agent(owner, case, fresh, include_planning_results=False, load_ct=False)
    status = fresh.context_status()
    assert status['source'] == 'retained_history_estimate'
    assert status['estimated']
    assert status['session_total_tokens'] == 0
    assert status['preexisting_history']


def test_concurrent_polling_never_observes_half_recorded_totals():
    from concurrent.futures import ThreadPoolExecutor
    import threading

    obj = agent()
    obj._begin_context_turn()
    done = threading.Event()

    def writer():
        try:
            for _ in range(100):
                obj._record_context_usage({'prompt_tokens': 1000, 'completion_tokens': 100})
        finally:
            done.set()

    def reader():
        while not done.is_set():
            status = obj.context_status()
            assert status['turn_total_tokens'] == status['turn_input_tokens'] + status['turn_output_tokens']
            assert status['session_total_tokens'] == status['session_input_tokens'] + status['session_output_tokens']
            assert status['turn_total_tokens'] == status['llm_calls'] * 1100
            assert status['session_total_tokens'] == status['session_calls'] * 1100

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reader), pool.submit(writer)]
        for future in futures:
            future.result(timeout=15)
    assert obj.context_status()['session_total_tokens'] == 110_000


@pytest.mark.parametrize('cancelled', [False, True])
def test_real_visual_child_boundary_checkpoints_numeric_usage_after_restoring_parent(cancelled):
    from agent_runtime.chat_workflows import ChatWorkflowMixin

    class Child(ChatWorkflowMixin, LLMRuntimeMixin):
        def _current_turn_token(self):
            return 1

        def _is_turn_cancelled(self, token):
            return False

        def _chat_with_stream_impl(self, message):
            self._begin_context_turn()
            self.memory.add_message('user', 'Hidden synthetic image prompt')
            self._record_context_usage({'prompt_tokens': 30_000, 'completion_tokens': 200})
            if cancelled:
                raise RuntimeError('Synthetic cancellation')
            yield 'synthetic SSE'

    obj = Child()
    obj.memory = AgentMemory('synthetic-case')
    obj.config = {}
    obj._active_turn_context = {'request_id': 'parent'}
    obj._begin_context_turn()
    obj.memory.add_message('user', 'Real synthetic user question')
    record(obj, 20_000, 100)
    parent = copy.deepcopy(obj.memory.conversation)
    notifications = []
    obj.memory.set_persistence_callback(lambda reason: notifications.append((reason, copy.deepcopy(obj.memory.conversation))))
    obj._active_turn_context = {'internal_followup': True, 'request_id': 'child', 'parent_request_id': 'parent'}
    if cancelled:
        with pytest.raises(RuntimeError, match='Synthetic cancellation'):
            list(obj.chat_with_stream('hidden analysis'))
    else:
        assert list(obj.chat_with_stream('hidden analysis')) == ['synthetic SSE']
    assert obj.memory.conversation == parent
    assert obj.context_status()['turn_total_tokens'] == 50_300
    assert obj.context_status()['session_total_tokens'] == 50_300
    assert notifications == [('context.accounting:visual_child_finished', parent)]
