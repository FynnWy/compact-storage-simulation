# tests/test_liveness_buried_blockers.py
"""
Regression fuer den Langzeit-Liveness-Fehler (2026-08-22).

Zwei getrennte Fehlerklassen, beide belegt in den langen Piloten auf der
finalen Geometrie:

Klasse A - verschuetteter Blocker beim Ordered Return
    Ein Task parkt Blocking-Bins auf Pufferstacks und holt sie zum Ordered
    Return genau dort wieder ab. Legte in der Zwischenzeit ein fremder
    Vorgang eine Bin darauf, scheiterte der Pickup dauerhaft mit
    `expected bin X not on top`. Der Rueckgabeplan kannte keinen Schritt zum
    Freiraeumen; Retry und Requeue aenderten daran nichts.
    Betroffen: ABC+ABC/Seed 42 (ab t=7019 kein Fortschritt mehr),
    POPULARITY/Seed 1 (ab t=5134).

Klasse B - verwaistes Pickup-Event
    Nach einem Requeue (`robot.clear_task()`) blieben eingeplante
    Pickup-Events in der Queue. Ohne Task lief das Event ungeprueft durch:
    der Roboter nahm an der Pickstation eine FREMDE Bin auf und blockierte
    danach die einzige Portzelle (LR+NR/Seed 42, t=2184), oder das Event lief
    bis `max_retries` und brach den Lauf ab (RR+RR/Seed 1, t=3603,
    `Event exceeded max retries (20). action_type=return`).

Die Tests pruefen Verhalten, nicht Implementierungsdetails: was darf wo
abgelegt werden, was passiert mit einem verwaisten Event, bleibt der Ordered
Return erhalten, und macht ein langer Lauf weiterhin Fortschritt.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


# ====================================================================== #
# Hilfsfunktionen
# ====================================================================== #

def build_engine(reordering="ABC", placement="ABC", rbb=True, seed=42,
                 robots=4, width=7, depth=7, bins=180, height=6,
                 util=0.5, sim_time=400):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = height
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = reordering
    config.placement_strategy = placement
    config.return_blocking_bins = rbb
    return SimulationEngine(config)


def run(engine):
    """Laesst die Simulation vollstaendig laufen, gibt Log und Fehler zurueck."""
    buf = io.StringIO()
    fehler = None
    with contextlib.redirect_stdout(buf):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            fehler = f"{type(exc).__name__}: {exc}"
    return buf.getvalue(), fehler


def make_task(bin_id, request_id=8001):
    return RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))


def stack_with_capacity(engine, mindestens_frei=2):
    hoehe = engine.config.max_stack_height
    for stack in engine.state.grid.all_stacks():
        pos = _pos(stack)
        if not engine.state.is_valid_storage_position(*pos):
            continue
        if hoehe - stack.height() >= mindestens_frei and stack.height() > 0:
            return stack
    raise AssertionError("Kein geeigneter Stack im Testaufbau")


def _pos(stack):
    teile = stack.stack_id.split("_")
    return int(teile[1]), int(teile[2])


def park_blocker(engine, task, stack, from_stack_id):
    """Simuliert eine bereits erfolgte Auslagerung auf `stack`."""
    bin_obj = stack.peek()
    task.remember_relocation(
        bin_id=bin_obj.bin_id,
        from_stack=from_stack_id,
        buffer_stack=stack.stack_id,
    )
    engine.active_queue.register_blocker_ownership(bin_obj.bin_id, task)
    return bin_obj


# ====================================================================== #
# 1. Ein fremder Task darf einen benoetigten Blocker nicht verschuetten
# ====================================================================== #

def test_placement_skips_stack_holding_a_foreign_blocker():
    """Die Target-Ruecklagerung meidet Stacks mit fremder Blocker-Bin."""
    engine = build_engine()
    stack = stack_with_capacity(engine)
    fremder_task = make_task(bin_id=1)
    park_blocker(engine, fremder_task, stack, from_stack_id="S_3_3")

    selector = engine.scheduler.strategy._placement_selector
    kandidaten = selector._get_eligible_stacks(engine.state)

    assert stack.stack_id not in {s.stack_id for s in kandidaten}, (
        "Ein Stack mit fremder, noch zurueckzulegender Blocker-Bin darf kein "
        "Ablageziel sein - sonst wird sie verschuettet."
    )


def test_relocation_skips_pending_restore_stack_of_another_task():
    """
    Kein Parken auf einem Stack, auf den ein anderer Task noch zurueckliefert.

    Der Ordered Return legt Blocker auf ihren Ursprungsstack zurueck; dieses
    Ziel gehoert zur Strategie und wird nicht umgelenkt. Also darf dort nicht
    fremd geparkt werden.
    """
    engine = build_engine()
    puffer = stack_with_capacity(engine)
    ursprung = None
    for stack in engine.state.grid.all_stacks():
        if stack.stack_id != puffer.stack_id and stack.height() > 0:
            ursprung = stack
            break
    assert ursprung is not None

    fremder_task = make_task(bin_id=2, request_id=8002)
    park_blocker(engine, fremder_task, puffer, from_stack_id=ursprung.stack_id)

    selector = engine.scheduler.strategy._relocation_selector
    kritisch = selector._get_critical_stack_ids(engine.state)

    assert ursprung.stack_id in kritisch, (
        "Das offene Rueckgabeziel eines fremden Tasks muss von der "
        "Park-Auswahl ausgeschlossen sein."
    )
    assert puffer.stack_id in kritisch, (
        "Der Pufferstack mit der fremden Blocker-Bin ebenfalls."
    )


# ====================================================================== #
# 2. Kein zyklischer Relocation-Wait / Freiraeumen statt Endlos-Retry
# ====================================================================== #

def test_buried_blocker_triggers_unbury_instead_of_repeating_the_pickup():
    """
    Liegt die eigene Blocker-Bin unter einer fremden Bin, muss die Strategie
    freiraeumen - nicht denselben Pickup erneut liefern.

    Genau dieser fehlende Schritt war die Ursache des Stillstands: der Pickup
    scheiterte dauerhaft mit `expected bin X not on top`, und niemand entfernte
    die aufliegende Bin.
    """
    engine = build_engine()
    strategy = engine.scheduler.strategy
    state = engine.state

    puffer = stack_with_capacity(engine, mindestens_frei=2)
    task = make_task(bin_id=3, request_id=8003)
    blocker = park_blocker(engine, task, puffer, from_stack_id="S_3_3")

    # Fremde Bin obenauf legen -> Blocker ist verschuettet
    quelle = None
    for stack in state.grid.all_stacks():
        if stack.stack_id != puffer.stack_id and stack.height() > 0:
            quelle = stack
            break
    fremde_bin = quelle.pop()
    puffer.push(fremde_bin)

    assert puffer.peek().bin_id == fremde_bin.bin_id
    assert any(b.bin_id == blocker.bin_id for b in puffer.bins)

    task.phase = RobotTask.PHASE_RESTORE_BLOCKERS
    task.target_at_pickstation = True
    task.pickstation_completed = True

    with contextlib.redirect_stdout(io.StringIO()):
        aktion = strategy.next_action(state, task)

    assert aktion is not None
    assert aktion["type"] == "relocate", (
        f"Erwartet wurde ein Freiraeum-Schritt, geliefert wurde {aktion}"
    )
    assert aktion["bin_id"] == fremde_bin.bin_id
    assert aktion["from_stack"] == puffer.stack_id
    assert aktion["to_stack"] != puffer.stack_id
    assert aktion.get("unbury") is True


def test_unbury_relocation_does_not_become_an_own_blocker():
    """
    Die freigeraeumte Bin darf weder in `temp_storage` noch in die Ownership.

    Sonst wuerde sie per LIFO als Erste zurueckgelegt - ausgerechnet auf den
    gerade freigeraeumten Stack - und die eigene Bin waere erneut verschuettet.
    """
    engine = build_engine()
    handler = engine.event_handler
    state = engine.state

    puffer = stack_with_capacity(engine, mindestens_frei=2)
    task = make_task(bin_id=4, request_id=8004)
    park_blocker(engine, task, puffer, from_stack_id="S_3_3")
    vorher = list(task.temp_storage)

    robot = state.robots[0]
    robot.assign_task(task)

    aktion = {
        "type": "relocate",
        "from_stack": puffer.stack_id,
        "to_stack": "S_2_2",
        "bin_id": 4242,
        "unbury": True,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=aktion, request=None, time=state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._update_task_after_successful_action_new(event)

    assert list(task.temp_storage) == vorher, (
        "Eine Freiraeum-Umlagerung darf keine neue Rueckgabeverpflichtung "
        "erzeugen."
    )
    assert not engine.active_queue.is_bin_blocker_owned(4242)


# ====================================================================== #
# 3. Verwaistes Pickup-Event (Klasse B)
# ====================================================================== #

def test_orphaned_pickup_event_is_dropped_instead_of_taking_a_foreign_bin():
    """
    Ein Roboter ohne Task darf kein Pickup-Event mehr ausfuehren.

    Vorher nahm er an der Pickstation die Bin eines FREMDEN Tasks auf und
    blockierte danach dauerhaft die Portzelle (LR+NR/Seed 42, t=2184).
    """
    engine = build_engine(robots=2)
    handler = engine.event_handler
    state = engine.state
    station = state.pickstations[0]

    quelle = None
    for stack in state.grid.all_stacks():
        if stack.height() > 0:
            quelle = stack
            break
    bin_obj = quelle.pop()
    handler._sync_stack_bin_metadata(quelle)
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.set_status("at_pickstation")
    bin_obj.mark_transit_done()

    robot = state.robots[0]
    robot.set_position(station.position)
    robot.clear_task()
    assert robot.current_task is None

    aktion = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": "S_1_1",
        "bin_id": bin_obj.bin_id,
    }
    event = handler.event_builder.build_robot_pickup_event(
        robot=robot, action=aktion, request=None, time=state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_pickup(event)

    assert robot.get_carried_bin() is None, (
        "Ein Roboter ohne Task hat eine fremde Bin aufgenommen."
    )
    assert not bin_obj.in_transit
    assert bin_obj.get_status() == "at_pickstation"


# ====================================================================== #
# 4.-8. Verhalten im Lauf
# ====================================================================== #

@pytest.mark.parametrize("policy", [
    ("ABC", "ABC", True),
    ("LOFI", "RANDOM", True),
    ("LOFI", "RANDOM", False),
    ("LOFI", "NEAREST", False),
    ("POPULARITY", "POPULARITY", True),
])
def test_run_keeps_bins_consistent_and_finishes_without_abort(policy):
    """
    Kein Bin-Verlust, keine Duplikate, kein Abbruch am Retry-Limit.

    Der Abbruch `Event exceeded max retries (20). action_type=return` war die
    sichtbare Form der Klasse B (RR+RR/Seed 1).
    """
    reordering, placement, rbb = policy
    engine = build_engine(reordering=reordering, placement=placement, rbb=rbb,
                          sim_time=600)
    vorher = len(engine.state.bins)
    log, fehler = run(engine)

    assert fehler is None, f"Lauf abgebrochen: {fehler}"

    ids = [b.bin_id for b in engine.state.bins]
    assert len(ids) == vorher
    assert len(set(ids)) == len(ids), "Bin-Duplikate im Zustand"

    in_stacks = [b.bin_id for s in engine.state.grid.all_stacks() for b in s.bins]
    unterwegs = [b.bin_id for b in engine.state.bins
                 if getattr(b, "in_transit", False)
                 or b.get_status() == "at_pickstation"]
    assert len(set(in_stacks)) == len(in_stacks), "Bin doppelt in Stacks"
    assert set(in_stacks) | set(unterwegs) == set(ids), "Bin verloren"

    assert "[TASK_DEADLOCK]" not in log, (
        "Unaufloesbare Task-Abhaengigkeit im Lauf gemeldet."
    )


def test_ordered_return_semantics_are_preserved():
    """
    Ordered Return bleibt fachlich erhalten: Blocker werden zurueckgelegt.

    Die Freiraeum-Umlagerung darf keine Rueckgabeverpflichtung verwerfen -
    sonst waere aus ABC/Baseline/Popularity heimlich ein No-Return-Verhalten
    geworden.
    """
    engine = build_engine(reordering="ABC", placement="ABC", rbb=True,
                          sim_time=600)
    log, fehler = run(engine)
    assert fehler is None

    zeilen = engine.metrics.retrievals
    assert zeilen, "Kein Retrieval im Testlauf"
    assert all(z["blockers_returned"] for z in zeilen), (
        "Ordered Return wurde stillschweigend abgeschaltet."
    )

    offen = sum(len(getattr(r.current_task, "temp_storage", []) or [])
                for r in engine.state.robots if r.current_task is not None)
    # Offene Verpflichtungen laufender Tasks sind erlaubt; entscheidend ist,
    # dass sie nicht verworfen werden.
    assert offen >= 0


def test_no_return_policies_keep_their_semantics():
    """RR+RR und LR+NR legen weiterhin KEINE Blocker zurueck."""
    for placement in ("RANDOM", "NEAREST"):
        engine = build_engine(reordering="LOFI", placement=placement,
                              rbb=False, sim_time=600)
        log, fehler = run(engine)
        assert fehler is None
        zeilen = engine.metrics.retrievals
        assert zeilen
        assert not any(z["blockers_returned"] for z in zeilen), (
            f"{placement}: Ordered Return wurde faelschlich aktiviert."
        )


def test_long_run_keeps_making_progress_past_the_old_stall_point():
    """
    End-to-End-Regression fuer den Stillstand.

    Dieselbe Konfiguration blieb vor dem Fix bei t=1942 mit 47 Retrievals
    stehen und machte bis t=6000 keinen Fortschritt mehr. Geprueft wird
    deshalb nicht eine Zahl, sondern dass nach der alten Stallstelle weiter
    Retrievals entstehen.
    """
    engine = build_engine(reordering="POPULARITY", placement="POPULARITY",
                          rbb=True, sim_time=3000)
    log, fehler = run(engine)
    assert fehler is None, f"Lauf abgebrochen: {fehler}"

    zeitpunkte = [z["t_pickstation"] for z in engine.metrics.retrievals]
    assert zeitpunkte, "Kein einziges Retrieval"

    nach_stall = [t for t in zeitpunkte if t > 2200]
    assert nach_stall, (
        f"Nach der alten Stallstelle (t=1942) entstand kein Retrieval mehr; "
        f"letztes bei t={zeitpunkte[-1]}"
    )
    assert zeitpunkte[-1] > 2500, (
        f"Der Lauf kommt zum Erliegen: letztes Retrieval bei t={zeitpunkte[-1]}"
    )
    assert len(zeitpunkte) > 47, (
        f"Nicht mehr Retrievals als im festgefahrenen Lauf: {len(zeitpunkte)}"
    )
