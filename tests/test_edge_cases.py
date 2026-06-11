# tests/test_edge_cases.py
"""
Edge-Case Tests.

Testet Grenzfälle die in echten Lägern Probleme verursachen könnten.
"""
import pytest
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


class TestFullGrid:
    """Volles Grid (alle Stacks auf max_height)."""

    def test_full_grid_no_crash(self):
        """Volles Grid darf nicht crashen."""
        config = SimulationConfig()
        config.grid_width = 3
        config.grid_depth = 3
        config.max_stack_height = 4
        # Genau genug Bins um Grid zu füllen: 3*3*4 = 36
        config.bin_num = 36
        config.num_robots = 1
        config.simulation_time = 200
        config.random_seed = 42
        config.enable_visualization = False

        engine = SimulationEngine(config)

        try:
            for _ in range(200):
                event = engine.step()
                if event is None:
                    break
        except RuntimeError as e:
            # "no capacity" Fehler sind bei vollem Grid erwartet
            if "capacity" not in str(e).lower():
                raise  # Andere Fehler weiterwerfen


class TestMinimalConfig:
    """Minimale Konfiguration."""

    def test_single_robot_single_stack(self):
        """1 Roboter, minimales Grid."""
        config = SimulationConfig()
        config.grid_width = 2
        config.grid_depth = 2
        config.max_stack_height = 3
        config.bin_num = 10
        config.num_robots = 1
        config.simulation_time = 100
        config.random_seed = 42
        config.enable_visualization = False

        engine = SimulationEngine(config)

        for _ in range(100):
            event = engine.step()
            if event is None:
                break


class TestDifferentStrategies:
    """Verschiedene Strategie-Kombinationen."""

    @pytest.mark.parametrize("reordering,placement", [
        ("LOFI", "ORIGINAL"),
        ("LOFI", "RANDOM"),
        ("ABC", "ORIGINAL"),
        ("ABC", "ABC"),
        ("POPULARITY", "POPULARITY"),
    ])
    def test_strategy_combinations(self, reordering, placement):
        """Verschiedene Strategie-Kombinationen sollten funktionieren."""
        config = SimulationConfig()
        config.grid_width = 4
        config.grid_depth = 4
        config.max_stack_height = 5
        config.bin_num = 40
        config.num_robots = 2
        config.simulation_time = 300
        config.random_seed = 42
        config.enable_visualization = False
        config.reordering_strategy = reordering
        config.placement_strategy = placement

        engine = SimulationEngine(config)

        # Sollte ohne Crash durchlaufen
        for _ in range(300):
            event = engine.step()
            if event is None:
                break

        # Mindestens einige Events verarbeitet
        assert engine._processed_events > 0


class TestSchedulerStrategies:
    """Verschiedene Scheduler-Strategien."""

    @pytest.mark.parametrize("scheduler", ["FIFO", "EDF"])
    def test_scheduler_strategies(self, scheduler):
        """FIFO und EDF sollten funktionieren."""
        config = SimulationConfig()
        config.grid_width = 4
        config.grid_depth = 4
        config.bin_num = 40
        config.num_robots = 2
        config.simulation_time = 300
        config.random_seed = 42
        config.enable_visualization = False
        config.scheduler_strategy = scheduler

        engine = SimulationEngine(config)

        for _ in range(300):
            event = engine.step()
            if event is None:
                break


class TestHighwaySystem:
    """Highway-System Tests."""

    @pytest.mark.parametrize("pattern", ["ring", "rows", "lanes", "none"])
    def test_highway_patterns(self, pattern):
        """Alle Highway-Patterns sollten funktionieren."""
        config = SimulationConfig()
        config.grid_width = 5
        config.grid_depth = 5
        config.bin_num = 50
        config.num_robots = 2
        config.simulation_time = 200
        config.random_seed = 42
        config.enable_visualization = False
        config.enable_highway_system = True
        config.highway_pattern = pattern

        engine = SimulationEngine(config)

        for _ in range(200):
            event = engine.step()
            if event is None:
                break