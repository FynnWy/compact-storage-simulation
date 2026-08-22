# tests/conftest.py
"""
Shared pytest fixtures für alle Tests.
"""
import pytest
import sys
from pathlib import Path

# Projekt-Root zum Python-Path hinzufügen
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from state.storage_grid import StorageGrid
from traffic.reservation_table import ReservationTable
from traffic.pathfinder import Pathfinder
from traffic.traffic_manager import TrafficManager
from traffic.deadlock_detector import DeadlockDetector, DeadlockResolver
from traffic.highway_rules import HighwayRules


@pytest.fixture
def small_config():
    """
    Minimale Konfiguration für schnelle Tests.

    FINAL FREEZE CLOSEOUT: Seit die Initialverteilung dieselbe
    Storage-Eligibility nutzt wie das Laufzeit-Placement, ist die
    Port-Pufferzone (Manhattan ≤ 1 um den Port) auch initial gesperrt.

    Auf dem alten 3x3-Grid sperrt sie 4 der 9 Zellen. Übrig blieben 5
    zulässige Stacks – zu wenig, um überhaupt umlagern zu können: der
    Originalstack läuft beim Rücklagern zuverlässig voll
    (`Cannot select original return stack: ... has no free capacity`).
    Ein 3x3-Grid mit Port ist unter der finalen Eligibility schlicht keine
    gültige Konfiguration mehr.

    Deshalb 4x4 statt 3x3: die Pufferzone sperrt weiterhin 4 Zellen, es
    bleiben aber 12 zulässige Stacks mit 12 x 4 = 48 Slots. `bin_num = 30`
    hält den ursprünglichen Füllgrad von 62,5 % (vorher 20/32) exakt.

    Kein Fallback in der Produktionslogik: die Fixture erfüllt die
    Vorbedingung jetzt explizit.
    """
    config = SimulationConfig()
    config.grid_width = 4
    config.grid_depth = 4
    config.max_stack_height = 4
    config.bin_num = 30
    config.num_robots = 1
    config.simulation_time = 200
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return config


@pytest.fixture
def medium_config():
    """Mittlere Konfiguration für Integrationstests."""
    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 6
    config.bin_num = 60
    config.num_robots = 2
    config.simulation_time = 500
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return config


@pytest.fixture
def multi_robot_config():
    """Konfiguration für Multi-Robot-Tests."""
    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 6
    config.bin_num = 50
    config.num_robots = 3
    config.simulation_time = 300
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return config


@pytest.fixture
def reservation_table():
    """Leere ReservationTable für Unit-Tests."""
    return ReservationTable(grid_width=5, grid_depth=5, time_horizon=100)


@pytest.fixture
def grid():
    """Leeres StorageGrid für Unit-Tests."""
    # Keine Ports in den generischen Grid-Fixtures → vollständiges Storage-Grid
    return StorageGrid(5, 5)


@pytest.fixture
def pathfinder(grid, reservation_table):
    """Pathfinder ohne Highway-Regeln."""
    return Pathfinder(grid, reservation_table)


@pytest.fixture
def pathfinder_with_highway(grid, reservation_table):
    """Pathfinder mit Highway-Regeln (Ring-Pattern)."""
    hw = HighwayRules(5, 5, pattern="ring")
    return Pathfinder(grid, reservation_table, highway_rules=hw)


@pytest.fixture
def deadlock_detector():
    """Leerer DeadlockDetector."""
    return DeadlockDetector()