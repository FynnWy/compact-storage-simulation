# tests/test_multi_pickstation.py
"""
Multi-Pickstation-Semantik (Phase 2B, AUDIT-005).

Auswahlregel – hierarchisch, ausgewertet EINMAL unmittelbar nach dem
erfolgreichen Target-Pickup aus dem Storage:

    1. minimale Manhattan-Distanz von der aktuellen Roboterposition
    2. bei Distanzgleichstand: minimale `effective_load`
    3. bei vollständigem Gleichstand: stabiler Stationsindex

    effective_load = inbound + waiting_for_service + in_service

Source of Truth der Zuordnung: `RobotTask.assigned_pickstation`.

Invarianten MP-1 … MP-11 siehe Auftrag / Audit-Dokument.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


def _engine(width=11, depth=7, robots=2, pickstations=2, seed=42, bins=60):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 6
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = 500
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    return SimulationEngine(config)


def _make_task(request_id=4001, bin_id=1):
    return RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))


def _distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _midpoint_between_ports(engine):
    """Position mit exakt gleicher Manhattan-Distanz zu beiden Ports."""
    ps0, ps1 = engine.state.pickstations
    for x in range(engine.state.grid.width):
        for y in range(engine.state.grid.depth):
            pos = (x, y)
            if _distance(pos, ps0.position) == _distance(pos, ps1.position):
                return pos
    return None


# ======================================================================
# MP-2 – Manhattan-Distanz entscheidet
# ======================================================================

def test_selects_nearer_station_ps0():
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    robot.set_position((ps0.position[0] + 1, ps0.position[1]))
    assert _distance(robot.get_position(), ps0.position) < \
        _distance(robot.get_position(), ps1.position)

    chosen = handler._select_pickstation_for_target(robot)
    assert chosen.station_id == ps0.station_id


def test_selects_nearer_station_ps1():
    """
    Reproduziert die alte, harte `pickstations[0]`-Logik: Steht der Roboter
    näher an PS_1, muss PS_1 gewählt werden.
    """
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    robot.set_position((ps1.position[0] - 1, ps1.position[1]))
    assert _distance(robot.get_position(), ps1.position) < \
        _distance(robot.get_position(), ps0.position)

    chosen = handler._select_pickstation_for_target(robot)
    assert chosen.station_id == ps1.station_id, (
        "Nähere Station PS_1 wurde nicht gewählt (alte pickstations[0]-Logik)."
    )


def test_distance_beats_load():
    """
    MP-2: Eine eindeutig nähere Station darf durch Last NICHT verdrängt werden.
    """
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    # Roboter minimal näher an PS_0
    robot.set_position((ps0.position[0] + 1, ps0.position[1]))

    # PS_0 kuenstlich stark belasten
    for i in range(10):
        ps0.enqueue(_make_task(request_id=100 + i, bin_id=i), 0)
    assert handler._effective_pickstation_load(ps0) >= 10
    assert handler._effective_pickstation_load(ps1) == 0

    chosen = handler._select_pickstation_for_target(robot)
    assert chosen.station_id == ps0.station_id, (
        "Last hat eine eindeutig nähere Station verdrängt."
    )


# ======================================================================
# MP-3 – Load-Tiebreak bei gleicher Distanz
# ======================================================================

def test_equal_distance_prefers_lower_load():
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    midpoint = _midpoint_between_ports(engine)
    assert midpoint is not None, "Kein Punkt mit gleicher Distanz gefunden"
    robot.set_position(midpoint)

    for i in range(4):
        ps0.enqueue(_make_task(request_id=200 + i, bin_id=i), 0)
    ps1.enqueue(_make_task(request_id=300, bin_id=50), 0)

    assert handler._effective_pickstation_load(ps0) == 4
    assert handler._effective_pickstation_load(ps1) == 1

    chosen = handler._select_pickstation_for_target(robot)
    assert chosen.station_id == ps1.station_id


def test_inbound_counts_towards_load():
    """
    Bins, die einer Station bereits zugeordnet wurden und noch unterwegs sind,
    müssen als Last zählen.
    """
    engine = _engine(robots=4)
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations

    midpoint = _midpoint_between_ports(engine)
    assert midpoint is not None

    # Drei Roboter tragen bereits Targets Richtung PS_0
    for index in range(3):
        carrier = engine.state.robots[index + 1]
        task = _make_task(request_id=400 + index, bin_id=index)
        task.assigned_pickstation = ps0.station_id
        carrier.assign_task(task)

    assert ps0.queue_length() == 0 and len(ps0.current_tasks) == 0
    assert handler._effective_pickstation_load(ps0) == 3, "inbound zählt nicht"
    assert handler._effective_pickstation_load(ps1) == 0

    robot = engine.state.robots[0]
    robot.set_position(midpoint)
    chosen = handler._select_pickstation_for_target(robot)
    assert chosen.station_id == ps1.station_id


def test_delivered_target_is_not_counted_as_inbound_twice():
    """
    Keine Doppelzählung: Sobald das Target die Station erreicht hat
    (`target_at_pickstation`), zählt es über die Queue – nicht mehr als
    inbound.
    """
    engine = _engine(robots=2)
    handler = engine.event_handler
    ps0, _ = engine.state.pickstations

    carrier = engine.state.robots[1]
    task = _make_task(request_id=500, bin_id=7)
    task.assigned_pickstation = ps0.station_id
    carrier.assign_task(task)
    assert handler._effective_pickstation_load(ps0) == 1

    # Target erreicht die Station
    task.mark_waiting_at_pickstation()
    ps0.enqueue(task, 0)

    assert handler._effective_pickstation_load(ps0) == 1, (
        "Task wurde doppelt gezählt (inbound + queue)."
    )


def test_completed_service_no_longer_counts_as_load():
    """
    Bins, deren Service beendet ist und die nur noch auf Rücktransport warten,
    belegen keine Servicekapazität mehr und zählen nicht als Last.
    """
    engine = _engine(robots=2)
    handler = engine.event_handler
    ps0, _ = engine.state.pickstations

    task = _make_task(request_id=600, bin_id=8)
    task.assigned_pickstation = ps0.station_id
    task.mark_waiting_at_pickstation()
    ps0.start_service(task)
    assert handler._effective_pickstation_load(ps0) == 1

    ps0.complete_service(task)
    task.mark_pickstation_completed()

    assert handler._effective_pickstation_load(ps0) == 0, (
        "Bereits bedienter Task zählt weiterhin als Service-Last."
    )


# ======================================================================
# MP-4 – Vollständiger Gleichstand
# ======================================================================

def test_full_tie_is_deterministic_and_stable():
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    midpoint = _midpoint_between_ports(engine)
    assert midpoint is not None
    robot.set_position(midpoint)

    assert handler._effective_pickstation_load(ps0) == 0
    assert handler._effective_pickstation_load(ps1) == 0

    chosen = [handler._select_pickstation_for_target(robot).station_id
              for _ in range(5)]
    assert len(set(chosen)) == 1, "Auswahl ist nicht deterministisch."
    assert chosen[0] == engine.state.pickstations[0].station_id, (
        "Bei vollständigem Gleichstand muss der stabile Index entscheiden."
    )


# ======================================================================
# MP-5 – Zuordnung bleibt eingefroren
# ======================================================================

def test_assignment_persists_when_load_changes():
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    task = _make_task(request_id=700, bin_id=9)
    robot.assign_task(task)
    task.assigned_pickstation = ps1.station_id

    # Lastverteilung ändert sich drastisch
    for i in range(20):
        ps1.enqueue(_make_task(request_id=800 + i, bin_id=i), 0)

    action = {"type": "remove_target", "from_stack": "S_1_1", "bin_id": 9}
    resolved = handler._get_drop_position_for_action(action, robot=robot)

    assert resolved == ps1.position, (
        "Stationszuordnung wurde nachträglich neu berechnet (MP-5 verletzt)."
    )
    assert task.assigned_pickstation == ps1.station_id


def test_return_robot_drives_to_assigned_station_not_nearest():
    """
    MP-8: Der Abhol-Roboter fährt zu der Station, an der die Bin liegt –
    auch wenn die andere Station näher wäre.
    """
    engine = _engine()
    handler = engine.event_handler
    ps0, ps1 = engine.state.pickstations
    robot = engine.state.robots[0]

    task = _make_task(request_id=900, bin_id=11)
    task.assigned_pickstation = ps1.station_id
    robot.assign_task(task)

    # Roboter steht direkt neben PS_0
    robot.set_position((ps0.position[0] + 1, ps0.position[1]))
    assert _distance(robot.get_position(), ps0.position) < \
        _distance(robot.get_position(), ps1.position)

    action = {
        "type": "return", "return_kind": "target",
        "from_stack": None, "to_stack": "S_2_2", "bin_id": 11,
    }
    resolved = handler._get_target_position_for_action(action, robot=robot)

    assert resolved == ps1.position, (
        "Abhol-Roboter wurde zur näheren statt zur zugeordneten Station "
        "geschickt."
    )


# ======================================================================
# MP-1 / MP-6 / MP-7 / MP-9 / MP-11 – Systemlauf
# ======================================================================

@pytest.mark.parametrize("robots,util,seed", [
    (2, 2.0, 1),
    (4, 2.0, 42),
    (4, 0.5, 99),
])
def test_system_run_multi_pickstation_consistency(robots, util, seed):
    """
    Systemlauf mit zwei Stationen:

    MP-1  jeder Target-Transport hat genau eine zugeordnete Station
    MP-6  Drop erfolgt physisch an genau dieser Station
    MP-7  Service erfolgt dort
    MP-8  Abholung erfolgt dort
    MP-9  keine Cross-Station-Verwechslung
    MP-11 beide Stationen verarbeiten Arbeit
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    engine = SimulationEngine(config)
    handler = engine.event_handler

    cross_station = []
    assignments = {ps.station_id: 0 for ps in engine.state.pickstations}

    original_pickup = handler._handle_robot_pickup
    original_drop = handler._handle_robot_drop

    def checked_pickup(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action") or {}
        assigned_before = getattr(
            getattr(robot, "current_task", None), "assigned_pickstation", None
        )
        before = robot.get_carried_bin() if robot else None
        original_pickup(event)
        after = robot.get_carried_bin() if robot else None
        if robot is None or before == after or after is None:
            return
        if action.get("type") == "remove_target":
            task = robot.current_task
            station_id = getattr(task, "assigned_pickstation", None)
            assert station_id is not None, "MP-1: keine Station zugeordnet"
            assignments[station_id] += 1
        if action.get("type") == "return" and action.get("from_stack") is None:
            here = engine.state.find_pickstation_at(robot.get_position())
            if here is None or (assigned_before
                                and here.station_id != assigned_before):
                cross_station.append(
                    ("pickup", engine.state.t, robot.robot_id,
                     here.station_id if here else None, assigned_before)
                )

    def checked_drop(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action") or {}
        if action.get("type") != "remove_target" or robot is None:
            return original_drop(event)
        assigned_before = getattr(
            getattr(robot, "current_task", None), "assigned_pickstation", None
        )
        position = robot.get_position()
        carried = robot.get_carried_bin()
        original_drop(event)
        if robot.get_carried_bin() == carried:
            return
        here = engine.state.find_pickstation_at(position)
        if here is None or (assigned_before
                            and here.station_id != assigned_before):
            cross_station.append(
                ("drop", engine.state.t, robot.robot_id,
                 here.station_id if here else None, assigned_before)
            )

    handler._handle_robot_pickup = checked_pickup
    handler._handle_robot_drop = checked_drop

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

    assert not cross_station, (
        f"MP-9 verletzt: {len(cross_station)} Cross-Station-Vorgänge, "
        f"erste 5: {cross_station[:5]}"
    )

    served = {ps.station_id: ps.total_tasks_processed
              for ps in engine.state.pickstations}
    assert all(count > 0 for count in served.values()), (
        f"MP-11 verletzt: nicht beide Stationen haben Arbeit verarbeitet "
        f"({served}, Zuordnungen: {assignments})"
    )
