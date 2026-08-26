# tests/test_blocker_return_invariant.py
"""
Regression für die Seed-1-`PICKUP_RETURN`-Endlosschleife (Hardening, 58c5ef2).

Beobachteter Ablauf (Seed 1, util 2.0, 2 Robots):

    Robot 0, Phase restore_blockers
    next_action → return blocker bin=90 (aus Buffer S_4_6 nach S_5_6)
    _can_pickup → "expected bin 90 not on top"
    [REPLAN][PICKUP_RETURN] "already stored -> re-evaluating next action"
    → neues Pickup-Event, retry_count = 0
    → next_action liefert exakt dieselbe Aktion
    → 457 identische Wiederholungen

KORREKTUR DER BISHERIGEN HYPOTHESE:
Die frühere Dokumentation nahm an, `temp_storage` enthalte eine bereits
zurückgelagerte Bin (fehlende `mark_last_relocation_restored`-Transition).
Das ist **falsch**. Bin 90 lag noch im Buffer-Stack und war korrekt in
`temp_storage` geführt – sie war nur von einer Blocker-Bin eines ANDEREN
Tasks überdeckt.

Tatsächliche Root Cause: Die Abkürzung „Bin ist bereits `stored` → Aktion
erledigt" galt für ALLE Return-Aktionen. Für Blocker-Returns ist `stored`
jedoch der Normalzustand (die Bin liegt planmäßig im Buffer-Stack).
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


def _build_engine(num_robots=2, seed=1, util=2.0, sim_time=500):
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 100
    config.num_robots = num_robots
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    return SimulationEngine(config)


# ======================================================================
# 1. Semantik: "stored" ist für Blocker der Normalzustand
# ======================================================================

def test_stored_blocker_is_not_treated_as_already_restored():
    """
    Ein Blocker-Return darf NICHT über die „already stored"-Abkürzung
    abgewickelt werden. Sonst wird dieselbe Aktion endlos neu erzeugt.
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]

    request = Request(
        request_id=7001, event_type=EventType.ARRIVAL, bin_id=1,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )
    task = RobotTask(request)
    task.phase = RobotTask.PHASE_RESTORE_BLOCKERS
    task.pickstation_completed = True
    robot.assign_task(task)

    # Blocker liegt im Buffer-Stack, aber NICHT obenauf
    buffer_stack = engine.state.grid.get_stack(4, 6)
    while buffer_stack.height() < 2:
        for other in engine.state.grid.all_stacks():
            if other is buffer_stack or other.height() == 0:
                continue
            moved = other.pop()
            buffer_stack.push(moved)
            handler._sync_stack_bin_metadata(other)
            handler._sync_stack_bin_metadata(buffer_stack)
            break

    buried = buffer_stack.bins[-2]
    assert buried.get_status() == "stored"
    assert buffer_stack.peek() is not buried

    task.remember_relocation(
        bin_id=buried.bin_id, from_stack="S_5_6", buffer_stack=buffer_stack.stack_id
    )

    action = {
        "type": "return",
        "return_kind": "blocker",
        "from_stack": buffer_stack.stack_id,
        "to_stack": "S_5_6",
        "bin_id": buried.bin_id,
    }
    robot.set_position((4, 6))

    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=request, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        handler._handle_robot_pickup(event)

    output = buf.getvalue()
    assert "[REPLAN][PICKUP_RETURN]" not in output, (
        "Blocker-Return wurde fälschlich als 'already stored' abgekürzt."
    )
    # Die Bin muss weiterhin als offener Restore-Schritt geführt werden
    assert any(
        reloc["bin_id"] == buried.bin_id for reloc in task.temp_storage
    )


def test_target_return_still_uses_already_stored_shortcut():
    """
    Gegenprobe: Für Target-Returns bleibt die Abkürzung erhalten – dort
    bedeutet `stored` tatsächlich „bereits zurückgelegt".
    """
    engine = _build_engine()
    handler = engine.event_handler

    robot = engine.state.robots[0]
    stack = engine.state.grid.get_stack(3, 3)
    target_bin = stack.bins[0]

    request = Request(
        request_id=7002, event_type=EventType.ARRIVAL, bin_id=target_bin.bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )
    task = RobotTask(request)
    task.phase = RobotTask.PHASE_RETURN_TARGET
    task.target_stack_id = stack.stack_id
    task.pickstation_completed = True
    task.target_removed = True
    task.target_at_pickstation = True
    robot.assign_task(task)

    action = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": stack.stack_id,
        "bin_id": target_bin.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=action, request=request, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        handler._handle_robot_pickup(event)

    assert "[REPLAN][PICKUP_RETURN]" in buf.getvalue(), (
        "Abkürzung für Target-Returns wurde versehentlich mit entfernt."
    )


# ======================================================================
# 2. temp_storage-Invariante
# ======================================================================

def _temp_storage_violations(engine):
    """
    `temp_storage` darf nur Blocker enthalten, deren Restore noch offen ist.

    Geprüft wird:
    - keine Bin doppelt in temp_storage eines Tasks
    - eine geführte Blocker-Bin liegt entweder im Buffer-Stack oder wird
      gerade transportiert – sie darf nicht bereits auf ihrem Ziel-Stack liegen
    """
    violations = []
    tasks = set()

    for task in engine.active_queue.waiting_tasks:
        tasks.add(task)
    for task in engine.active_queue.pickstation_tasks.values():
        tasks.add(task)
    for robot in engine.state.robots:
        if robot.current_task is not None:
            tasks.add(robot.current_task)

    for task in tasks:
        ids = [reloc["bin_id"] for reloc in task.temp_storage]
        if len(ids) != len(set(ids)):
            violations.append((engine.state.t, task.request_id, "Duplikat", ids))

        for reloc in task.temp_storage:
            bin_obj = engine.state.get_bin_by_id(reloc["bin_id"])
            if bin_obj is None:
                violations.append(
                    (engine.state.t, task.request_id, "Bin fehlt", reloc["bin_id"])
                )
                continue
            if getattr(bin_obj, "in_transit", False):
                continue
            buffer_pos = engine.event_handler._resolve_position(reloc["buffer_stack"])
            if bin_obj.get_stack() != buffer_pos:
                violations.append((
                    engine.state.t, task.request_id, "nicht im Buffer",
                    reloc["bin_id"], bin_obj.get_stack(), buffer_pos,
                ))

    return violations


@pytest.mark.parametrize("num_robots,seed,util", [
    (2, 1, 2.0),
    (3, 1, 2.0),
    (2, 42, 0.5),
    (3, 99, 0.5),
])
def test_temp_storage_only_holds_open_restores(num_robots, seed, util):
    """
    Systemlauf: Ein erfolgreich zurückgelagerter Blocker darf nicht weiter als
    offener Restore-Schritt geführt werden.
    """
    engine = _build_engine(num_robots=num_robots, seed=seed, util=util)
    all_violations = []

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            all_violations.extend(_temp_storage_violations(engine))
            if all_violations:
                break

    assert not all_violations, f"Erste Verletzungen: {all_violations[:3]}"


# ======================================================================
# 3. Seed-1-Regression: kein endloses Wiederholen, echter Fortschritt
# ======================================================================

def test_seed1_does_not_repeat_the_same_return_action_endlessly():
    """
    Kernregression. Vor dem Fix: 457 identische
    `[REPLAN][PICKUP_RETURN]`-Wiederholungen und 1 abgeschlossener Request.
    """
    engine = _build_engine(num_robots=2, seed=1, util=2.0)

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        while True:
            if engine.step() is None:
                break

    output = buf.getvalue()
    pickup_return_replans = output.count("[REPLAN][PICKUP_RETURN]")
    completed = engine.metrics.summary().get("requests_completed", 0) or 0

    assert pickup_return_replans < 50, (
        f"`[REPLAN][PICKUP_RETURN]` wurde {pickup_return_replans}x ausgelöst – "
        f"die Endlosschleife besteht fort."
    )
    assert completed >= 10, (
        f"Zu wenig fachlicher Fortschritt: nur {completed} abgeschlossene "
        f"Requests (vor dem Fix: 1)."
    )


@pytest.mark.parametrize("num_robots", [2, 3, 4])
def test_seed1_makes_real_progress(num_robots):
    """
    Seed 1 muss in allen geprüften Roboterzahlen echten Fortschritt machen.
    Vor dem Fix: 1 / 28 / 38 Completions bei bis zu 449 ZE Stillstand.
    """
    engine = _build_engine(num_robots=num_robots, seed=1, util=2.0)

    completed_at = []
    last = 0

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            current = engine.metrics.summary().get("requests_completed", 0) or 0
            if current > last:
                last = current
                completed_at.append(engine.state.t)

    assert last > 0, "Kein einziger Request abgeschlossen."

    gaps = [b - a for a, b in zip(completed_at, completed_at[1:])]
    longest = max(gaps) if gaps else engine.state.t
    assert longest <= 150, (
        f"Längste Phase ohne Completion: {longest} ZE "
        f"(completions={last})"
    )
