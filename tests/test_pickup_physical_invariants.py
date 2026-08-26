# tests/test_pickup_physical_invariants.py
"""
Physische Pickup-Invarianten (Phase 2B, AUDIT-001 + AUDIT-004).

Invarianten:

    P-1  Ein Roboter darf eine Bin nur an ihrer tatsächlichen Quelle aufnehmen.
         Das gilt für Stack-Pickups UND für Pickups an der Pickstation.

    P-2  Ein Roboter darf keinen Pickup einer Bin ausführen, während er bereits
         eine ANDERE Bin trägt.

    P-3  Ein Duplikat-Pickup derselben, bereits getragenen Bin ist idempotent
         (er darf den Zustand nicht verändern, aber auch nicht scheitern).

    P-4  `carried_bin_id` ist die einheitliche Wahrheit darüber, welcher Roboter
         welche Bin trägt – in BEIDEN Ablaufgenerationen (Zwei-Phasen-Pipeline
         und `pickup_from_pickstation`-Executor).
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from simulation.simulation_engine import SimulationEngine


def _build_engine(num_robots=2, pickstations=1, width=6, depth=6, seed=42):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 4
    config.bin_num = 40
    config.num_robots = num_robots
    config.num_pickstations = pickstations
    config.simulation_time = 200
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def _find_non_empty_stack(engine, exclude=()):
    for stack in engine.state.grid.all_stacks():
        if stack.height() > 0 and stack.stack_id not in exclude:
            return stack
    raise AssertionError("Kein nicht-leerer Stack im Testaufbau gefunden")


def _put_bin_at_pickstation(engine, station, source=None):
    """Erzeugt den Zustand nach einem `remove_target`-Drop."""
    stack = engine.state.grid.get_stack(*source) if source else None
    if stack is None or stack.height() == 0:
        stack = _find_non_empty_stack(engine)
    bin_obj = stack.peek()
    stack.pop()
    engine.event_handler._sync_stack_bin_metadata(stack)
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.set_status("at_pickstation")
    bin_obj.mark_transit_done()
    return bin_obj


def _give_robot_task_for(engine, robot, bin_id, request_id=9001):
    """
    Stattet den Roboter mit einem Task für genau diese Bin aus.

    LIVENESS (2026-08-22): Ein Pickup gehört immer zu einem Task. Ein
    Pickup-Event eines Roboters OHNE Task gilt seit dieser Änderung als
    verwaist und wird verworfen – im Produktivlauf nahm ein solcher Roboter
    sonst eine FREMDE Bin an der Pickstation auf und blockierte danach
    dauerhaft die einzige Portzelle (LR+NR/Seed 42, t=2184).

    Die Fixtures stellen die reale Vorbedingung deshalb explizit her, statt
    sich auf einen Zustand zu stützen, den es im Produktivlauf nicht gibt.
    """
    from requests_.request import Request
    from simulation.robot_task import RobotTask

    task = RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))
    robot.assign_task(task)
    return task


def _take_bin_into_hand(engine, robot, source=(2, 3)):
    stack = engine.state.grid.get_stack(*source)
    if stack is None or stack.height() == 0:
        stack = _find_non_empty_stack(engine)
    bin_obj = stack.peek()
    stack.pop()
    engine.event_handler._sync_stack_bin_metadata(stack)
    bin_obj.mark_in_transit()
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    robot.set_carried_bin(bin_obj.bin_id)
    return bin_obj


# ======================================================================
# P-1 – Positionsinvariante für Pickstation-Pickups
# ======================================================================

def test_pickup_from_pickstation_requires_robot_on_port():
    """
    AUDIT-001: Ein Roboter darf eine Bin nicht aus der Ferne von der
    Pickstation aufnehmen.

    Vor dem Fix schlägt dieser Test fehl – der Pickup gelingt über vier
    Zellen Distanz.
    """
    engine = _build_engine()
    handler = engine.event_handler
    station = engine.state.pickstations[0]

    robot = engine.state.robots[0]
    bin_obj = _put_bin_at_pickstation(engine, station)

    away = (4, 4) if station.position != (4, 4) else (3, 4)
    robot.set_position(away)
    assert robot.get_position() != station.position

    action = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": "S_1_1",
        "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() is None, (
        "Bin wurde aus der Ferne von der Pickstation aufgenommen."
    )
    assert not bin_obj.in_transit
    assert bin_obj.get_status() == "at_pickstation"


def test_pickup_from_pickstation_succeeds_on_port():
    """Gegenprobe: Auf der Port-Zelle muss der Pickup normal funktionieren."""
    engine = _build_engine()
    handler = engine.event_handler
    station = engine.state.pickstations[0]

    robot = engine.state.robots[0]
    bin_obj = _put_bin_at_pickstation(engine, station)
    robot.set_position(station.position)
    _give_robot_task_for(engine, robot, bin_obj.bin_id)

    action = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": "S_1_1",
        "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() == bin_obj.bin_id
    assert bin_obj.in_transit


def test_pickup_at_wrong_pickstation_is_rejected():
    """
    MP-8/MP-9: Steht der Roboter auf der FALSCHEN Station, darf er die Bin
    dort nicht aufnehmen – auch wenn es physisch eine Port-Zelle ist.
    """
    engine = _build_engine(num_robots=2, pickstations=2, width=7, depth=7)
    handler = engine.event_handler
    assert len(engine.state.pickstations) == 2
    assigned, other = engine.state.pickstations

    robot = engine.state.robots[0]
    bin_obj = _put_bin_at_pickstation(engine, assigned)

    from events.event_types import EventType as _ET
    from requests_.request import Request
    from simulation.robot_task import RobotTask

    task = RobotTask(Request(
        request_id=5001, event_type=_ET.ARRIVAL, bin_id=bin_obj.bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))
    task.assigned_pickstation = assigned.station_id
    robot.assign_task(task)

    # Roboter steht auf der ANDEREN Station
    robot.set_position(other.position)

    action = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": "S_1_1",
        "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=task.request, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() is None, (
        "Bin wurde an der falschen Pickstation aufgenommen "
        "(Cross-Station-Verwechslung)."
    )


# ======================================================================
# P-2 / P-3 – Carrying-Invariante
# ======================================================================

def test_pickup_is_rejected_while_carrying_another_bin():
    """
    AUDIT-004: Der Pickup einer zweiten, anderen Bin muss scheitern.
    Sonst wird `carried_bin_id` überschrieben und die erste Bin verwaist.
    """
    engine = _build_engine()
    handler = engine.event_handler
    station = engine.state.pickstations[0]

    robot = engine.state.robots[0]
    carried = _take_bin_into_hand(engine, robot)
    other = _put_bin_at_pickstation(engine, station)

    robot.set_position(station.position)

    action = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": "S_1_1",
        "bin_id": other.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() == carried.bin_id, (
        "Trage-Verknüpfung wurde durch einen zweiten Pickup überschrieben."
    )
    assert carried.in_transit, "Erste Bin ist verwaist."
    assert not other.in_transit, "Zweite Bin wurde trotzdem aufgenommen."


def test_pickup_from_stack_is_rejected_while_carrying_another_bin():
    """Gleiche Invariante für Stack-Pickups."""
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    carried = _take_bin_into_hand(engine, robot)

    source = engine.state.grid.get_stack(3, 3)
    if source is None or source.height() == 0:
        source = _find_non_empty_stack(engine)
    target_bin = source.peek()
    height_before = source.height()
    robot.set_position((3, 3))

    action = {
        "type": "relocate",
        "from_stack": source.stack_id,
        "to_stack": "S_1_1",
        "bin_id": target_bin.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() == carried.bin_id
    assert source.height() == height_before, (
        "Zweite Bin wurde aus dem Stack entnommen, obwohl der Roboter "
        "bereits eine Bin trägt."
    )


def test_duplicate_pickup_of_same_bin_stays_idempotent():
    """
    P-3: Ein Duplikat-Event für die BEREITS GETRAGENE Bin darf den Zustand
    nicht verändern und muss in die Drop-Phase übergehen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((3, 3))
    carried = _take_bin_into_hand(engine, robot, source=(3, 3))

    action = {
        "type": "relocate",
        "from_stack": "S_3_3",
        "to_stack": "S_1_1",
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        handler._handle_robot_pickup(event)

    assert "[STALE][PICKUP]" in buf.getvalue()
    assert robot.get_carried_bin() == carried.bin_id
    assert carried.in_transit


# ======================================================================
# P-4 – Systemweite Invariante
# ======================================================================

@pytest.mark.parametrize("num_robots,pickstations,util,seed", [
    (2, 1, 0.5, 42),
    (4, 1, 2.0, 42),
    (4, 2, 2.0, 42),
    (3, 2, 0.5, 99),
])
def test_no_physically_invalid_pickups_during_run(num_robots, pickstations,
                                                  util, seed):
    """
    Systemlauf: Kein erfolgreicher Pickup darf aus einer Position erfolgen,
    die nicht der tatsächlichen Quelle entspricht.
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = num_robots
    config.num_pickstations = pickstations
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    engine = SimulationEngine(config)

    handler = engine.event_handler
    original = handler._handle_robot_pickup
    violations = []

    def checked(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action") or {}
        before = robot.get_carried_bin() if robot else None
        position = robot.get_position() if robot else None
        original(event)
        after = robot.get_carried_bin() if robot else None
        if robot is None or before == after or after is None:
            return
        from_stack = action.get("from_stack")
        if from_stack is not None:
            expected = handler._resolve_position(from_stack)
        else:
            station = handler._resolve_assigned_pickstation(robot=robot)
            expected = station.position if station else None
        if expected is not None and position != expected:
            violations.append(
                (engine.state.t, robot.robot_id, position, expected,
                 action.get("type"))
            )

    handler._handle_robot_pickup = checked

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

    assert not violations, (
        f"{len(violations)} physisch unmögliche Pickups, "
        f"erste 5: {violations[:5]}"
    )


@pytest.mark.parametrize("num_robots,pickstations,util,seed", [
    (4, 1, 2.0, 42),
    (4, 2, 2.0, 42),
])
def test_no_orphaned_transit_bins_during_run(num_robots, pickstations,
                                             util, seed):
    """
    AUDIT-004: Massenerhaltung. Jede Bin liegt am Ende in genau einer Rolle
    vor und keine Bin ist `in_transit` ohne Träger.
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = num_robots
    config.num_pickstations = pickstations
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "RANDOM"
    engine = SimulationEngine(config)

    orphans = []

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            carried = {
                r.get_carried_bin() for r in engine.state.robots
                if r.is_carrying_bin()
            }
            for bin_obj in engine.state.bins:
                if not bin_obj.in_transit:
                    continue
                if bin_obj.bin_id in carried:
                    continue
                if bin_obj.get_status() == "at_pickstation":
                    continue
                orphans.append((engine.state.t, bin_obj.bin_id))
            if orphans:
                break

    assert not orphans, f"Verwaiste Transit-Bins: {orphans[:5]}"
