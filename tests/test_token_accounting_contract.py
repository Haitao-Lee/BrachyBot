"""Synthetic accounting controls: no paid provider or clinical case access."""
from types import SimpleNamespace as NS
import threading
import time

import pytest

from brain.core.usage import normalize_usage, anthropic_usage, merge_usage_snapshot
from agent_runtime.context_window import ContextWindowManager, estimate_messages
from agent_runtime.llm_runtime import LLMRuntimeMixin


def runtime():
    agent = LLMRuntimeMixin()
    manager = ContextWindowManager(window=1_048_576)
    agent._context_window_manager = lambda: manager
    agent.memory = NS(conversation=[], context_summary='', retrieve=lambda *args: None)
    agent._begin_context_turn()
    return agent, manager


def test_total_is_input_plus_output_not_a_conflicting_provider_total():
    row = normalize_usage({'prompt_tokens': 116_020, 'completion_tokens': 2_626, 'total_tokens': 999})
    assert row['total_tokens'] == 118_646
    assert row['usage_complete']


@pytest.mark.parametrize('bad', [None, True, -1, float('nan'), float('inf'), 'wrong', 1.5])
def test_invalid_counts_are_unavailable_not_measured_zero(bad):
    row = normalize_usage({'prompt_tokens': bad, 'completion_tokens': 0})
    assert not row['input_reported'] and not row['usage_complete']
    assert not normalize_usage(row)['input_reported']


def test_anthropic_stream_merges_start_and_output_snapshots_once():
    first = anthropic_usage(NS(input_tokens=100, output_tokens=0,
                              cache_creation_input_tokens=200, cache_read_input_tokens=700))
    final = merge_usage_snapshot(first, anthropic_usage(NS(output_tokens=30)))
    final = merge_usage_snapshot(final, anthropic_usage(NS(output_tokens=40)))
    assert final['prompt_tokens'] == 1000
    assert final['completion_tokens'] == 40
    assert final['total_tokens'] == 1040


def test_real_anthropic_stream_path_keeps_start_input(monkeypatch):
    from brain.providers.anthropic_llm import AnthropicLLM
    provider = AnthropicLLM(api_key='synthetic-test-value')
    events = [NS(type='message_start', message=NS(usage=NS(
        input_tokens=100, output_tokens=0, cache_read_input_tokens=900))),
        NS(type='content_block_delta', delta=NS(type='text_delta', text='hello')),
        NS(type='message_delta', delta=NS(stop_reason='end_turn'), usage=NS(output_tokens=50))]
    monkeypatch.setattr(provider, '_get_client', lambda _: NS(messages=NS(create=lambda **kwargs: iter(events))))
    chunks = list(provider.chat_messages_stream([{'role': 'user', 'content': 'hello'}]))
    assert chunks[-1]['type'] == 'final'
    assert chunks[-1]['usage']['total_tokens'] == 1050
    assert chunks[-1]['usage']['prompt_tokens'] == 1000


def test_latest_context_and_turn_sum_are_different_quantities():
    agent, _ = runtime()
    agent._record_context_usage({'prompt_tokens': 31_139, 'completion_tokens': 1000})
    agent._record_context_usage({'prompt_tokens': 40_000, 'completion_tokens': 800})
    agent._record_context_usage({'prompt_tokens': 44_881, 'completion_tokens': 826})
    status = agent.context_status()
    assert status['used_tokens'] == 45_707
    assert status['turn_total_tokens'] == 118_646
    assert status['turn_input_tokens'] == 116_020
    assert status['turn_output_tokens'] == 2_626
    assert status['ratio'] == 45_707 / 1_048_576
    meta = agent._accounted_llm_meta({'usage': {'total_tokens': 1}})
    assert meta['usage']['total_tokens'] == 118_646
    assert meta['context_status'] == status


def test_missing_usage_replaces_old_measurement_with_current_estimate():
    agent, manager = runtime()
    agent._record_context_usage({'prompt_tokens': 5000, 'completion_tokens': 100})
    messages = [{'role': 'user', 'content': 'second request'}]
    agent._enforce_context_budget(messages)
    agent._record_context_usage({})
    status = agent.context_status()
    assert status['estimated'] and not status['measured']
    assert status['used_tokens'] != 5100 and status['used_tokens'] > 0
    assert status['missing_usage_calls'] == 1
    assert agent._accounted_llm_meta({})['usage']['usage_complete'] is False


def test_actual_fallback_provider_window_not_default_provider_window():
    agent, _ = runtime()
    agent._record_context_usage({'prompt_tokens': 25_000, 'completion_tokens': 200,
        'provider': 'fallback', 'model': 'custom-small-model', 'context_window': 32_768})
    status = agent.context_status()
    assert status['provider'] == 'fallback' and status['model'] == 'custom-small-model'
    assert status['window'] == 32_768
    assert status['ratio'] == 25_200 / 32_768
    assert status['target_tokens'] < status['window']


def test_fallback_without_usage_does_not_keep_prior_window_or_input():
    agent, _ = runtime()
    agent._record_context_usage({'prompt_tokens': 5000, 'completion_tokens': 100})
    agent._enforce_context_budget([{'role': 'user', 'content': 'fallback prompt'}])
    agent._record_context_usage({'provider': 'fallback', 'model': 'custom-small-model',
                                'context_window': 4096})
    status = agent.context_status()
    assert status['estimated'] and not status['measured']
    assert status['input_tokens'] is None and not status['input_reported']
    assert status['window'] == 4096 and status['provider'] == 'fallback'
    assert status['target_tokens'] < 4096
    assert status['reserve_output_tokens'] < 4096


def test_router_tags_actual_provider_in_sync_and_stream():
    from brain.core.router import LLMRouter
    from brain.core.base import LLMResponse
    router = LLMRouter({})
    row = {'prompt_tokens': 100, 'completion_tokens': 20}
    router.providers = {'synthetic': NS(
        model='synthetic-model',
        chat_messages=lambda **kwargs: LLMResponse(content='ok', usage=row, model='synthetic-model'),
        chat_messages_stream=lambda **kwargs: iter([{'type': 'final', 'usage': row}]),
    )}
    router.default_provider = 'synthetic'
    router.provider_meta = {'synthetic': {'model': 'synthetic-model', 'max_context_tokens': 4096}}
    sync = router.chat_messages([{'role': 'user', 'content': 'ok'}]).usage
    stream = list(router.chat_messages_stream([{'role': 'user', 'content': 'ok'}]))[-1]['usage']
    for usage in (sync, stream):
        assert usage['provider'] == 'synthetic'
        assert usage['context_window'] == 4096 and usage['total_tokens'] == 120


def test_context_estimator_calibration_converges_without_feedback_bias():
    agent, manager = runtime()
    messages = [{'role': 'user', 'content': 'x' * 10_000}]
    raw = estimate_messages(messages)
    for _ in range(30):
        agent._enforce_context_budget(messages)
        agent._record_context_usage({'prompt_tokens': raw * 2, 'completion_tokens': 0})
    assert 1.98 < manager.calibration <= 2.01


def test_small_configured_windows_are_not_silently_replaced_by_8192():
    manager = ContextWindowManager(window=4096)
    assert manager.window == 4096
    assert 0 < manager.target_tokens < 4096
    assert manager.snapshot(iter([{'role': 'user', 'content': 'ok'}]))['message_count'] == 1


def test_compression_does_not_reset_completed_turn_usage():
    from agent_runtime.core import AgentMemory
    agent, _ = runtime()
    agent.memory = AgentMemory('synthetic-token-compress')
    for index in range(12):
        agent.memory.add_message('user', 'saved text ' * 100 + str(index))
    agent._record_context_usage({'prompt_tokens': 5000, 'completion_tokens': 200})
    agent.compress_context_now()
    status = agent.context_status()
    assert status['turn_total_tokens'] == 5200
    assert status['estimated'] and not status['measured']
    assert status['manual'] is True


def test_case_control_operation_blocks_running_and_unwinding_workers():
    from web.chat_tasks import ChatTaskManager, ChatTaskError
    manager = ChatTaskManager()
    done = threading.Event()
    task = NS(user_id='user', session_id='case', status='running',
              created_at=time.time(), finished_at=None, _worker_done=done)
    manager._tasks['test'] = task
    called = []
    for state in ('running', 'cancelled'):
        task.status = state
        with pytest.raises(ChatTaskError, match='finish'):
            manager.run_idle_operation('user', 'case', lambda: called.append(True))
    assert not called
    done.set()
    manager.run_idle_operation('user', 'case', lambda: called.append(True))
    assert called == [True]


def test_real_compression_endpoint_requires_confirmation_and_idle_case(monkeypatch):
    from flask import Flask
    from web.routes import planning_routes as routes
    agent, _ = runtime()
    mutations, checkpoints = [], []
    agent.compress_context_now = lambda **kwargs: mutations.append(kwargs) or {'manual': True}
    store = NS(get_session=lambda user, case: NS(id=case),
               flush_agent_checkpoint=lambda *args, **kwargs: checkpoints.append(kwargs))
    monkeypatch.setattr(routes, 'require_api_key', lambda f: f)
    monkeypatch.setattr(routes, 'rate_limit', lambda f: f)
    monkeypatch.setattr(routes, 'current_user', lambda store: {'id': 'synthetic-user'})
    app = Flask('context-contract')
    app.secret_key = 'synthetic-session-value'
    app.extensions['brachybot_workspace_store'] = store
    routes.register_planning_routes(app, lambda *args: agent, get_cached_agent=lambda *args: agent)
    client = app.test_client()
    headers = {'X-BrachyBot-Session': 'synthetic-case'}
    for body in ({}, {'confirmed': False}, {'confirmed': 'true'}):
        response = client.post('/api/chat/context/compress', json=body, headers=headers)
        assert response.status_code == 400
    assert not mutations
    manager = app.extensions['brachybot_chat_tasks']
    done = threading.Event()
    task = NS(user_id='synthetic-user', session_id='synthetic-case', status='running',
              created_at=time.time(), finished_at=None, _worker_done=done)
    manager._tasks['synthetic-task'] = task
    assert client.post('/api/chat/context/compress', json={'confirmed': True}, headers=headers).status_code == 409
    assert not mutations
    task.status = 'completed'
    done.set()
    response = client.post('/api/chat/context/compress', json={'confirmed': True}, headers=headers)
    assert response.status_code == 200 and response.get_json()['persisted']
    assert len(mutations) == len(checkpoints) == 1
    assert response.get_json()['session_id'] == 'synthetic-case'
