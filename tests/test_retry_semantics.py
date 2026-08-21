# tests/test_retry_semantics.py
"""
Semantik der Retry-Persistenz über Replan-Grenzen (Hardening, Baseline 58c5ef2).

Regel:
    Retry-Fortschritt bleibt NUR erhalten, wenn es sich fachlich weiterhin um
    denselben fehlgeschlagenen Versuch handelt.

    Gleicher Versuch  = gleiche Aktionsart, gleiche Bin, gleiche Quelle,
                        gleiches Ziel, kein Zustandsfortschritt.
    Neuer Versuch     = Ziel gewechselt, andere Bin, andere Aktionsart,
                        Phasenwechsel, echter Fortschritt.

Ohne Persistenz sind die Eskalationsschwellen strukturell unerreichbar
(Seed-1-Endlosschleife: 457 identische Wiederholungen, 0 Requeues).
Mit blinder Persistenz würde eine echte neue Recovery mit fast erschöpftem
Budget starten (z.B. Drop-Redirect auf einen anderen Stack).
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.event_handler import EventHandler
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


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


def _build_engine(num_robots=2):
    config = SimulationConfig()
    config.grid_width = 6
    config.grid_depth = 6
    config.max_stack_height = 4
    config.bin_num = 40
    config.num_robots = num_robots
    config.simulation_time = 200
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


# ======================================================================
# 1. Die Regel selbst
# ======================================================================

def test_identical_action_counts_as_same_attempt():
    action = {
        "type": "return", "return_kind": "blocker",
        "bin_id": 90, "from_stack": "S_4_6", "to_stack": "S_5_6",
    }
    assert EventHandler._is_same_attempt(action, dict(action))


@pytest.mark.parametrize("changed_key,new_value", [
    ("to_stack", "S_1_1"),      # Recovery wählt anderen Ziel-Stack
    ("from_stack", "S_2_2"),    # andere Quelle
    ("bin_id", 91),             # andere Bin
    ("type", "relocate"),       # andere Aktionsart
    ("return_kind", "target"),  # anderer fachlicher Kontext
])
def test_changed_action_is_a_new_attempt(changed_key, new_value):
    """
    Sobald sich das tatsächliche Vorhaben ändert, muss das Retry-Budget
    neu beginnen.
    """
    old_action = {
        "type": "return", "return_kind": "blocker",
        "bin_id": 90, "from_stack": "S_4_6", "to_stack": "S_5_6",
    }
    new_action = dict(old_action)
    new_action[changed_key] = new_value

    assert not EventHandler._is_same_attempt(old_action, new_action), (
        f"Änderung von '{changed_key}' hätte als neuer Versuch gelten müssen."
    )


def test_missing_action_is_never_the_same_attempt():
    action = {"type": "relocate", "bin_id": 1}
    assert not EventHandler._is_same_attempt(None, action)
    assert not EventHandler._is_same_attempt(action, None)


# ======================================================================
# 2. Gleicher Versuch → Schwelle wird erreichbar
# ======================================================================

def test_repeated_identical_action_reaches_requeue_threshold():
    """
    Wiederholt die Strategie dieselbe unerfüllbare Aktion, muss der
    Retry-Zähler wachsen und die Requeue-Eskalation tatsächlich auslösen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]

    request = Request(
        request_id=8001, event_type=EventType.ARRIVAL, bin_id=1,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )
    task = RobotTask(request)
    task.phase = RobotTask.PHASE_RESTORE_BLOCKERS
    task.pickstation_completed = True
    robot.assign_task(task)

    # Blocker im Buffer, dauerhaft verschüttet → Pickup nie möglich
    buffer_stack = engine.state.grid.get_stack(2, 2)
    while buffer_stack.height() < 2:
        for other in engine.state.grid.all_stacks():
            if other is buffer_stack or other.height() == 0:
                continue
            buffer_stack.push(other.pop())
            handler._sync_stack_bin_metadata(other)
            handler._sync_stack_bin_metadata(buffer_stack)
            break

    buried = buffer_stack.bins[-2]
    task.remember_relocation(
        bin_id=buried.bin_id, from_stack="S_1_1",
        buffer_stack=buffer_stack.stack_id,
    )
    robot.set_position((2, 2))

    action = {
        "type": "return", "return_kind": "blocker",
        "from_stack": buffer_stack.stack_id, "to_stack": "S_1_1",
        "bin_id": buried.bin_id,
    }

    seen_retries = []
    requeued = False

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        event = handler.event_builder.build_robot_pickup_event(
            robot=robot, action=action, request=request, time=engine.state.t
        )
        for _ in range(handler.max_repeated_action_retries_before_requeue + 5):
            handler._handle_robot_pickup(event)
            # nachfolgendes Pickup-Event aus der Queue holen
            follow_up = [
                e for e in engine.state.event_queue.queue
                if e.event_type == EventType.ROBOT_PICKUP
            ]
            if not follow_up:
                break
            event = follow_up[-1]
            engine.state.event_queue.queue.remove(event)
            seen_retries.append(event.retry_count)
            if robot.current_task is None:
                requeued = True
                break

    assert seen_retries, "Kein Folge-Pickup-Event erzeugt."
    assert max(seen_retries) > 1, (
        f"Retry-Zähler blieb stehen: {seen_retries} – Eskalationsschwelle "
        f"strukturell unerreichbar."
    )
    assert requeued or "[REQUEUE][PICKUP_REPEAT]" in buf.getvalue(), (
        f"Requeue-Eskalation nie erreicht (Zähler: {seen_retries})."
    )


def test_pickup_position_replan_keeps_retry_budget():
    """
    `[REPLAN][PICKUP_POS]` plant dieselbe Aktion erneut – der Zähler darf
    nicht auf 0 zurückfallen.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    request = Request(
        request_id=8002, event_type=EventType.ARRIVAL, bin_id=1,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )
    task = RobotTask(request)
    robot.assign_task(task)

    source_stack = engine.state.grid.get_stack(3, 3)
    if source_stack is None or source_stack.height() == 0:
        source_stack = _find_non_empty_stack(engine)
    top_bin = source_stack.peek()
    robot.set_position((0, 0))  # nicht am Stack

    action = {
        "type": "relocate",
        "from_stack": source_stack.stack_id,
        "to_stack": "S_1_1",
        "bin_id": top_bin.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=request, time=engine.state.t
    )
    event.retry_count = handler.max_pickup_position_retries_before_replan

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    follow_up = [
        e for e in engine.state.event_queue.queue
        if e.event_type == EventType.ROBOT_PICKUP
    ]
    assert follow_up, "Kein neues Pickup-Event nach dem Replan."
    assert follow_up[-1].retry_count >= event.retry_count, (
        f"Retry-Budget ging beim Positions-Replan verloren "
        f"({follow_up[-1].retry_count} < {event.retry_count})."
    )


# ======================================================================
# 3. Neuer Versuch → Budget wird zurückgesetzt
# ======================================================================

def test_drop_redirect_to_other_stack_starts_a_fresh_attempt():
    """
    Wählt die Drop-Recovery einen ANDEREN Ziel-Stack, ist das ein neuer
    sinnvoller Versuch. Er darf nicht mit fast erschöpftem Budget starten.
    """
    engine = _build_engine()
    handler = engine.event_handler
    max_height = engine.config.max_stack_height

    full_stack = engine.state.grid.get_stack(2, 2)
    for bin_obj in list(engine.state.bins):
        if full_stack.height() >= max_height:
            break
        if bin_obj.get_stack() is None:
            continue
        src = engine.state.grid.get_stack(*bin_obj.get_stack())
        if src is None or src is full_stack or src.peek() is not bin_obj:
            continue
        src.pop()
        full_stack.push(bin_obj)
        handler._sync_stack_bin_metadata(src)
        handler._sync_stack_bin_metadata(full_stack)

    robot = engine.state.robots[0]
    robot.set_position((2, 2))

    carried_src = engine.state.grid.get_stack(5, 5)
    if carried_src is None or carried_src.height() == 0:
        carried_src = _find_non_empty_stack(engine)
    carried = carried_src.peek()
    carried_src.pop()
    handler._sync_stack_bin_metadata(carried_src)
    carried.mark_in_transit()
    carried.set_stack(None)
    carried.set_level(None)
    robot.set_carried_bin(carried.bin_id)

    action = {
        "type": "relocate",
        "from_stack": "S_4_4",
        "to_stack": full_stack.stack_id,
        "bin_id": carried.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )
    event.retry_count = handler.max_drop_retries_before_redirect

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert action["to_stack"] != full_stack.stack_id, (
        "Testaufbau: Redirect hätte greifen müssen."
    )

    new_drops = [
        e for e in engine.state.event_queue.queue
        if e.event_type == EventType.ROBOT_DROP
    ]
    assert new_drops, "Kein neues Drop-Event nach dem Redirect."
    assert all(e.retry_count == 0 for e in new_drops), (
        f"Neuer Ziel-Stack, aber altes Retry-Budget übernommen: "
        f"{[e.retry_count for e in new_drops]}"
    )


def test_moving_robot_resets_drop_position_retry_budget():
    """
    Bewegt sich ein Roboter Richtung Ablageziel, ist das echter Fortschritt –
    kein fehlgeschlagener Versuch. Das Budget muss zurückgesetzt werden.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    carried_src = engine.state.grid.get_stack(5, 5)
    if carried_src is None or carried_src.height() == 0:
        carried_src = _find_non_empty_stack(engine)
    carried = carried_src.peek()
    carried_src.pop()
    handler._sync_stack_bin_metadata(carried_src)
    carried.mark_in_transit()
    carried.set_stack(None)
    carried.set_level(None)
    robot.set_carried_bin(carried.bin_id)

    action = {
        "type": "relocate",
        "from_stack": "S_4_4",
        "to_stack": "S_1_1",
        "bin_id": carried.bin_id,
    }

    # Erste Prüfung an Position A
    robot.set_position((5, 5))
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )
    event.retry_count = 3
    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_drop_position_mismatch(event, robot, action)

    # Zweite Prüfung nach echter Bewegung
    robot.set_position((4, 5))
    event2 = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )
    event2.retry_count = 4
    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_drop_position_mismatch(event2, robot, action)

    assert event2.retry_count == 0, (
        "Retry-Budget wurde trotz Bewegungsfortschritt nicht zurückgesetzt."
    )


def test_task_phase_change_does_not_carry_retry_budget():
    """
    Nach einem Phasenwechsel liefert die Strategie eine andere Aktion –
    `_is_same_attempt` muss das als neuen Versuch erkennen.
    """
    retrieve_action = {
        "type": "remove_target", "return_kind": None,
        "bin_id": 5, "from_stack": "S_2_2", "to_stack": None,
    }
    restore_action = {
        "type": "return", "return_kind": "blocker",
        "bin_id": 7, "from_stack": "S_3_3", "to_stack": "S_2_2",
    }

    assert not EventHandler._is_same_attempt(retrieve_action, restore_action)
