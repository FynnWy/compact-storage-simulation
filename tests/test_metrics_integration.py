from types import SimpleNamespace

from simulation.event_handler import EventHandler
from simulation.metrics import Metrics


def _request(request_id, arrival_time, latest_time):
    return SimpleNamespace(
        request_id=request_id,
        arrival_time=arrival_time,
        earliest_time=arrival_time,
        latest_time=latest_time,
    )


def test_throughput_counts_full_completions_not_only_on_time():
    metrics = Metrics()
    state = SimpleNamespace(t=0)
    action = {"type": "remove_target", "bin_id": 1}

    on_time_request = _request(request_id=1, arrival_time=0, latest_time=10)
    late_request = _request(request_id=2, arrival_time=0, latest_time=5)

    state.t = 8
    metrics.record_target_bin_at_pickstation(state, action, on_time_request)

    state.t = 12
    metrics.record_target_bin_at_pickstation(state, action, late_request)

    metrics.record_full_completion(18, on_time_request)
    metrics.record_full_completion(22, late_request)

    assert metrics.throughput() == 2
    assert metrics.throughput_on_time() == 1

    summary = metrics.summary()
    assert summary["throughput"] == 2
    assert summary["throughput_on_time"] == 1
    assert summary["requests_completed"] == 2


def test_resolve_digging_depth_uses_temp_storage_fallback():
    task = SimpleNamespace(initial_blocker_count=None, temp_storage=[{"bin_id": 1}, {"bin_id": 2}])
    depth = EventHandler._resolve_digging_depth_for_task(None, task)
    assert depth == 2


def test_resolve_digging_depth_prefers_initial_blocker_count():
    task = SimpleNamespace(initial_blocker_count=4, temp_storage=[{"bin_id": 1}])
    depth = EventHandler._resolve_digging_depth_for_task(None, task)
    assert depth == 4