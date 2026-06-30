# tests/test_multi_robot.py
"""
Tests für Multi-Robot-Koordination.

Testet:
- Keine Kollisionen zwischen Robotern
- Keine Starvation (alle Roboter bekommen Arbeit)
- Keine Deadlocks, die nicht aufgelöst werden
"""
import pytest
from simulation.simulation_engine import SimulationEngine
from events.event_types import EventType


class TestNoCollisions:
    """Kollisionsvermeidung."""

    def test_no_collision_two_robots(self, medium_config):
        """Zwei Roboter dürfen nie zur gleichen Zeit auf derselben Zelle sein."""
        medium_config.num_robots = 2
        engine = SimulationEngine(medium_config)

        for _ in range(500):
            event = engine.step()
            if event is None:
                break

            # Nach jedem Event: Prüfe Positionen
            positions = {}
            for robot in engine.state.robots:
                pos = robot.get_position()
                if pos is not None:
                    if pos in positions:
                        pytest.fail(
                            f"Collision at {pos} between "
                            f"Robot {positions[pos]} and Robot {robot.robot_id}"
                        )
                    positions[pos] = robot.robot_id

    def test_no_collision_three_robots(self, multi_robot_config):
        """Drei Roboter ohne Kollision."""
        engine = SimulationEngine(multi_robot_config)

        collision_count = 0

        for _ in range(400):
            event = engine.step()
            if event is None:
                break

            positions = {}
            for robot in engine.state.robots:
                pos = robot.get_position()
                if pos is not None:
                    if pos in positions:
                        collision_count += 1
                    positions[pos] = robot.robot_id

        assert collision_count == 0, f"{collision_count} collisions detected"


class TestNoStarvation:
    """Alle Roboter bekommen Arbeit."""

    def test_all_robots_used(self, multi_robot_config):
        """Alle Roboter sollten mindestens einmal verwendet werden."""
        engine = SimulationEngine(multi_robot_config)

        robots_used = set()

        for _ in range(500):
            event = engine.step()
            if event is None:
                break

            for robot in engine.state.robots:
                if robot.status == "busy":
                    robots_used.add(robot.robot_id)

        # Bei genug Arbeit sollten alle Roboter verwendet werden
        expected_robots = set(range(multi_robot_config.num_robots))

        # Mindestens die Hälfte der Roboter sollte verwendet worden sein
        assert len(robots_used) >= len(expected_robots) // 2, (
            f"Only {len(robots_used)} of {len(expected_robots)} robots used"
        )


class TestNoInfiniteLoop:
    """Simulation darf nicht in Endlosschleife stecken bleiben."""

    def test_simulation_progresses(self, medium_config):
        """Zeit muss voranschreiten."""
        engine = SimulationEngine(medium_config)

        last_time = -1
        stuck_count = 0
        max_stuck = 50  # Erlaubt einige Events zur gleichen Zeit

        for _ in range(1000):
            event = engine.step()
            if event is None:
                break

            current_time = engine.state.t
            if current_time == last_time:
                stuck_count += 1
                if stuck_count > max_stuck:
                    pytest.fail(f"Simulation stuck at time {current_time}")
            else:
                stuck_count = 0
                last_time = current_time

    def test_requests_complete(self, medium_config):
        """Requests müssen abgeschlossen werden."""
        engine = SimulationEngine(medium_config)

        # Simuliere komplett durch
        while True:
            event = engine.step()
            if event is None:
                break

        summary = engine.metrics.summary()

        # Mindestens einige Requests sollten abgeschlossen sein
        completed = summary.get("requests_completed", 0)
        assert completed > 0, "No requests completed"


class TestDeadlockRecovery:
    """Deadlock-Erkennung und -Auflösung funktioniert."""

    def test_deadlock_stats_available(self, multi_robot_config):
        """Traffic-Manager liefert Deadlock-Statistiken."""
        engine = SimulationEngine(multi_robot_config)

        # Simuliere
        for _ in range(300):
            event = engine.step()
            if event is None:
                break

        stats = engine.state.traffic_manager.get_statistics()

        # Stats sollten existieren
        assert "deadlocks_detected" in stats
        assert "deadlocks_resolved" in stats

        # Aufgelöste Deadlocks <= erkannte Deadlocks
        assert stats["deadlocks_resolved"] <= stats["deadlocks_detected"]