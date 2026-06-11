# tests/test_edge_cases.py
"""
Edge-Case Tests.

Testet Grenzfälle die in echten Lägern Probleme verursachen könnten.

HINWEIS: Minimale Grid-Größe ist 7x7, da kleinere Grids mit Pickstations
und Pufferzonen kaum sinnvoll testbar sind.

KAPAZITÄTSBERECHNUNG:
- Pickstation-Positionen sind KEINE Storage-Stacks
- Bei 7x7 Grid mit 1 Pickstation: 49 - 1 = 48 Storage-Stacks
- Bei 8x8 Grid mit 1 Pickstation: 64 - 1 = 63 Storage-Stacks
"""
import pytest
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


class TestFullGrid:
    """Volles Grid (alle Stacks auf max_height)."""

    def test_full_grid_no_crash(self):
        """Volles Grid darf nicht crashen."""
        config = SimulationConfig()
        config.grid_width = 7
        config.grid_depth = 7
        config.max_stack_height = 4
        # 7x7 = 49 Zellen, minus 1 Pickstation = 48 Storage-Stacks
        # 48 * 4 = 192 max. Kapazität
        # 90% Auslastung = 172 Bins (etwas Puffer für Relocations)
        config.bin_num = 172
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
    """Minimale Konfiguration (mit sinnvoller Grid-Größe)."""

    def test_single_robot_minimal_grid(self):
        """1 Roboter, minimales sinnvolles Grid (7x7)."""
        config = SimulationConfig()
        config.grid_width = 7
        config.grid_depth = 7
        config.max_stack_height = 3
        # 48 Storage-Stacks * 3 Höhe = 144 max. Kapazität
        # 50% Auslastung = 72 Bins
        config.bin_num = 72
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
        config.grid_width = 8
        config.grid_depth = 8
        config.max_stack_height = 5
        # 64 - 1 Pickstation = 63 Storage-Stacks
        # 63 * 5 = 315 max. Kapazität
        # 70% Auslastung = 220 Bins
        config.bin_num = 220
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
        config.grid_width = 8
        config.grid_depth = 8
        config.max_stack_height = 5
        # 63 Storage-Stacks * 5 = 315, davon 63% = 200 Bins
        config.bin_num = 200
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
        config.grid_width = 8
        config.grid_depth = 8
        config.max_stack_height = 5
        # 63 Storage-Stacks * 5 = 315, davon 63% = 200 Bins
        config.bin_num = 200
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