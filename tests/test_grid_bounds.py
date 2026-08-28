# tests/test_grid_bounds.py
"""
Geometrie-Invariante: Es gibt keinen Raum außerhalb des Grids
(Phase 2B, AUDIT-002).

`Pickstation_Logik.md` ist hier verbindlich:

    „Die Port-Säule befindet sich vollständig innerhalb des Grids und belegt
     dort eine reguläre Grid-Zelle. […] Es existiert keine zusätzliche
     externe Übergabezone außerhalb des Grids."

Der Simulationskern enthielt jedoch noch Reste einer älteren Modellgeneration
mit Ports LINKS NEBEN dem Grid:

    - `Pathfinder._is_valid_position`   erlaubte `-5 <= x < 0`
    - `ReservationTable._is_valid_position` erlaubte ±5 außerhalb
    - `EventHandler._handle_robot_move` behandelte `x < 0` als „PS-Bereich"

Beobachtet wurden dadurch real geplante und ausgeführte Bewegungen wie
`(-1,3) → (-1,2) → (-1,1)`. Solche Abkürzungen durch nicht existierenden Raum
verkürzen Wegzeiten systematisch und verzerren jeden Strategievergleich.

Invariante:

    G-1  Keine geplante, reservierte oder ausgeführte Position darf außerhalb
         des Grids liegen.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from traffic.pathfinder import Pathfinder
from traffic.reservation_table import ReservationTable


# ======================================================================
# G-1 auf Komponentenebene
# ======================================================================

def test_reservation_table_rejects_positions_outside_grid():
    """
    Modellkorrektur gegenüber der Altgeneration: Positionen außerhalb des
    Grids sind keine gültigen Modellpositionen mehr.
    """
    table = ReservationTable(grid_width=5, grid_depth=5, time_horizon=100)

    assert table.reserve(robot_id=0, x=-1, y=2, t=10) is False
    assert table.reserve(robot_id=0, x=5, y=2, t=10) is False
    assert table.reserve(robot_id=0, x=2, y=-1, t=10) is False
    assert table.reserve(robot_id=0, x=2, y=5, t=10) is False

    # Gültige Grid-Positionen weiterhin reservierbar
    assert table.reserve(robot_id=0, x=0, y=0, t=10) is True
    assert table.reserve(robot_id=0, x=4, y=4, t=10) is True


def test_pathfinder_never_leaves_the_grid(grid, reservation_table):
    """
    Der Pathfinder darf keine Zelle außerhalb des Grids als gültig ansehen.
    """
    finder = Pathfinder(grid, reservation_table)

    assert finder._is_valid_position(0, 0) is True
    assert finder._is_valid_position(4, 4) is True

    assert finder._is_valid_position(-1, 2) is False
    assert finder._is_valid_position(-3, 2) is False
    assert finder._is_valid_position(2, -1) is False
    assert finder._is_valid_position(5, 2) is False
    assert finder._is_valid_position(2, 5) is False


def test_pathfinder_path_stays_inside_grid(grid, reservation_table):
    finder = Pathfinder(grid, reservation_table)
    path = finder.find_path(
        start=(0, 3), target=(0, 1), start_time=0, robot_id=0
    )
    assert path is not None
    for x, y in path:
        assert 0 <= x < grid.width and 0 <= y < grid.depth, (
            f"Pfad verlässt das Grid: {path}"
        )


# ======================================================================
# G-1 im Systemlauf
# ======================================================================

@pytest.mark.parametrize("robots,pickstations,util,seed", [
    (3, 1, 0.5, 7),    # exaktes AUDIT-002-Szenario
    (4, 2, 2.0, 42),
    (2, 1, 2.0, 1),
    (4, 1, 0.5, 4),
])
def test_no_robot_leaves_the_grid_during_run(robots, pickstations, util, seed):
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    engine = SimulationEngine(config)

    width = engine.state.grid.width
    depth = engine.state.grid.depth
    violations = []

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            for robot in engine.state.robots:
                position = robot.get_position()
                if position is not None and not (
                        0 <= position[0] < width and 0 <= position[1] < depth
                ):
                    violations.append(
                        (engine.state.t, robot.robot_id, position)
                    )
                for waypoint in robot.planned_path:
                    if not (0 <= waypoint[0] < width
                            and 0 <= waypoint[1] < depth):
                        violations.append(
                            (engine.state.t, robot.robot_id, "geplant",
                             waypoint)
                        )
            if violations:
                break

    assert not violations, (
        f"Positionen/Pfade außerhalb des Grids: {violations[:5]}"
    )
