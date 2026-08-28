# tests/test_blocker_target_ownership.py
"""
Contract zwischen Target-Reservation und Blocker-Ownership
(Phase 2B, AUDIT-003).

Ausgangsbefund:
Eine Bin kann gleichzeitig
  - Target eines aktiven Tasks A sein und
  - von Task B als Blocker in dessen `temp_storage` geführt werden.
Verarbeitet Task A die Bin regulär (Pickstation, Rücklagerung), bleibt der
Restore-Eintrag in Task B dauerhaft offen. Task B kann nie abschließen
(`has_blockers_to_restore()` bleibt für immer True) und bindet einen Roboter.

Fachlicher Contract (Phase 2B):

    C-1  Eine Blocker-Restore-Verpflichtung besteht nur so lange, wie die Bin
         wegen dieses Tasks im Buffer-Stack liegt.

    C-2  Nimmt ein ANDERER Task die Bin regulär aus dem Buffer (weil sie sein
         Target ist), ist die Restore-Verpflichtung gegenstandslos. Sie muss
         genau dann aufgelöst werden – Eintrag aus `temp_storage` und globale
         Ownership.

    C-3  Danach darf die Bin nicht erneut als offener Restore-Schritt geführt
         oder als Return-Aktion gewählt werden.

    C-4  Der Blocker-Task muss anschließend normal weiterlaufen können.

Bewusst NICHT gewählt: ein globales Verbot „Target-Bin darf nie Blocker sein".
Blocker ergeben sich physisch aus dem, was auf dem Zielstapel liegt; ein
solches Verbot wäre nicht erfüllbar, ohne Retrievals zu blockieren.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


def _engine(robots=2, pickstations=1, seed=42):
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 60
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = 500
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    return SimulationEngine(config)


def _task(request_id, bin_id):
    return RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))


def _find_non_empty_stack(engine):
    for stack in engine.state.grid.all_stacks():
        if stack.height() > 0:
            return stack
    raise AssertionError("kein gefüllter Stack")


# ======================================================================
# C-2 / C-3 – Übernahme durch den Target-Task
# ======================================================================

def test_blocker_obligation_is_released_when_target_task_takes_the_bin():
    """
    Kernregression AUDIT-003.

    Bin liegt als Blocker von Task A im Buffer. Task B nimmt sie als Target
    auf → Task A darf sie danach nicht mehr als offenen Restore führen.
    """
    engine = _engine(robots=2)
    handler = engine.event_handler
    queue = engine.active_queue

    buffer_stack = _find_non_empty_stack(engine)
    blocker_bin = buffer_stack.peek()

    # Task A führt die Bin als Blocker
    task_a = _task(1001, bin_id=999)
    task_a.remember_relocation(
        bin_id=blocker_bin.bin_id,
        from_stack="S_1_1",
        buffer_stack=buffer_stack.stack_id,
    )
    queue.register_blocker_ownership(blocker_bin.bin_id, task_a)
    engine.state.robots[1].assign_task(task_a)

    assert task_a.has_blockers_to_restore()
    assert queue.get_blocker_owner(blocker_bin.bin_id) is task_a

    # Task B nimmt dieselbe Bin als Target auf
    robot_b = engine.state.robots[0]
    task_b = _task(1002, bin_id=blocker_bin.bin_id)
    robot_b.assign_task(task_b)
    robot_b.set_position(engine.event_handler._parse_stack_position(buffer_stack))

    action = {
        "type": "remove_target",
        "from_stack": buffer_stack.stack_id,
        "bin_id": blocker_bin.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot_b, action=action, request=task_b.request,
        time=engine.state.t,
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot_b.get_carried_bin() == blocker_bin.bin_id, (
        "Testaufbau: Pickup hätte gelingen müssen"
    )
    assert not any(
        reloc["bin_id"] == blocker_bin.bin_id for reloc in task_a.temp_storage
    ), (
        "C-2 verletzt: Task A führt die Bin weiterhin als offenen "
        "Restore-Schritt, obwohl Task B sie übernommen hat."
    )
    assert queue.get_blocker_owner(blocker_bin.bin_id) is None, (
        "C-2 verletzt: Blocker-Ownership wurde nicht freigegeben."
    )


def test_own_blocker_restore_keeps_obligation_until_drop():
    """
    Gegenprobe: Nimmt der EIGENE Task seinen Blocker auf, um ihn
    zurückzulagern, bleibt der Eintrag bis zum erfolgreichen Drop bestehen.
    """
    engine = _engine(robots=1)
    handler = engine.event_handler
    queue = engine.active_queue

    buffer_stack = _find_non_empty_stack(engine)
    blocker_bin = buffer_stack.peek()

    task = _task(1010, bin_id=555)
    task.remember_relocation(
        bin_id=blocker_bin.bin_id,
        from_stack="S_1_1",
        buffer_stack=buffer_stack.stack_id,
    )
    queue.register_blocker_ownership(blocker_bin.bin_id, task)

    robot = engine.state.robots[0]
    robot.assign_task(task)
    robot.set_position(handler._parse_stack_position(buffer_stack))

    action = {
        "type": "return",
        "return_kind": "blocker",
        "from_stack": buffer_stack.stack_id,
        "to_stack": "S_1_1",
        "bin_id": blocker_bin.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=task.request, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert any(
        reloc["bin_id"] == blocker_bin.bin_id for reloc in task.temp_storage
    ), "Eigener Restore-Eintrag wurde vorzeitig entfernt."


# ======================================================================
# C-1 / C-4 – Systemlauf
# ======================================================================

def _stale_restore_entries(engine):
    """temp_storage-Einträge, deren Bin nicht (mehr) im Buffer liegt."""
    tasks = {}
    for task in engine.active_queue.waiting_tasks:
        tasks[id(task)] = task
    for task in engine.active_queue.pickstation_tasks.values():
        tasks[id(task)] = task
    for robot in engine.state.robots:
        if robot.current_task is not None:
            tasks[id(robot.current_task)] = robot.current_task

    stale = []
    for task in tasks.values():
        for reloc in task.temp_storage:
            bin_obj = engine.state.get_bin_by_id(reloc["bin_id"])
            if bin_obj is None or getattr(bin_obj, "in_transit", False):
                continue
            buffer_pos = engine.event_handler._resolve_position(
                reloc["buffer_stack"]
            )
            if bin_obj.get_stack() != buffer_pos:
                stale.append(
                    (engine.state.t, task.request_id, reloc["bin_id"],
                     bin_obj.get_stack(), buffer_pos)
                )
    return stale


@pytest.mark.parametrize("robots,pickstations,util,seed", [
    (4, 1, 0.5, 42),   # exaktes AUDIT-003-Szenario
    (4, 2, 2.0, 42),
    (3, 2, 0.5, 99),
    (2, 1, 2.0, 1),
])
def test_no_permanently_stale_restore_entries(robots, pickstations, util, seed):
    """
    Ein Restore-Eintrag darf nicht dauerhaft offen bleiben, wenn die Bin
    den Buffer verlassen hat.

    Kurzzeitige Abweichungen sind zulässig (Transportzustände); dauerhaft
    offen sind sie nicht.
    """
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

    first_seen = {}
    persistent = []

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            current = {(x[1], x[2]) for x in _stale_restore_entries(engine)}
            for key in current:
                first_seen.setdefault(key, engine.state.t)
                if engine.state.t - first_seen[key] > 60:
                    persistent.append((key, first_seen[key], engine.state.t))
            for key in list(first_seen):
                if key not in current:
                    first_seen.pop(key, None)
            if persistent:
                break

    assert not persistent, (
        f"Dauerhaft offene Restore-Einträge: {persistent[:3]}"
    )


def test_audit003_scenario_completes_requests():
    """
    C-4: Das konkrete AUDIT-003-Szenario läuft weiter und schließt Requests ab.
    """
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = 4
    config.num_pickstations = 1
    config.simulation_time = 500
    config.random_seed = 42
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = "ORIGINAL"
    engine = SimulationEngine(config)

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

    completed = engine.metrics.summary().get("requests_completed", 0) or 0
    assert completed > 20, f"Zu wenig Fortschritt: {completed}"
    assert not _stale_restore_entries(engine), (
        "Am Laufende bestehen offene Restore-Einträge für Bins, die den "
        "Buffer längst verlassen haben."
    )
