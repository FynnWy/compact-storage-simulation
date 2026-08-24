# tests/test_task_lifecycle_consistency.py
"""
Regression fuer den Lifecycle-Abbruch (2026-08-22).

Fehlerbild
----------
    RuntimeError: Cannot complete request 394: target was not removed

`ABC+ABC`, Seed 7, t = 21.869. Der Task stand in `PHASE_COMPLETE` und meldete
die Target-Bin als zurueckgelegt, obwohl `target_removed` nie gesetzt war. Der
Lauf war bis sechs Zeiteinheiten vor dem Abbruch produktiv — kein Deadlock,
kein Stillstand.

Ursache
-------
Der Stale-Schutz im DROP-Pfad erkannte eine fremde Target-Ruecklagerung an der
BIN statt am Request:

    foreign_target = (... and robot.current_task.target_bin_id != bin_id)

Zielen zwei Requests auf dieselbe Bin — bei einer A-Klasse-Bin der Normalfall,
fuer Bin 0 standen 22 Requests in der Batch-Warteliste —, stimmt die Bin
ueberein, obwohl die Aktion zu einem anderen Task gehoert. Die Buchhaltung
landete auf dem falschen Task. Der Pickup-Pfad prueft an derselben Stelle
ueber die `request_id` und war nie betroffen.

Zweiter, verwandter Befund: `TopAccessStrategy` setzte im Zweig „Target liegt
bereits an der Pickstation" nur `target_at_pickstation`, nicht
`target_removed` — ein Task, der diesen Zweig nimmt, waere an derselben
Abschlussinvariante gescheitert.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


def build_engine(robots=2, bins=100, width=7, depth=7, height=6,
                 seed=42, sim_time=400):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = height
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.reordering_strategy = "ABC"
    config.placement_strategy = "ABC"
    config.return_blocking_bins = True
    return SimulationEngine(config)


def make_task(request_id, bin_id):
    return RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))


def stack_position(stack):
    return tuple(int(x) for x in stack.stack_id.split("_")[1:])


def put_bin_at_pickstation(engine, robot):
    """Bin liegt an der Pickstation und wird vom Roboter getragen."""
    handler = engine.event_handler
    quelle = next(s for s in engine.state.grid.all_stacks() if s.height() > 0)
    bin_obj = quelle.pop()
    handler._sync_stack_bin_metadata(quelle)
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.set_status("at_pickstation")
    bin_obj.mark_in_transit()
    robot.set_carried_bin(bin_obj.bin_id)
    return bin_obj, quelle


def free_target_stack(engine):
    for stack in engine.state.grid.all_stacks():
        pos = stack_position(stack)
        if (stack.height() < engine.config.max_stack_height
                and engine.state.is_valid_storage_position(*pos)):
            return stack
    raise AssertionError("Kein freier Zielstack im Testaufbau")


# ====================================================================== #
# 1. Lifecycle-Vorbedingung
# ====================================================================== #

def test_target_cannot_be_marked_returned_before_it_was_removed():
    """
    Eine Bin kann nicht zurueckgelegt werden, bevor sie entnommen wurde.

    Fail-Fast an der ersten ungueltigen Transition statt erst beim
    Request-Abschluss rund 21.000 ZE spaeter.
    """
    task = make_task(request_id=1, bin_id=7)
    assert task.target_removed is False

    with pytest.raises(RuntimeError, match="never removed from storage"):
        task.mark_target_returned()

    assert task.target_returned is False
    assert task.phase != RobotTask.PHASE_COMPLETE


def test_regular_lifecycle_still_completes():
    """Der gueltige Weg bleibt unveraendert moeglich."""
    engine = build_engine()
    task = make_task(request_id=2, bin_id=7)
    task.target_stack_id = "S_1_1"

    task.mark_waiting_at_pickstation()
    assert task.target_removed is True
    assert task.target_at_pickstation is True

    task.mark_pickstation_completed()
    task.actual_return_stack_id = "S_1_1"
    task.mark_target_returned()

    assert task.target_returned is True
    assert task.phase == RobotTask.PHASE_COMPLETE


def test_bin_already_at_pickstation_sets_both_flags():
    """
    Findet ein Task seine Target-Bin bereits an der Pickstation vor, gilt sie
    als entnommen — sonst scheitert er spaeter an der eigenen
    Abschlussinvariante.
    """
    engine = build_engine()
    strategy = engine.scheduler.strategy
    state = engine.state
    robot = state.robots[0]

    bin_obj, _ = put_bin_at_pickstation(engine, robot)
    bin_obj.mark_transit_done()
    robot.clear_carried_bin()

    task = make_task(request_id=3, bin_id=bin_obj.bin_id)
    with contextlib.redirect_stdout(io.StringIO()):
        strategy.next_action(state, task)

    assert task.target_at_pickstation is True
    assert task.target_removed is True, (
        "Eine Bin an der Pickstation ist nachweislich aus dem Lager entnommen."
    )


# ====================================================================== #
# 2./3. Fremder Target-Return bei zwei Requests auf dieselbe Bin
# ====================================================================== #

def test_foreign_target_return_does_not_touch_the_current_task():
    """
    Der Kernfall: zwei Requests auf DIESELBE Bin.

    Der Drop gehoert zu Request A, der Roboter haelt inzwischen Task B. Die
    Bin muss physisch abgelegt werden, aber Task B darf davon nichts
    mitbekommen.
    """
    engine = build_engine()
    handler = engine.event_handler
    state = engine.state
    robot = state.robots[0]

    bin_obj, quelle = put_bin_at_pickstation(engine, robot)
    ziel = free_target_stack(engine)
    robot.set_position(stack_position(ziel))

    task_a = make_task(request_id=500, bin_id=bin_obj.bin_id)
    task_a.target_stack_id = quelle.stack_id
    task_a.mark_waiting_at_pickstation()
    task_a.mark_pickstation_completed()
    task_a.phase = RobotTask.PHASE_RETURN_TARGET

    aktion = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": ziel.stack_id,
        "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=aktion, request=task_a.request, time=state.t
    )

    # Zwischenzeitlich bekommt der Roboter einen anderen Task auf dieselbe Bin.
    task_b = make_task(request_id=394, bin_id=bin_obj.bin_id)
    robot.assign_task(task_b)

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert task_b.target_returned is False, (
        "Ein fremder Target-Return hat den aktuellen Task als 'returned' "
        "markiert."
    )
    assert task_b.target_removed is False
    assert task_b.phase != RobotTask.PHASE_COMPLETE

    ok, grund = task_b.can_complete_consistently(state)
    assert not ok and grund != "target was not removed", (
        f"Task B ist in einen inkonsistenten Abschlusszustand geraten: {grund}"
    )


def test_foreign_target_return_still_stores_the_bin_physically():
    """
    Die Bin darf nicht im Transit haengen bleiben.

    Uebersprungen wird ausschliesslich die Task-Buchhaltung, nicht die
    physische Ablage — sonst waere die Bin dauerhaft verloren.
    """
    engine = build_engine()
    handler = engine.event_handler
    state = engine.state
    robot = state.robots[0]

    bin_obj, quelle = put_bin_at_pickstation(engine, robot)
    ziel = free_target_stack(engine)
    robot.set_position(stack_position(ziel))

    task_a = make_task(request_id=501, bin_id=bin_obj.bin_id)
    task_a.target_stack_id = quelle.stack_id
    task_a.mark_waiting_at_pickstation()
    task_a.mark_pickstation_completed()

    aktion = {
        "type": "return", "return_kind": "target", "from_stack": None,
        "to_stack": ziel.stack_id, "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=aktion, request=task_a.request, time=state.t
    )
    robot.assign_task(make_task(request_id=395, bin_id=bin_obj.bin_id))

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert bin_obj.get_status() == "stored"
    assert not bin_obj.in_transit
    assert bin_obj.get_stack() is not None
    assert robot.get_carried_bin() is None


def test_own_target_return_is_still_booked():
    """Gegenprobe: der eigene Return wird weiterhin verbucht."""
    engine = build_engine()
    handler = engine.event_handler
    state = engine.state
    robot = state.robots[0]

    bin_obj, quelle = put_bin_at_pickstation(engine, robot)
    ziel = free_target_stack(engine)
    robot.set_position(stack_position(ziel))

    task = make_task(request_id=600, bin_id=bin_obj.bin_id)
    task.target_stack_id = quelle.stack_id
    task.mark_waiting_at_pickstation()
    task.mark_pickstation_completed()
    task.phase = RobotTask.PHASE_RETURN_TARGET
    robot.assign_task(task)

    aktion = {
        "type": "return", "return_kind": "target", "from_stack": None,
        "to_stack": ziel.stack_id, "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=aktion, request=task.request, time=state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert task.target_returned is True
    assert task.phase == RobotTask.PHASE_COMPLETE
    assert task.actual_return_stack_id == ziel.stack_id


# ====================================================================== #
# 4.-7. Lauf bleibt konsistent
# ====================================================================== #

@pytest.mark.parametrize("policy", [
    ("ABC", "ABC", True),
    ("POPULARITY", "POPULARITY", True),
    ("LOFI", "RANDOM", True),
    ("LOFI", "NEAREST", False),
])
def test_run_completes_requests_only_with_a_valid_lifecycle(policy):
    """
    Kein Request wird abgeschlossen, ohne dass sein physischer
    Retrieval-Lifecycle gueltig ist — und kein Bin geht dabei verloren.
    """
    reordering, placement, rbb = policy
    engine = build_engine()
    engine.config.reordering_strategy = reordering
    engine.config.placement_strategy = placement
    engine.config.return_blocking_bins = rbb

    buf = io.StringIO()
    fehler = None
    with contextlib.redirect_stdout(buf):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            fehler = f"{type(exc).__name__}: {exc}"

    assert fehler is None, f"Lauf abgebrochen: {fehler}"

    ids = [b.bin_id for b in engine.state.bins]
    assert len(set(ids)) == len(ids), "Bin-Duplikate"

    in_stacks = [b.bin_id for s in engine.state.grid.all_stacks() for b in s.bins]
    assert len(set(in_stacks)) == len(in_stacks), "Bin doppelt in Stacks"

    unterwegs = {b.bin_id for b in engine.state.bins
                 if getattr(b, "in_transit", False)
                 or b.get_status() == "at_pickstation"}
    assert set(in_stacks) | unterwegs == set(ids), "Bin verloren"

    log = buf.getvalue()
    assert "Invalid task lifecycle" not in log
    assert "[TASK_DEADLOCK]" not in log


def test_multiple_requests_for_the_same_bin_stay_consistent():
    """
    Mehrere Requests auf dieselbe Bin duerfen sich nicht gegenseitig den
    Lifecycle ueberschreiben.

    Genau diese Konstellation loeste den Abbruch aus: Bin 0 ist A-Klasse, es
    standen 22 Requests dafuer in der Batch-Warteliste.
    """
    engine = build_engine()
    state = engine.state
    ziel_bin = state.bins[0].bin_id

    tasks = [make_task(request_id=900 + i, bin_id=ziel_bin) for i in range(3)]
    for task in tasks:
        assert task.target_bin_id == ziel_bin
        assert task.target_removed is False

    # Nur der Task, der die Bin tatsaechlich entnimmt, darf sie zurueckgeben.
    tasks[0].target_stack_id = "S_1_1"
    tasks[0].mark_waiting_at_pickstation()
    tasks[0].mark_pickstation_completed()
    tasks[0].mark_target_returned()

    assert tasks[0].target_returned is True
    for anderer in tasks[1:]:
        assert anderer.target_returned is False
        with pytest.raises(RuntimeError):
            anderer.mark_target_returned()
