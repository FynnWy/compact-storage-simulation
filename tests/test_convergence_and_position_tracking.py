# tests/test_convergence_and_position_tracking.py
"""
Unit-Tests für ConvergenceDetector und PositionChangeTracker.
"""
import pytest

from metrics.convergence_detector import ConvergenceDetector, PositionChangeTracker


# ---------------------------------------------------------------------------
# ConvergenceDetector
# ---------------------------------------------------------------------------

class TestConvergenceDetectorBasic:
    def test_empty_history(self):
        cd = ConvergenceDetector(window_size=3, threshold=0.01)

        assert cd.is_converged() is False
        assert cd.get_convergence_time() is None

        metrics = cd.get_stability_metrics()
        assert metrics["variance_over_time"] == []
        assert metrics["rolling_mean_digging_depth"] == []
        assert metrics["convergence_point"] is None

    def test_converges_for_stable_values(self):
        """
        Bei fast konstanten Werten sollte nach window_size Snapshots
        eine Konvergenz erkannt werden.
        """
        cd = ConvergenceDetector(window_size=3, threshold=0.001)

        snapshots = [
            {"time": 1, "average_digging_depth": 1.0, "hot_bins_top_ratio": 0.5},
            {"time": 2, "average_digging_depth": 1.001, "hot_bins_top_ratio": 0.499},
            {"time": 3, "average_digging_depth": 0.999, "hot_bins_top_ratio": 0.501},
        ]

        for s in snapshots:
            cd.add_snapshot(s)

        assert cd.is_converged() is True
        # Konvergenzzeitpunkt = time des letzten fenster-Snapshots
        assert cd.get_convergence_time() == 3

    def test_does_not_converge_for_high_variance(self):
        cd = ConvergenceDetector(window_size=3, threshold=0.01)

        snapshots = [
            {"time": 1, "average_digging_depth": 1.0, "hot_bins_top_ratio": 0.2},
            {"time": 2, "average_digging_depth": 3.0, "hot_bins_top_ratio": 0.8},
            {"time": 3, "average_digging_depth": 0.5, "hot_bins_top_ratio": 0.1},
        ]

        for s in snapshots:
            cd.add_snapshot(s)

        assert cd.is_converged() is False
        assert cd.get_convergence_time() is None

    def test_stability_metrics_after_convergence(self):
        cd = ConvergenceDetector(window_size=2, threshold=0.1)

        # Erst schwankend (keine Konvergenz)
        cd.add_snapshot({"time": 1, "average_digging_depth": 1.0, "hot_bins_top_ratio": 0.1})
        cd.add_snapshot({"time": 2, "average_digging_depth": 3.0, "hot_bins_top_ratio": 0.9})
        assert cd.is_converged() is False

        # Dann stabil
        cd.add_snapshot({"time": 3, "average_digging_depth": 2.0, "hot_bins_top_ratio": 0.5})
        cd.add_snapshot({"time": 4, "average_digging_depth": 2.01, "hot_bins_top_ratio": 0.49})

        assert cd.is_converged() is True
        conv_time = cd.get_convergence_time()
        assert conv_time in {3, 4}  # je nach Schwellen-Feinheit

        metrics = cd.get_stability_metrics()
        assert "post_convergence_stability" in metrics
        post = metrics["post_convergence_stability"]
        # Varianzen nach Konvergenz sollten klein, aber >= 0 sein
        assert post["average_digging_depth"] >= 0.0
        assert post["hot_bins_top_ratio"] >= 0.0


# ---------------------------------------------------------------------------
# PositionChangeTracker
# ---------------------------------------------------------------------------

class DummyBinForTracker:
    def __init__(self, bin_id, stack, level):
        self.bin_id = bin_id
        self._stack = stack
        self._level = level

    def get_stack(self):
        return self._stack

    def get_level(self):
        return self._level


class DummyStateForTracker:
    def __init__(self, bins):
        self.bins = list(bins)


class TestPositionChangeTracker:
    def test_no_changes_on_first_record(self):
        tracker = PositionChangeTracker()

        state = DummyStateForTracker([
            DummyBinForTracker(0, stack=(0, 0), level=0),
            DummyBinForTracker(1, stack=(1, 0), level=1),
        ])

        tracker.record_state(state, time=0)

        # Erste Aufnahme erzeugt noch keinen Eintrag
        assert tracker.get_timeseries() == []

    def test_stack_and_level_changes_tracked(self):
        tracker = PositionChangeTracker()

        # t=0
        state0 = DummyStateForTracker([
            DummyBinForTracker(0, stack=(0, 0), level=0),
            DummyBinForTracker(1, stack=(1, 0), level=1),
        ])
        tracker.record_state(state0, time=0)

        # t=1: Bin 0 bleibt im gleichen Stack, aber Level ändert sich,
        #       Bin 1 wechselt den Stack.
        state1 = DummyStateForTracker([
            DummyBinForTracker(0, stack=(0, 0), level=1),   # nur Level geändert
            DummyBinForTracker(1, stack=(2, 0), level=0),   # Stack geändert
        ])
        tracker.record_state(state1, time=1)

        timeseries = tracker.get_timeseries()
        assert len(timeseries) == 1

        entry = timeseries[0]
        assert entry["time"] == 1
        assert entry["total_moves"] == 2
        assert entry["bins_changed_stack"] == 1
        assert entry["bins_changed_level"] == 1

    def test_missing_bin_in_next_state_counts_as_move(self):
        """
        Wenn eine Bin im nächsten Snapshot fehlt (z.B. gelöscht),
        sollte das als Stack-Änderung gezählt werden (fallback: None).
        """
        tracker = PositionChangeTracker()

        state0 = DummyStateForTracker([
            DummyBinForTracker(0, stack=(0, 0), level=0),
        ])
        tracker.record_state(state0, time=0)

        # Bin 0 fehlt jetzt komplett
        state1 = DummyStateForTracker([])
        tracker.record_state(state1, time=1)

        timeseries = tracker.get_timeseries()
        assert len(timeseries) == 1
        entry = timeseries[0]
        assert entry["total_moves"] == 1
        assert entry["bins_changed_stack"] == 1
        assert entry["bins_changed_level"] == 0