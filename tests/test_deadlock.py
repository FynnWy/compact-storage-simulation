# tests/test_deadlock.py
"""
Unit-Tests für Deadlock Detection und Resolution.

Testet:
- Zyklus-Erkennung im Wait-For-Graph
- Verschiedene Zyklusgrößen (2, 3, n Roboter)
- Deadlock-Auflösung
"""
import pytest
from traffic.deadlock_detector import DeadlockDetector, DeadlockResolver


class TestDeadlockDetectorCycles:
    """Zykluserkennung im Wait-For-Graph."""

    def test_simple_two_robot_cycle(self, deadlock_detector):
        """2-Roboter-Zyklus: 0 → 1 → 0"""
        dd = deadlock_detector

        dd.register_wait(waiting_robot_id=0, blocking_robot_id=1, reason="test")
        dd.register_wait(waiting_robot_id=1, blocking_robot_id=0, reason="test")

        cycle = dd.detect_cycle()

        assert cycle is not None
        assert set(cycle) == {0, 1}

    def test_three_robot_cycle(self, deadlock_detector):
        """3-Roboter-Zyklus: 0 → 1 → 2 → 0"""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(1, 2, "test")
        dd.register_wait(2, 0, "test")

        cycle = dd.detect_cycle()

        assert cycle is not None
        assert len(cycle) == 3
        assert set(cycle) == {0, 1, 2}

    def test_four_robot_cycle(self, deadlock_detector):
        """4-Roboter-Zyklus."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(1, 2, "test")
        dd.register_wait(2, 3, "test")
        dd.register_wait(3, 0, "test")

        cycle = dd.detect_cycle()

        assert cycle is not None
        assert len(cycle) == 4


class TestDeadlockDetectorNoCycle:
    """Fälle ohne Zyklus."""

    def test_no_cycle_chain(self, deadlock_detector):
        """Kette ohne Zyklus: 0 → 1 → 2 (Roboter 2 wartet auf niemanden)."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(1, 2, "test")
        # Roboter 2 wartet auf niemanden

        cycle = dd.detect_cycle()

        assert cycle is None

    def test_no_cycle_empty_graph(self, deadlock_detector):
        """Leerer Graph = kein Zyklus."""
        dd = deadlock_detector

        cycle = dd.detect_cycle()

        assert cycle is None

    def test_no_cycle_single_wait(self, deadlock_detector):
        """Einzelne Wartebeziehung = kein Zyklus."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")

        cycle = dd.detect_cycle()

        assert cycle is None

    def test_no_cycle_parallel_chains(self, deadlock_detector):
        """Parallele Ketten ohne Zyklus."""
        dd = deadlock_detector

        # Kette 1: 0 → 1
        dd.register_wait(0, 1, "test")
        # Kette 2: 2 → 3
        dd.register_wait(2, 3, "test")

        cycle = dd.detect_cycle()

        assert cycle is None


class TestDeadlockDetectorClearWait:
    """clear_wait bricht Zyklen."""

    def test_clear_wait_breaks_cycle(self, deadlock_detector):
        """Nach clear_wait darf kein Zyklus mehr erkannt werden."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(1, 0, "test")

        # Zyklus vorhanden
        assert dd.detect_cycle() is not None

        dd.clear_wait(0)  # Roboter 0 wartet nicht mehr

        # Kein Zyklus mehr
        assert dd.detect_cycle() is None

    def test_clear_all(self, deadlock_detector):
        """clear_all löscht alle Wartebeziehungen."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(1, 2, "test")
        dd.register_wait(2, 0, "test")

        dd.clear_all()

        assert dd.detect_cycle() is None
        assert dd.get_waiting_robots() == []


class TestDeadlockDetectorHelpers:
    """Hilfsfunktionen."""

    def test_is_waiting(self, deadlock_detector):
        """is_waiting gibt korrekten Status zurück."""
        dd = deadlock_detector

        assert dd.is_waiting(0) is False

        dd.register_wait(0, 1, "test")

        assert dd.is_waiting(0) is True
        assert dd.is_waiting(1) is False

    def test_get_waiting_robots(self, deadlock_detector):
        """get_waiting_robots listet alle wartenden Roboter."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test")
        dd.register_wait(2, 3, "test")

        waiting = dd.get_waiting_robots()

        assert set(waiting) == {0, 2}

    def test_get_wait_time(self, deadlock_detector):
        """get_wait_time berechnet Wartezeit korrekt."""
        dd = deadlock_detector

        dd.register_wait(0, 1, "test", current_time=10)

        assert dd.get_wait_time(0, current_time=15) == 5
        assert dd.get_wait_time(0, current_time=10) == 0
        assert dd.get_wait_time(1, current_time=15) == 0  # Wartet nicht


class TestDeadlockResolver:
    """Deadlock-Auflösung."""

    def test_resolve_lowest_priority_fallback(self):
        """Ohne Scheduler: höchste robot_id wird Victim."""
        resolver = DeadlockResolver(strategy="lowest_priority")

        cycle = [0, 1, 2]
        victim = resolver.resolve(
            cycle=cycle,
            robots=[],  # Leere Liste
            scheduler=None,
            current_time=0,
        )

        assert victim == 2  # Höchste ID

    def test_resolve_random(self):
        """random-Strategie wählt einen aus dem Zyklus."""
        resolver = DeadlockResolver(strategy="random")

        cycle = [0, 1, 2]
        victim = resolver.resolve(
            cycle=cycle,
            robots=[],
            scheduler=None,
            current_time=0,
        )

        assert victim in cycle

    def test_resolve_empty_cycle(self):
        """Leerer Zyklus = None."""
        resolver = DeadlockResolver(strategy="lowest_priority")

        victim = resolver.resolve(
            cycle=[],
            robots=[],
            scheduler=None,
            current_time=0,
        )

        assert victim is None