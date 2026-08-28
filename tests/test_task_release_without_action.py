# tests/test_task_release_without_action.py
"""
Regression fuer verwaiste Tasks (Bug 3, 2026-08-22).

Fehlerbild
----------
`Scheduler.try_schedule` weist dem Roboter den Task zu
(`robot.assign_task`) und ruft danach `strategy.next_action`. Liefert die
Strategie `None` — etwa weil die Target-Bin gerade `in_transit` ist, ein
dokumentiert unkritischer Zustand mit der Absicht „Task kurz warten lassen
und spaeter neu versuchen" —, kehrte `EventHandler.schedule_available_robots`
zurueck, **ohne etwas einzuplanen**.

Folge: Der Roboter behielt den Task, bekam nie ein Event und stand dauerhaft
still. Als unbewegliches Hindernis blockierte er zusaetzlich die uebrigen
Roboter. Belegt in ABC+ABC/Seed 7 bei t=20.828: die Roboter 0, 1 und 4
hielten einen Task, hatten aber kein einziges Event in der Queue; Roboter 4
blockierte (17,17), drei weitere warteten auf genau diese Zelle.

Erwartetes Verhalten
--------------------
    NO_ACTION -> RELEASE -> RETRY -> PROGRESS

Der Task geht zurueck in `waiting_tasks`, der Roboter wird frei, und sobald
die Ursache entfaellt, wird derselbe Task erneut vergeben und macht echten
Fortschritt.

Definition eines verwaisten Roboters, die hier geprueft wird:

    robot.current_task is not None
    UND kein zukuenftiges Event fuer diesen Roboter
    UND kein vom Scheduler verwalteter Wartezustand
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.simulation_engine import SimulationEngine


def build_engine(robots=1, bins=60, width=6, depth=6, height=5, seed=42):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = height
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = 500
    config.random_seed = seed
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def clear_scheduling_state(engine):
    """Leert Queues, damit nur der praeparierte Request wirkt."""
    engine.active_queue.pending.clear()
    engine.active_queue.waiting_tasks.clear()
    engine.active_queue.assigned.clear()
    engine.state.event_queue.queue.clear()
    for robot in engine.state.robots:
        robot.clear_task()


def events_for(engine, robot_id):
    treffer = 0
    for item in engine.state.event_queue.queue:
        event = item[-1] if isinstance(item, tuple) else item
        payload = event.payload if isinstance(event.payload, dict) else {}
        robot = payload.get("robot")
        if getattr(robot, "robot_id", None) == robot_id:
            treffer += 1
    return treffer


def stranded_robots(engine):
    """Roboter mit Task, aber ohne jedes zukuenftige Event."""
    return [r.robot_id for r in engine.state.robots
            if r.current_task is not None and events_for(engine, r.robot_id) == 0]


def make_request(request_id, bin_id):
    return Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    )


def take_bin_into_transit(engine, nth=0):
    """
    Versetzt eine Bin in den Zustand „wird gerade getragen".

    Genau dafuer liefert `TopAccessStrategy._next_retrieve_target_action`
    bewusst `None`: die Bin liegt in keinem Stack, ist aber auch nicht
    verloren — der Task soll kurz warten und spaeter neu versuchen. Es reicht
    NICHT, nur das Flag zu setzen: solange die Bin im Stack liegt, plant die
    Strategie ganz normal weiter.
    """
    stacks = [s for s in engine.state.grid.all_stacks() if s.height() > 0]
    stack = stacks[nth]
    bin_obj = stack.pop()
    engine.event_handler._sync_stack_bin_metadata(stack)
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.mark_in_transit()
    return bin_obj


def put_bin_back(engine, bin_obj, nth=0):
    """Hebt den Transit-Zustand auf und legt die Bin wieder in einen Stack."""
    stacks = [s for s in engine.state.grid.all_stacks()
              if s.height() < engine.config.max_stack_height]
    stack = stacks[nth]
    bin_obj.mark_transit_done()
    bin_obj.set_stack(None)
    stack.push(bin_obj)
    engine.event_handler._sync_stack_bin_metadata(stack)
    return stack


def rng_states(engine):
    return [rng.bit_generator.state for rng in (
        engine.rng, engine.robot_rng, engine.service_rng,
        engine.relocation_rng, engine.placement_rng)]


# ====================================================================== #
# NO_ACTION -> RELEASE
# ====================================================================== #

@pytest.fixture
def blocked_assignment():
    """
    Ein Request, dessen Target-Bin gerade `in_transit` ist.

    Die Strategie liefert dafuer bewusst `None` („Task kurz warten lassen").
    Genau dieser Zustand fuehrte zum verwaisten Roboter.
    """
    engine = build_engine()
    clear_scheduling_state(engine)

    bin_obj = take_bin_into_transit(engine)

    request = make_request(4711, bin_obj.bin_id)
    engine.active_queue.add(request)

    return engine, request, bin_obj


def test_task_without_action_is_released_instead_of_stranding(blocked_assignment):
    """Der Roboter darf den Task nicht behalten, wenn nichts eingeplant wird."""
    engine, request, _ = blocked_assignment
    robot = engine.state.robots[0]

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    assert robot.current_task is None, (
        "Der Roboter haelt einen Task, fuer den nichts eingeplant wurde."
    )
    assert stranded_robots(engine) == [], "Verwaister Roboter"


def test_the_task_survives_the_release_exactly_once(blocked_assignment):
    """Kein Taskverlust, kein Duplikat, keine doppelte Zuweisung."""
    engine, request, _ = blocked_assignment

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    warteschlange = list(engine.active_queue.waiting_tasks)
    passend = [t for t in warteschlange if t.request_id == request.request_id]

    assert len(passend) == 1, (
        f"Task genau einmal erwartet, gefunden: {len(passend)}"
    )
    assert request.request_id not in engine.active_queue.assigned, (
        "Task gilt weiterhin als zugewiesen."
    )
    assert passend[0].target_bin_id == request.target_box_id


def test_release_does_not_create_a_new_request(blocked_assignment):
    """Die Freigabe erzeugt keinen zusaetzlichen Request."""
    engine, request, _ = blocked_assignment
    vorher = len(engine.active_queue.pending)

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    nachher = len(engine.active_queue.pending)
    assert nachher <= vorher, "Es ist ein zusaetzlicher Request entstanden."


def test_release_consumes_no_randomness(blocked_assignment):
    """Der Freigabepfad zieht keine Zufallszahl."""
    engine, _, _ = blocked_assignment
    vorher = rng_states(engine)

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    assert rng_states(engine) == vorher


def test_release_leaves_no_stale_ownership(blocked_assignment):
    """Die Freigabe hinterlaesst keine Blocker-Ownership."""
    engine, _, bin_obj = blocked_assignment

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    assert engine.active_queue.get_blocker_owned_bin_ids() == frozenset()
    assert not engine.active_queue.is_bin_blocker_owned(bin_obj.bin_id)


# ====================================================================== #
# RETRY -> PROGRESS
# ====================================================================== #

def test_released_task_is_reassigned_and_makes_progress(blocked_assignment):
    """
    Der Kern der Regression: nach Wegfall der Ursache muss derselbe Task
    erneut vergeben werden UND eine echte Folgeaktion bekommen.

    Ein Test, der nur prueft, dass keine Exception fliegt, wuerde den
    urspruenglichen Fehler nicht erkennen — dort flog nie eine Exception,
    es passierte nur nichts mehr.
    """
    engine, request, bin_obj = blocked_assignment
    robot = engine.state.robots[0]

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    assert robot.current_task is None
    assert len(engine.state.event_queue.queue) == 0, (
        "Testaufbau: es sollte noch kein Event geben."
    )

    # Ursache entfaellt: die Bin ist wieder greifbar.
    put_bin_back(engine, bin_obj)

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler.schedule_available_robots(engine.state.t)

    assert robot.current_task is not None, (
        "Der freigegebene Task wurde nicht erneut vergeben."
    )
    assert robot.current_task.request_id == request.request_id
    assert events_for(engine, robot.robot_id) > 0, (
        "Der wieder zugewiesene Task hat keine Folgeaktion erhalten."
    )
    assert stranded_robots(engine) == []


def test_multiple_robots_none_stays_stranded():
    """
    Mehrere Roboter erhalten gleichzeitig einen Task ohne Aktion — keiner
    darf haengen bleiben.
    """
    engine = build_engine(robots=3)
    clear_scheduling_state(engine)

    bins = []
    for i in range(3):
        bin_obj = take_bin_into_transit(engine, nth=i)
        bins.append(bin_obj)
        engine.active_queue.add(make_request(5000 + i, bin_obj.bin_id))

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(3):
            engine.event_handler.schedule_available_robots(engine.state.t)

    assert stranded_robots(engine) == [], "Mindestens ein Roboter blieb haengen."
    for robot in engine.state.robots:
        assert robot.current_task is None


# ====================================================================== #
# Im echten Lauf
# ====================================================================== #

def test_no_stranded_robots_in_a_real_run():
    """Ende-zu-Ende: ein normaler Lauf hinterlaesst keinen verwaisten Roboter."""
    engine = build_engine(robots=4, bins=120, width=7, depth=7, height=6)
    engine.config.simulation_time = 1200
    engine.config.reordering_strategy = "ABC"
    engine.config.placement_strategy = "ABC"
    engine.config.return_blocking_bins = True

    buf = io.StringIO()
    fehler = None
    with contextlib.redirect_stdout(buf):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            fehler = f"{type(exc).__name__}: {exc}"

    assert fehler is None, f"Lauf abgebrochen: {fehler}"
    assert stranded_robots(engine) == []
    assert "Invalid task lifecycle" not in buf.getvalue()
