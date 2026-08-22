# tests/test_evade_hardening.py
"""
Absicherung der Deadlock-Recovery `_evade_robot` (Hardening, Baseline 58c5ef2).

Hintergrund:
`_evade_robot` versetzt einen Roboter zur Deadlock-Auflösung physisch auf eine
Nachbarzelle. Bereits geplante Pickup-/Drop-/Move-Events des alten Plans
bleiben dabei in der EventQueue.

Diese Datei prüft drei Dinge:

1. **Drop-Positionsinvariante** – ein Drop darf den Bin-State nur verändern,
   wenn der Roboter physisch an der vorgesehenen Ablageposition steht.
   (Vor dem Hardening NICHT garantiert.)
2. **Carrying Robot + Evade** – eine getragene Bin bleibt konsistent im
   Transit-State; sie wird weder dupliziert noch verloren.
3. **Stale Events nach Evade** – kein alter Plan wird später unbemerkt
   ausgeführt.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from simulation.simulation_engine import SimulationEngine


def _build_engine(num_robots=2, width=6, depth=6, seed=42, pickstations=1):
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
    """
    Liefert irgendeinen belegten Stack.

    PHASE 4: Die Initialverteilung stammt jetzt aus einem abgeleiteten
    Zufallsstrom, dadurch ist nicht mehr jede fest verdrahtete Position
    belegt. Die Tests stellen ihre Vorbedingung deshalb explizit her, statt
    sich auf ein zufälliges Layout zu verlassen. Geprüft wird unverändert
    dasselbe Verhalten. (Dasselbe Muster nutzt
    `tests/test_pickup_physical_invariants.py` bereits seit Phase 2B.)
    """
    for stack in engine.state.grid.all_stacks():
        if stack.height() > 0 and stack.stack_id not in exclude:
            return stack
    raise AssertionError("Kein nicht-leerer Stack im Testaufbau gefunden")


def _position_of(stack):
    """(x, y)-Position eines Stacks aus seiner ID."""
    stack_id = stack.stack_id
    if isinstance(stack_id, tuple):
        return stack_id
    parts = stack_id.split("_")
    return int(parts[1]), int(parts[2])


def _take_bin_into_transit(engine, stack_position):
    """Nimmt die oberste Bin eines Stacks 'in die Hand' des Roboters."""
    stack = engine.state.grid.get_stack(*stack_position)
    if stack is None or stack.height() == 0:
        stack = _find_non_empty_stack(engine)
    bin_obj = stack.peek()
    assert bin_obj is not None, f"Stack {stack.stack_id} ist leer"
    stack.pop()
    engine.event_handler._sync_stack_bin_metadata(stack)
    bin_obj.mark_in_transit()
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    return bin_obj


def _bin_occurrences(engine, bin_obj):
    """Zählt, in wie vielen Stacks die Bin physisch liegt."""
    return sum(
        1
        for stack in engine.state.grid.all_stacks()
        if bin_obj in stack.bins
    )


# ======================================================================
# 1. Drop-Positionsinvariante
# ======================================================================

def test_drop_requires_robot_at_target_stack_position():
    """
    Kern-Invariante:
    Ein Roboter darf keinen erfolgreichen Drop auf einem Stack ausführen,
    wenn er physisch nicht an dessen Position steht.

    Vor dem Hardening schlägt dieser Test fehl: die Bin landet im Stack,
    obwohl der Roboter mehrere Zellen entfernt steht.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    carried = _take_bin_into_transit(engine, (3, 3))

    target_stack = engine.state.grid.get_stack(2, 2)
    height_before = target_stack.height()

    # Roboter steht bewusst NICHT an (2, 2)
    robot.set_position((5, 5))

    action = {
        "type": "relocate",
        "from_stack": "S_3_3",
        "to_stack": target_stack.stack_id,
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert carried not in target_stack.bins, (
        "Bin wurde abgelegt, obwohl der Roboter nicht am Ziel-Stack steht "
        "(physisch unmöglicher Drop)."
    )
    assert target_stack.height() == height_before
    assert carried.in_transit, (
        "Bin wurde aus dem Transit-State entlassen, ohne tatsächlich "
        "abgelegt worden zu sein."
    )


def test_drop_at_pickstation_requires_robot_on_port():
    """
    Gleiche Invariante für `remove_target`: Die Bin darf erst an der
    Pickstation abgegeben werden, wenn der Roboter dort steht.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    carried = _take_bin_into_transit(engine, (3, 3))

    pickstation = engine.state.get_all_pickstations()[0]
    # Roboter steht irgendwo, nur nicht auf dem Port
    away = (4, 4) if pickstation.position != (4, 4) else (3, 4)
    robot.set_position(away)

    action = {
        "type": "remove_target",
        "from_stack": "S_3_3",
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert carried.get_status() != "at_pickstation", (
        "Bin wurde an der Pickstation abgegeben, obwohl der Roboter nicht "
        "auf der Port-Zelle steht."
    )
    assert carried.in_transit


def test_drop_succeeds_when_robot_is_at_target_position():
    """
    Gegenprobe: Steht der Roboter korrekt am Ziel-Stack, muss der Drop
    unverändert funktionieren.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    carried = _take_bin_into_transit(engine, (3, 3))

    target_stack = engine.state.grid.get_stack(2, 2)
    robot.set_position((2, 2))

    action = {
        "type": "relocate",
        "from_stack": "S_3_3",
        "to_stack": target_stack.stack_id,
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert carried in target_stack.bins
    assert not carried.in_transit
    assert carried.get_stack() == (2, 2)


# ======================================================================
# 2. Carrying Robot + Evade
# ======================================================================

def test_carrying_robot_keeps_bin_state_consistent_after_evade():
    """
    Ein Roboter, der eine Bin trägt, darf durch `_evade_robot` versetzt
    werden, ohne dass die Bin dupliziert, verloren oder gleichzeitig in
    Transit und in einem Stack sichtbar wird.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((3, 3))
    carried = _take_bin_into_transit(engine, (2, 3))

    assert carried.in_transit
    assert _bin_occurrences(engine, carried) == 0

    with contextlib.redirect_stdout(io.StringIO()):
        evaded = handler._evade_robot(robot, forbidden_cells={(3, 4)})

    assert evaded, "Ausweichen war nicht möglich – Testaufbau prüfen."

    # Bin-State darf sich durch das Ausweichen nicht verändern
    assert carried.in_transit, "Bin verlor ihren Transit-State beim Ausweichen."
    assert carried.get_stack() is None
    assert _bin_occurrences(engine, carried) == 0, (
        "Bin ist nach dem Ausweichen gleichzeitig in Transit und in einem Stack."
    )

    # Bin existiert weiterhin genau einmal im State
    ids = [b.bin_id for b in engine.state.bins]
    assert ids.count(carried.bin_id) == 1


def test_stale_drop_event_after_evade_does_not_corrupt_state():
    """
    Der in der Dokumentation beschriebene Risikoablauf:

        Robot trägt Bin → Drop auf Stack X geplant → Deadlock
        → _evade_robot versetzt Robot auf Zelle Y
        → altes Drop-Event feuert später

    Das alte Drop-Event darf den Bin-State NICHT verändern.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((3, 3))
    carried = _take_bin_into_transit(engine, (2, 3))

    target_stack = engine.state.grid.get_stack(3, 3)
    action = {
        "type": "relocate",
        "from_stack": "S_2_3",
        "to_stack": target_stack.stack_id,
        "bin_id": carried.bin_id,
    }
    stale_drop = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        assert handler._evade_robot(robot, forbidden_cells={(4, 3)})
        # Ausweichzug deterministisch ausführen (ohne Engine-Scheduling,
        # das den Testaufbau überschreiben würde)
        engine.state.set_time(engine.state.t + 1)
        evade_move = handler.event_builder.build_robot_move_event(
            robot=robot, time=engine.state.t
        )
        handler._handle_robot_move(evade_move)

    assert robot.get_position() != (3, 3), "Roboter ist nicht ausgewichen."

    height_before = target_stack.height()

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(stale_drop)

    assert target_stack.height() == height_before, (
        "Stale Drop-Event hat die Bin abgelegt, obwohl der Roboter nach dem "
        "Ausweichen nicht mehr am Ziel-Stack steht."
    )
    assert carried.in_transit
    assert _bin_occurrences(engine, carried) == 0


def test_stale_pickup_event_after_evade_is_rejected():
    """
    Analog für Pickup: Nach dem Ausweichen steht der Roboter nicht mehr am
    Quell-Stack; das alte Pickup-Event darf keine Bin aus dem Stack ziehen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    source_stack = engine.state.grid.get_stack(3, 3)
    if source_stack is None or source_stack.height() == 0:
        source_stack = _find_non_empty_stack(engine)
    # Der Roboter steht zunächst am Quellstack und weicht gleich aus.
    robot.set_position(_position_of(source_stack))

    top_bin = source_stack.peek()
    height_before = source_stack.height()

    action = {
        "type": "relocate",
        "from_stack": source_stack.stack_id,
        "to_stack": "S_1_1",
        "bin_id": top_bin.bin_id,
    }
    stale_pickup = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        assert handler._evade_robot(robot, forbidden_cells={(4, 3)})
        engine.state.set_time(engine.state.t + 1)
        evade_move = handler.event_builder.build_robot_move_event(
            robot=robot, time=engine.state.t
        )
        handler._handle_robot_move(evade_move)
        assert robot.get_position() != (3, 3), "Roboter ist nicht ausgewichen."
        handler._handle_robot_pickup(stale_pickup)

    assert source_stack.height() == height_before, (
        "Stale Pickup-Event hat eine Bin entnommen, obwohl der Roboter nach "
        "dem Ausweichen nicht mehr am Quell-Stack steht."
    )
    assert not top_bin.in_transit


def test_stale_move_events_after_evade_do_not_move_robot_further():
    """
    Nach dem Ausweichen liegen ggf. noch alte ROBOT_MOVE-Events des früheren
    Plans in der Queue. Sie dürfen den Roboter nicht entlang des alten Pfads
    weiterbewegen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((1, 1))
    # Alter Plan: mehrere Schritte nach rechts
    robot.set_path([(2, 1), (3, 1), (4, 1)], target_action=None)

    old_moves = [
        handler.event_builder.build_robot_move_event(robot=robot, time=engine.state.t + i)
        for i in range(1, 4)
    ]

    with contextlib.redirect_stdout(io.StringIO()):
        assert handler._evade_robot(robot, forbidden_cells={(2, 1)})

    # Der Ausweichpfad ersetzt den alten Plan vollständig
    assert robot.planned_path != [(2, 1), (3, 1), (4, 1)]
    assert len(robot.planned_path) == 1

    evade_cell = robot.planned_path[0]

    with contextlib.redirect_stdout(io.StringIO()):
        for move_event in old_moves:
            engine.state.set_time(engine.state.t + 1)
            handler._handle_robot_move(move_event)

    assert robot.get_position() in ((1, 1), evade_cell), (
        f"Roboter folgte nach dem Ausweichen weiterhin dem alten Plan: "
        f"{robot.get_position()}"
    )


# ======================================================================
# 3. Getragene Bin darf nie verwaisen
# ======================================================================

def test_carrying_robot_is_never_requeued_by_deadlock_recovery():
    """
    `_resolve_move_deadlock` darf einen Roboter, der eine Bin trägt, nicht
    von seinem Task trennen. Sonst hängt die Bin `in_transit` an niemandem
    mehr und spätere Return-Pickups laufen in
    `RuntimeError: Event exceeded max retries`.
    """
    engine = _build_engine(num_robots=2)
    handler = engine.event_handler

    victim, waiting = engine.state.robots

    # Opfer in eine Ecke stellen, aus der es nicht ausweichen kann
    victim.set_position((0, 0))
    waiting.set_position((1, 0))
    carried = _take_bin_into_transit(engine, (2, 2))
    victim.set_carried_bin(carried.bin_id)

    task = object()  # Platzhalter genügt: es darf gar nicht erst requeued werden
    victim.current_task = task

    with contextlib.redirect_stdout(io.StringIO()):
        resolved = handler._resolve_move_deadlock(
            victim=victim,
            contested_cell=(0, 1),
            waiting_robot=waiting,
        )
        # Alle Nachbarzellen verbieten → Ausweichen unmöglich
        blocked = handler._evade_robot(
            victim, forbidden_cells={(0, 1), (1, 0), (-1, 0), (0, -1)}
        )

    assert not blocked, "Testaufbau: Ausweichen sollte hier unmöglich sein."
    assert victim.current_task is task, (
        "Tragender Roboter wurde trotz getragener Bin requeued."
    )
    assert victim.is_carrying_bin()
    assert task not in engine.active_queue.waiting_tasks


def test_carried_bin_link_is_set_on_pickup_and_cleared_on_drop():
    """
    Die Roboter→Bin-Verknüpfung muss dem physischen Zustand folgen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    source_stack = engine.state.grid.get_stack(3, 3)
    if source_stack is None or source_stack.height() == 0:
        source_stack = _find_non_empty_stack(engine)
    top_bin = source_stack.peek()
    # Der Roboter muss physisch am Quellstack stehen (Pickup-Positions-Guard).
    robot.set_position(_position_of(source_stack))

    # LIVENESS (2026-08-22): Ein Pickup gehört immer zu einem Task. Ein
    # Pickup-Event eines Roboters OHNE Task ist seit dieser Änderung verwaist
    # und wird verworfen – im Produktivlauf war genau das die Ursache dafür,
    # dass ein Roboter eine fremde Bin aufnahm und die Portzelle blockierte.
    # Die Fixture stellt die reale Vorbedingung deshalb explizit her.
    from events.event_types import EventType as _EvT
    from requests_.request import Request as _Req
    from simulation.robot_task import RobotTask

    robot.assign_task(RobotTask(_Req(
        request_id=9401, event_type=_EvT.ARRIVAL, bin_id=top_bin.bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )))

    assert not robot.is_carrying_bin()

    pickup_action = {
        "type": "relocate",
        "from_stack": source_stack.stack_id,
        "to_stack": "S_1_1",
        "bin_id": top_bin.bin_id,
    }
    pickup_event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=pickup_action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(pickup_event)

    assert robot.get_carried_bin() == top_bin.bin_id, (
        "Verknüpfung wurde beim Pickup nicht gesetzt."
    )

    # Drop am korrekten Ziel
    robot.set_position((1, 1))
    drop_event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=pickup_action, request=None, time=engine.state.t
    )
    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(drop_event)

    assert not robot.is_carrying_bin(), (
        "Verknüpfung wurde beim Drop nicht gelöscht."
    )


@pytest.mark.parametrize("num_robots,util,seed", [
    (2, 0.5, 42),
    (3, 2.0, 42),
    (4, 2.0, 7),
    (3, 0.5, 99),
])
def test_no_orphaned_in_transit_bins_during_full_run(num_robots, util, seed):
    """
    Systeminvariante: Jede Bin im Transit muss genau einem Roboter zugeordnet
    sein, und jeder tragende Roboter muss eine existierende Transit-Bin haben.
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = num_robots
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    engine = SimulationEngine(config)

    violations = []

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

            carried_ids = [
                r.get_carried_bin()
                for r in engine.state.robots
                if r.is_carrying_bin()
            ]

            # Keine Bin darf von zwei Robotern gleichzeitig getragen werden
            if len(carried_ids) != len(set(carried_ids)):
                violations.append((engine.state.t, "doppelt getragen", carried_ids))

            for bin_id in carried_ids:
                bin_obj = engine.state.get_bin_by_id(bin_id)
                if bin_obj is None:
                    violations.append((engine.state.t, "Bin fehlt", bin_id))
                    continue
                # Getragene Bin darf nicht zusätzlich in einem Stack liegen
                in_stack = any(
                    bin_obj in s.bins for s in engine.state.grid.all_stacks()
                )
                if in_stack:
                    violations.append(
                        (engine.state.t, "getragen UND im Stack", bin_id)
                    )

    assert not violations, f"Erste 5 Verletzungen: {violations[:5]}"


# ======================================================================
# 3b. Duplikat-Events (Pickup/Drop)
# ======================================================================

def test_duplicate_pickup_for_already_carried_bin_continues_with_drop():
    """
    Trägt der Roboter die Ziel-Bin bereits, ist das Pickup-Event ein Duplikat.
    Es darf nicht endlos scheitern ("not on top"), sondern muss in die
    Drop-Phase übergehen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((3, 3))
    carried = _take_bin_into_transit(engine, (3, 3))
    robot.set_carried_bin(carried.bin_id)

    action = {
        "type": "relocate",
        "from_stack": "S_3_3",
        "to_stack": "S_1_1",
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )

    drops_before = sum(
        1 for e in engine.state.event_queue.queue
        if e.event_type == EventType.ROBOT_DROP
    )

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        handler._handle_robot_pickup(event)

    assert "[STALE][PICKUP]" in buf.getvalue()
    drops_after = sum(
        1 for e in engine.state.event_queue.queue
        if e.event_type == EventType.ROBOT_DROP
    )
    assert drops_after > drops_before, (
        "Kein Drop-Event nach dem Duplikat-Pickup eingeplant."
    )
    # Bin bleibt unverändert in der Hand
    assert carried.in_transit
    assert robot.get_carried_bin() == carried.bin_id


def test_duplicate_drop_for_other_bin_is_skipped():
    """
    Ein Roboter kann nur EINE Bin tragen. Ein Drop-Event für eine andere Bin
    gehört zu einem abgeschlossenen Vorgang und darf den State nicht ändern.

    Beobachtet vor dem Guard: zwei `DROP_TARGET`-Events desselben Roboters im
    selben Zeitschritt → `RuntimeError: Cannot start pickstation service:
    robot has no task`.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    robot.set_position((2, 2))

    carried = _take_bin_into_transit(engine, (3, 3))
    orphan = _take_bin_into_transit(engine, (2, 3))
    robot.set_carried_bin(carried.bin_id)

    target_stack = engine.state.grid.get_stack(2, 2)
    height_before = target_stack.height()

    stale_action = {
        "type": "relocate",
        "from_stack": "S_2_3",
        "to_stack": target_stack.stack_id,
        "bin_id": orphan.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=stale_action, request=None, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        handler._handle_robot_drop(event)

    assert "[STALE][DROP]" in buf.getvalue()
    assert target_stack.height() == height_before, (
        "Stale Drop-Event hat eine fremde Bin abgelegt."
    )
    assert orphan.in_transit
    assert robot.get_carried_bin() == carried.bin_id


# ======================================================================
# 4. Ausweichen nahe Port / Sackgasse
# ======================================================================

def test_evade_never_moves_a_robot_onto_a_port_cell():
    """
    `_evade_robot` meidet Port-Zellen (eigene Reservierungs-/Anwesenheits-
    buchhaltung). Ein Roboter direkt neben dem Port darf nicht dorthin
    ausweichen.
    """
    engine = _build_engine()
    handler = engine.event_handler
    pickstation = engine.state.get_all_pickstations()[0]
    px, py = pickstation.position

    robot = engine.state.robots[0]
    neighbour = (px + 1, py)
    robot.set_position(neighbour)

    with contextlib.redirect_stdout(io.StringIO()):
        handler._evade_robot(robot, forbidden_cells=set())

    if robot.planned_path:
        assert robot.planned_path[0] != pickstation.position, (
            "Ausweichen führte auf die Port-Zelle."
        )
    assert pickstation.robot_on_port is None


def test_requeue_path_leaves_consistent_state_when_evade_impossible():
    """
    Sackgasse: Ist kein Ausweichen möglich und trägt der Roboter nichts,
    muss der Requeue-Pfad einen konsistenten Zustand hinterlassen –
    Task genau einmal wartend, Roboter ohne Task, keine Doppelbuchung.
    """
    engine = _build_engine()
    handler = engine.event_handler

    from events.event_types import EventType as _ET
    from requests_.request import Request
    from simulation.robot_task import RobotTask

    victim, waiting = engine.state.robots
    victim.set_position((0, 0))
    waiting.set_position((1, 0))

    task = RobotTask(Request(
        request_id=9101, event_type=_ET.ARRIVAL, bin_id=3,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))
    victim.assign_task(task)
    engine.active_queue.mark_task_assigned(task, victim)

    with contextlib.redirect_stdout(io.StringIO()):
        resolved = handler._resolve_move_deadlock(
            victim=victim,
            contested_cell=(0, 1),
            waiting_robot=waiting,
        )

    assert resolved, "Requeue-Pfad hat den Konflikt nicht behandelt."
    assert victim.current_task is None
    assert not victim.is_carrying_bin()

    waiting_ids = [t.request_id for t in engine.active_queue.waiting_tasks]
    assert waiting_ids.count(task.request_id) == 1, (
        f"Task nicht genau einmal wartend: {waiting_ids}"
    )
    assert task.request_id not in engine.active_queue.assigned, (
        "Task gilt weiterhin als zugewiesen (Invariante aus Fix 2 verletzt)."
    )


# ======================================================================
# 5. Systemweite Invariante
# ======================================================================

@pytest.mark.parametrize("num_robots,util,seed", [
    (2, 0.5, 42),
    (3, 2.0, 42),
    (4, 2.0, 7),
])
def test_no_physically_impossible_drop_during_full_run(num_robots, util, seed):
    """
    Systemlauf: Kein erfolgreicher Drop darf aus einer Position erfolgen, die
    nicht der Ablageposition der Aktion entspricht.
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = num_robots
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    engine = SimulationEngine(config)

    handler = engine.event_handler
    violations = []

    original_drop = handler._handle_robot_drop

    def checked_drop(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action")
        stack_heights_before = {
            s.stack_id: s.height() for s in engine.state.grid.all_stacks()
        }
        status_before = {
            b.bin_id: (b.get_status(), b.in_transit) for b in engine.state.bins
        }
        original_drop(event)
        changed = any(
            s.height() != stack_heights_before[s.stack_id]
            for s in engine.state.grid.all_stacks()
        ) or any(
            (b.get_status(), b.in_transit) != status_before[b.bin_id]
            for b in engine.state.bins
        )
        if changed:
            target = handler._get_drop_position_for_action(action)
            if target is not None and robot is not None:
                if robot.get_position() != target:
                    violations.append(
                        (engine.state.t, robot.robot_id,
                         robot.get_position(), target, action.get("type"))
                    )

    handler._handle_robot_drop = checked_drop

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

    assert not violations, (
        f"{len(violations)} Drop(s) aus falscher Position, "
        f"erste 5: {violations[:5]}"
    )
