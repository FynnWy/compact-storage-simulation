# tests/test_task_assignment_invariant.py
"""
Invarianten-Tests gegen Task-Doppelvergabe (Fix 2, 2026-08-19).

Zentrale Invariante:

    Ein Task darf zu einem Zeitpunkt nicht gleichzeitig als wartend
    (`ActiveQueue.waiting_tasks`) und als zugewiesen (`ActiveQueue.assigned`)
    gelten.

    Ein Task darf nicht gleichzeitig mehreren Robotern zugewiesen sein.

Befund (ARCHITEKTUR_KARTE.md 9.1): `mark_task_assigned` entfernte den Task
nicht aus `waiting_tasks`. Über `_handle_pickstation_complete` landete
derselbe Task damit gleichzeitig in `waiting_tasks` und in `assigned`; der
nächste Scheduler-Lauf bot ihn einem zweiten Roboter erneut an.

Diese Tests prüfen die Container-/Scheduling-Invariante direkt, nicht erst
die Spätfolge ("duplicate bin detected").
"""

import io
import contextlib

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.active_queue import ActiveQueue
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine
from state.robot import Robot


def _make_request(request_id, bin_id):
    return Request(
        request_id=request_id,
        event_type=EventType.ARRIVAL,
        bin_id=bin_id,
        t_arrival=0,
        t_earliest=0,
        t_latest=1000,
    )


def _build_engine(num_robots=2, seed=42):
    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 4
    config.bin_num = 30
    config.num_robots = num_robots
    config.num_pickstations = 1
    config.pickstation_capacity = 1
    config.simulation_time = 300
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


# ----------------------------------------------------------------------
# 1. Container-Invariante direkt
# ----------------------------------------------------------------------

def test_mark_task_assigned_removes_task_from_waiting_tasks():
    """
    Kern-Invariante: Nach `mark_task_assigned` darf der Task nicht mehr in
    `waiting_tasks` stehen.
    """
    queue = ActiveQueue()
    task = RobotTask(_make_request(1, 10))
    robot_a = Robot(robot_id=0, position=(0, 0))

    queue.add_waiting_task(task)
    assert task in queue.waiting_tasks

    queue.mark_task_assigned(task, robot_a)

    assert task not in queue.waiting_tasks, (
        "Zugewiesener Task steht weiterhin in waiting_tasks – er kann einem "
        "zweiten Roboter erneut angeboten werden."
    )
    assert queue.assigned[task.request_id]["robot"] is robot_a


def test_task_is_never_waiting_and_assigned_at_the_same_time():
    """
    Ein Task darf nie gleichzeitig in `waiting_tasks` und `assigned` sein.
    """
    queue = ActiveQueue()
    task = RobotTask(_make_request(2, 11))
    robot_a = Robot(robot_id=0, position=(0, 0))

    queue.add_waiting_task(task)
    queue.mark_task_assigned(task, robot_a)

    waiting_ids = {t.request_id for t in queue.waiting_tasks}
    assigned_ids = set(queue.assigned.keys())

    assert not (waiting_ids & assigned_ids), (
        f"Task-IDs gleichzeitig wartend und zugewiesen: "
        f"{waiting_ids & assigned_ids}"
    )


def test_same_task_cannot_be_offered_to_a_second_robot():
    """
    Ablauf aus der Baseline-Analyse:

        Task landet in waiting_tasks
        → Task wird Robot A zugewiesen
        → Scheduler läuft erneut
        → derselbe Task darf Robot B nicht erneut angeboten werden
    """
    engine = _build_engine(num_robots=2)
    queue = engine.active_queue
    scheduler = engine.scheduler

    task = RobotTask(_make_request(3, 12))
    task.target_stack_id = "S_1_1"

    robot_a, robot_b = engine.state.robots[0], engine.state.robots[1]

    # Task ist fortsetzbar und wird Robot A direkt zugewiesen
    # (entspricht dem Pfad in _handle_pickstation_complete)
    queue.add_waiting_task(task)
    robot_a.assign_task(task)
    queue.assign_task_to_robot(task, robot_a)

    # Scheduler läuft erneut – Robot B ist idle
    robot_b.set_status("idle")
    with contextlib.redirect_stdout(io.StringIO()):
        result = scheduler._try_schedule_waiting_task(
            state=engine.state,
            robot=robot_b,
            current_time=engine.state.t,
        )

    if result is not None:
        assert result["task"] is not task, (
            "Derselbe Task wurde einem zweiten Roboter angeboten "
            "(Doppelvergabe)."
        )

    assert robot_b.current_task is not task
    assert queue.assigned[task.request_id]["robot"] is robot_a


# ----------------------------------------------------------------------
# 2. Invariante im laufenden Systembetrieb
# ----------------------------------------------------------------------

def _assert_no_double_assignment(engine):
    """Prüft beide Teile der Invariante auf dem aktuellen Zustand."""
    queue = engine.active_queue

    waiting_ids = [t.request_id for t in queue.waiting_tasks]
    assigned_ids = set(queue.assigned.keys())

    overlap = set(waiting_ids) & assigned_ids
    assert not overlap, (
        f"t={engine.state.t}: Task(s) {sorted(overlap)} gleichzeitig in "
        f"waiting_tasks und assigned."
    )

    assert len(waiting_ids) == len(set(waiting_ids)), (
        f"t={engine.state.t}: waiting_tasks enthält Duplikate: {waiting_ids}"
    )

    # Ein Task darf nicht bei zwei Robotern gleichzeitig hängen
    tasks_per_robot = {}
    for robot in engine.state.robots:
        if robot.current_task is None:
            continue
        rid = robot.current_task.request_id
        tasks_per_robot.setdefault(rid, []).append(robot.robot_id)

    doubled = {rid: ids for rid, ids in tasks_per_robot.items() if len(ids) > 1}
    assert not doubled, (
        f"t={engine.state.t}: Task(s) mehreren Robotern zugewiesen: {doubled}"
    )


def test_no_double_assignment_during_multi_robot_run():
    """
    Systemlauf mit mehreren Robotern: Die Invariante muss in jedem
    Simulationsschritt gelten.
    """
    engine = _build_engine(num_robots=3, seed=42)

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(1500):
            if engine.step() is None:
                break
            _assert_no_double_assignment(engine)


def test_no_double_assignment_across_seeds():
    """Mehrere Seeds, damit der Befund nicht seed-spezifisch bleibt."""
    for seed in (1, 2, 3, 4, 42):
        engine = _build_engine(num_robots=3, seed=seed)
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(800):
                if engine.step() is None:
                    break
                _assert_no_double_assignment(engine)
