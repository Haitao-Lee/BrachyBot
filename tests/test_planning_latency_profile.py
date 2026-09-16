from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from plans.performance import collect_planning_latency, timed, _profile


def test_profile_preserves_result_and_cleans_up_after_failure():
    result = SimpleNamespace(success=True, metadata={'existing': 42})

    @timed('work')
    def work():
        return result

    @collect_planning_latency
    def request():
        return work()

    assert request() is result
    assert result.metadata['existing'] == 42
    assert result.metadata['latency_profile']['nested_timings']['work']['calls'] == 1
    assert _profile.get() is None

    @collect_planning_latency
    def failure():
        raise ValueError('original error')

    with pytest.raises(ValueError, match='original error'):
        failure()
    assert _profile.get() is None


def test_concurrent_requests_do_not_share_profile():
    barrier = Barrier(2)

    @timed('work')
    def work():
        return None

    @collect_planning_latency
    def request(count):
        barrier.wait(timeout=5)
        for _ in range(count):
            work()
        return SimpleNamespace(metadata={})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, [2, 5]))
    assert [r.metadata['latency_profile']['nested_timings']['work']['calls'] for r in results] == [2, 5]
    assert _profile.get() is None


def test_nested_request_restores_outer_profile():
    @timed('inner_work')
    def work():
        return SimpleNamespace(metadata={})

    @collect_planning_latency
    def inner():
        return work()

    @collect_planning_latency
    def outer():
        inner_result = inner()
        assert inner_result.metadata['latency_profile']['nested_timings']['inner_work']['calls'] == 1
        return SimpleNamespace(metadata={})

    assert outer().metadata['latency_profile']['nested_timings'] == {}
    assert _profile.get() is None
