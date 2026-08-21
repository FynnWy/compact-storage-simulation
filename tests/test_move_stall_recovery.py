# tests/test_move_stall_recovery.py
"""
Deterministischer Regressionstest für den MOVE-Stall (Phase 2D, Baseline 29c075b).

Hintergrund
-----------
In finalnaher Konfiguration (20x30, 8 Roboter, 2 Pickstations, RANDOM) kamen
die Seeds 3 und 4 ab t≈850–900 dauerhaft zum Stillstand: mehrere Roboter
standen um einen Port herum fest und erreichten nie wieder Fortschritt.

Die Ursache war NICHT, dass keine Eskalation existierte, sondern dass die
vorhandene Eskalation strukturell unerreichbar war:

* `ROBOT_MOVE` eskaliert über `event.retry_count`.
* Ein übergeordneter Replan (z.B. `[REPLAN][PICKUP_POS]`) erzeugt neue
  MOVE-Events und setzt `retry_count` damit auf 0 zurück.
* Gemessen: Robot 2 stand ab t=854 insgesamt 157+ ZE still, feuerte 91
  MOVE-Events mit retry=0, 91 mit retry=1 und nur 5 mit retry=2 – die
  Eskalationsschwelle wurde nie zuverlässig erreicht.
* Zusätzlich verzögert der Zweig „Zelle in der ReservationTable belegt"
  ohne Wait-Edge, sodass auch die Deadlock-Erkennung nicht greift.

Fix
---
Ein zweiter, **semantischer** Stall-Begriff neben `retry_count`:

    gleicher Robot + gleicher Task + gleiche Taskphase
    + keine tatsächliche Positionsänderung

Bewusst OHNE den geplanten Pfad – ein Replan um dasselbe Hindernis ist kein
neuer Bewegungsversuch.

Diese Datei prüft echtes Verhalten:
1. der Stau entsteht überhaupt,
2. ohne Recovery entsteht kein dauerhafter Fortschritt,
3. die Recovery greift tatsächlich,
4. mindestens ein Roboter verlässt den Konflikt physisch,
5. danach geht es weiter,
6. die physikalischen Invarianten halten (insbesondere Carrying Safety).
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


# ======================================================================
# Aufbau eines deterministischen Staus
# ======================================================================

def _build_engine(width=6, depth=6, num_robots=2, seed=42):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 4
    config.bin_num = 40
    config.num_robots = num_robots
    config.num_pickstations = 1
    config.simulation_time = 2000
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


class _Task:
    """Minimaler Task-Stellvertreter mit der fachlich relevanten Identität."""

    def __init__(self, request_id, phase="PICKUP_TARGET"):
        self.request_id = request_id
        self.phase = phase
        self.assigned_pickstation = None


def _park(robot, position, task=None, path=None):
    robot.set_position(position)
    robot.current_task = task
    robot.set_path(list(path) if path else [], None)


def _jam(engine, blocked_at=(2, 2), blocker_at=(3, 2)):
    """
    Stellt den Kern des beobachteten Staus deterministisch her.

    `blocked` will auf die Zelle von `blocker`, und diese Zelle ist zugleich
    sein Ziel. `blocker` hat keinen eigenen Pfad und räumt die Zelle daher aus
    eigenem Antrieb nie.

    Umplanen kann diesen Konflikt grundsätzlich nicht lösen – die Zielzelle
    IST die blockierte Zelle (dokumentiert in `_resolve_move_deadlock`).
    Einer der beiden muss die Zelle physisch räumen.
    """
    blocked, blocker = engine.state.robots[0], engine.state.robots[1]

    _park(blocked, blocked_at, _Task(901), path=[blocker_at])
    _park(blocker, blocker_at, _Task(902))
    return blocked, blocker


def _drive_moves(engine, robots, until_t, start_t=0):
    """
    Treibt die Simulation zeitschrittweise und stellt in jedem Schritt für die
    gegebenen Roboter ein MOVE-Event zu.

    Bewusst am EventHandler vorbei an der Scheduler-Logik: Der Test soll
    ausschließlich die Bewegungs-Eskalation prüfen, nicht die Taskvergabe.
    """
    handler = engine.event_handler
    positions = {r.robot_id: [] for r in robots}

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        for t in range(start_t, until_t + 1):
            engine.state.t = t
            for robot in robots:
                event = engine.event_builder.build_robot_move_event(robot, t)
                handler._handle_robot_move(event)
            for robot in robots:
                positions[robot.robot_id].append(robot.get_position())

    return positions, buf.getvalue()


# ======================================================================
# 1. Der Stau entsteht – und ohne Recovery bleibt er bestehen
# ======================================================================

def test_jam_persists_without_recovery():
    """
    Kontrollgruppe: Mit deaktivierter Stall-Recovery steht der blockierte
    Roboter über 400 ZE unverändert auf derselben Zelle.

    Das entspricht dem gemessenen Baseline-Verhalten von Seed 3
    (letzter Fortschritt t=854, danach dauerhafter Stillstand).
    """
    engine = _build_engine()
    engine.event_handler.max_move_stall_before_recovery = 10 ** 9

    blocked, blocker = _jam(engine)
    start = blocked.get_position()

    positions, _ = _drive_moves(engine, [blocked], until_t=400)

    assert set(positions[blocked.robot_id]) == {start}, (
        "Ohne Recovery darf sich am Stau nichts ändern – sonst prüft der Test "
        "nicht das, was er prüfen soll."
    )
    assert blocker.get_position() == (3, 2)


# ======================================================================
# 2. Die Recovery greift – und zwar erst nach der Schwelle
# ======================================================================

def test_recovery_does_not_fire_during_normal_congestion():
    """
    Normale Stauzeiten dürfen die Recovery NICHT auslösen.

    Gemessen auf der Baseline (1200 ZE, 8 Roboter): auf gesunden Seeds liegt
    die längste normale Stall-Episode bei 31 (Seed 99) bzw. 48 ZE (Seed 42),
    p99 bei 17–22 ZE. Eine zu früh feuernde Recovery verschlechtert gesunde
    Läufe messbar.
    """
    engine = _build_engine()
    threshold = engine.event_handler.max_move_stall_before_recovery
    assert threshold >= 100, (
        f"Schwelle {threshold} liegt im normalen Staubereich (max. gemessen: "
        f"107 ZE) und würde gesunden Verkehr stören."
    )

    blocked, _ = _jam(engine)

    _, output = _drive_moves(engine, [blocked], until_t=threshold - 5)

    assert "[RECOVERY][MOVE_STALL]" not in output, (
        "Recovery ist vor Ablauf der Schwelle gefeuert."
    )


def test_recovery_fires_and_resolves_the_jam():
    """
    Kernaussage von Phase 2D:
    Erkannt → Recovery → Konflikt aufgelöst → echter Fortschritt.

    Nicht ausreichend wäre: „Recovery wurde ausgelöst und irgendein Zustand
    hat sich geändert."
    """
    engine = _build_engine()
    threshold = engine.event_handler.max_move_stall_before_recovery

    blocked, blocker = _jam(engine)
    contested = blocker.get_position()
    start = blocked.get_position()

    positions, output = _drive_moves(engine, [blocked], until_t=threshold + 60)

    # 3. Die Recovery greift tatsächlich.
    assert "[RECOVERY][MOVE_STALL]" in output, (
        "Stall wurde nicht erkannt – die Eskalation ist weiterhin unerreichbar."
    )

    # 4. Mindestens ein Roboter verlässt den Konflikt physisch.
    moved = [
        r.robot_id
        for r, before in ((blocked, start), (blocker, contested))
        if r.get_position() != before
    ]
    assert moved, (
        "Recovery hat Zustand verändert, aber kein Roboter hat den Konflikt "
        "verlassen – genau das ist der nicht akzeptierte Fall."
    )

    # 5. Der Blockierte kommt danach wirklich voran.
    assert blocked.get_position() != start or contested not in (
        blocker.get_position(),
    ), "Der umstrittene Konflikt besteht unverändert fort."


def test_recovery_restarts_its_budget_after_real_movement():
    """
    Tatsächlicher Positionsfortschritt beendet den Bewegungsversuch. Ein
    Roboter, der sich bewegt, darf niemals in die Recovery laufen.
    """
    engine = _build_engine()
    handler = engine.event_handler
    robot = engine.state.robots[0]

    _park(robot, (1, 1), _Task(903), path=[(1, 2), (1, 3), (1, 4)])
    engine.state.robots[1].set_position((5, 5))

    engine.state.t = 0
    assert handler._note_move_stall(robot) == 0

    engine.state.t = 90
    assert handler._note_move_stall(robot) == 90

    # Bewegung → Budget beginnt neu
    handler._clear_move_stall(robot)
    engine.state.t = 95
    assert handler._note_move_stall(robot) == 0


# ======================================================================
# 3. Die Stall-Identität ist semantisch, nicht ereignisbezogen
# ======================================================================

def test_replan_does_not_reset_the_stall_budget():
    """
    Regression gegen die eigentliche Root Cause.

    Ein Replan tauscht den geplanten Pfad aus. Wäre der Pfad Teil der
    Stall-Identität, würde das Budget – wie beim alten `retry_count` – bei
    jedem Replan zurückgesetzt und die Eskalation nie erreicht.
    """
    engine = _build_engine()
    handler = engine.event_handler
    robot = engine.state.robots[0]

    _park(robot, (2, 2), _Task(904), path=[(3, 2)])

    engine.state.t = 0
    handler._note_move_stall(robot)

    # Replan um dasselbe Hindernis: neuer Pfad, gleiche Position, gleicher Task
    robot.set_path([(2, 3), (3, 3), (3, 2)], None)

    engine.state.t = 100
    assert handler._note_move_stall(robot) == 100, (
        "Ein Replan hat das Stall-Budget zurückgesetzt – das ist genau der "
        "Mechanismus, der den Dauerstillstand verursacht hat."
    )


def test_new_task_starts_a_new_attempt():
    """
    Ein neuer Task ist ein neuer Bewegungsversuch – das Budget muss von vorn
    beginnen, sonst würde ein frisch zugewiesener Roboter sofort eskalieren.
    """
    engine = _build_engine()
    handler = engine.event_handler
    robot = engine.state.robots[0]

    _park(robot, (2, 2), _Task(905), path=[(3, 2)])
    engine.state.t = 0
    handler._note_move_stall(robot)

    engine.state.t = 200
    robot.current_task = _Task(906)
    assert handler._note_move_stall(robot) == 0


def test_phase_change_starts_a_new_attempt():
    """
    Auch ein Phasenwechsel innerhalb desselben Tasks (Hinweg → Rückweg) ist
    fachlich ein neuer Bewegungsversuch.
    """
    engine = _build_engine()
    handler = engine.event_handler
    robot = engine.state.robots[0]

    task = _Task(907, phase="PICKUP_TARGET")
    _park(robot, (2, 2), task, path=[(3, 2)])
    engine.state.t = 0
    handler._note_move_stall(robot)

    engine.state.t = 200
    task.phase = "PICKUP_RETURN"
    assert handler._note_move_stall(robot) == 0


# ======================================================================
# 3b. Zweite Ausprägung: erschöpfte Retry-Leiter
# ======================================================================

def test_exhausted_retry_ladder_triggers_recovery_instead_of_abort():
    """
    Zweite Ausprägung derselben Root Cause.

    Ohne zwischenzeitlichen Replan läuft `retry_count` bis `max_retries`;
    `delay_event` wirft dann `RuntimeError: Event exceeded max retries`.
    Gemessen auf Baseline 29c075b, 20x30, 8 Roboter, Seed 3:
        ABC/ABC                 -> Abbruch bei t=868
        POPULARITY/POPULARITY   -> Abbruch bei t=944
    beide mit `action_type=None`, also einem MOVE-Event.

    Das Ende der Retry-Leiter ist die letzte Sprosse der Eskalation, nicht
    der Abbruchgrund: Erst muss die Recovery versuchen, den Konflikt zu
    lösen.
    """
    engine = _build_engine()
    max_retries = engine.event_builder.max_retries
    blocked, blocker = _jam(engine)
    start = blocked.get_position()

    engine.state.t = 700
    event = engine.event_builder.build_robot_move_event(blocked, 700)
    event.retry_count = max_retries

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        engine.event_handler._handle_robot_move(event)

    output = buf.getvalue()

    assert "[RECOVERY][MOVE_STALL]" in output, (
        "Am Ende der Retry-Leiter wurde keine Recovery versucht – das Event "
        "läuft weiter in den harten Abbruch."
    )
    assert "grund=retry_ladder" in output, (
        "Die Recovery wurde nicht durch die erschöpfte Retry-Leiter "
        "ausgelöst – der zweite Auslöser greift nicht."
    )
    # `_evade_robot` bewegt nicht sofort, sondern plant den Ausweichschritt
    # für t+1 ein. Erst dessen Ausführung ist der echte Fortschritt.
    engine.state.t = 701
    with contextlib.redirect_stdout(io.StringIO()):
        while not engine.state.event_queue.is_empty():
            queued = engine.state.event_queue.pop()
            if queued.payload.get("robot") is blocked:
                engine.event_handler._handle_robot_move(queued)
                break

    assert blocked.get_position() != start, (
        f"Recovery gemeldet, aber der Roboter steht weiterhin auf {start} – "
        f"Zustandsänderung ohne Konfliktauflösung ist nicht ausreichend."
    )


def test_move_at_exhausted_retry_ladder_does_not_raise():
    """
    Verhaltensgarantie statt Implementierungsdetail: Ein MOVE-Event auf der
    letzten Sprosse darf die Simulation nicht mehr abbrechen.
    """
    engine = _build_engine()
    blocked, _ = _jam(engine)

    engine.state.t = 700
    event = engine.event_builder.build_robot_move_event(blocked, 700)
    event.retry_count = engine.event_builder.max_retries

    with contextlib.redirect_stdout(io.StringIO()):
        engine.event_handler._handle_robot_move(event)  # darf nicht werfen


def test_recovery_pushes_a_fresh_move_attempt():
    """
    Nach erfolgreicher Recovery muss ein FRISCHES MOVE-Event zugestellt
    werden (`retry_count == 0`).

    Würde stattdessen `delay_event` den alten Zähler fortschreiben, liefe die
    Recovery bei erschöpfter Leiter unmittelbar in genau den RuntimeError,
    den sie verhindern soll.
    """
    engine = _build_engine()
    max_retries = engine.event_builder.max_retries
    blocked, blocker = _jam(engine)

    queue = engine.state.event_queue
    before = len(queue)
    engine.state.t = 500
    event = engine.event_builder.build_robot_move_event(blocked, 500)
    event.retry_count = max_retries

    with contextlib.redirect_stdout(io.StringIO()):
        resolved = engine.event_handler._recover_stalled_move(
            blocked, blocker.get_position(), event,
            reason="retry_ladder", stalled_for=None,
        )

    assert resolved is True
    assert len(queue) > before, "Kein Folge-Event zugestellt."

    pushed = queue.pop()
    assert pushed.retry_count == 0, (
        f"Folge-Event trägt retry_count={pushed.retry_count} – der alte "
        f"Versuch wird fortgeschrieben statt neu begonnen."
    )


# ======================================================================
# 4. Carrying Safety
# ======================================================================

def test_carrying_robot_keeps_bin_and_task_through_recovery():
    """
    Ein Roboter, der physisch eine Bin trägt, darf durch die Recovery
    NIEMALS seine Bin oder seinen Task verlieren.

    Der Ausweichschritt selbst ist für tragende Roboter zulässig; die
    Trennung von Bin und Task ist es nicht.
    """
    engine = _build_engine()
    threshold = engine.event_handler.max_move_stall_before_recovery

    blocked, blocker = _jam(engine)

    stack = engine.state.grid.get_stack(0, 0)
    bin_obj = stack.peek()
    assert bin_obj is not None
    stack.pop()
    engine.event_handler._sync_stack_bin_metadata(stack)
    bin_obj.mark_in_transit()
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    blocked.set_carried_bin(bin_obj.bin_id)

    task_before = blocked.current_task

    _drive_moves(engine, [blocked], until_t=threshold + 60)

    assert blocked.get_carried_bin() == bin_obj.bin_id, (
        "Die getragene Bin ist der Recovery zum Opfer gefallen."
    )
    assert blocked.current_task is task_before, (
        "Der tragende Roboter wurde von seinem Task getrennt – Bin und Task "
        "dürfen nie auseinanderlaufen."
    )

    # Die Bin liegt in keinem Stack – sie ist weder dupliziert noch abgelegt.
    occurrences = sum(
        1 for s in engine.state.grid.all_stacks() if bin_obj in s.bins
    )
    assert occurrences == 0, (
        f"Getragene Bin liegt zusätzlich in {occurrences} Stack(s)."
    )


def test_carrying_robot_is_never_requeued_by_recovery():
    """
    Ohne freie Nachbarzelle darf die Recovery einen tragenden Roboter nicht
    requeuen – das würde die Bin stranden lassen (Phase-2B-Invariante).
    """
    engine = _build_engine(num_robots=5)
    handler = engine.event_handler

    victim = engine.state.robots[0]
    _park(victim, (2, 2), _Task(908))
    victim.set_carried_bin(4242)

    # Alle Nachbarzellen dichtmachen
    for robot, cell in zip(engine.state.robots[1:],
                           [(3, 2), (1, 2), (2, 3), (2, 1)]):
        _park(robot, cell, _Task(909))

    engine.state.t = 500
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        resolved = handler._resolve_move_deadlock(
            victim=victim,
            contested_cell=(3, 2),
            waiting_robot=engine.state.robots[1],
        )

    assert resolved is False
    assert victim.current_task is not None, "Tragender Roboter wurde requeued."
    assert victim.get_carried_bin() == 4242
    assert "no requeue" in buf.getvalue()


# ======================================================================
# 5. Systemebene: der Stau löst sich und die Simulation läuft weiter
# ======================================================================

def test_full_simulation_recovers_and_keeps_progressing():
    """
    Ende-zu-Ende auf einem kleinen, schnellen Szenario: Nach der Recovery
    entsteht weiterhin echter Fortschritt, und keine physikalische Invariante
    wird verletzt.
    """
    engine = _build_engine(width=8, depth=8, num_robots=4, seed=7)
    engine.config.simulation_time = 600

    completions = []
    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break
            completions.append(
                engine.metrics.summary().get("requests_completed", 0) or 0
            )

    assert completions, "Simulation hat keinen einzigen Schritt ausgeführt."
    assert completions[-1] > 0, "Kein Request abgeschlossen."

    # Bin-Erhaltung: jede Bin ist genau einmal vorhanden.
    carried = {r.get_carried_bin() for r in engine.state.robots}
    carried.discard(None)
    in_stacks = []
    for stack in engine.state.grid.all_stacks():
        in_stacks.extend(b.bin_id for b in stack.bins)

    assert len(in_stacks) == len(set(in_stacks)), "Bin doppelt in Stacks."
    assert not (set(in_stacks) & carried), (
        "Eine getragene Bin liegt gleichzeitig in einem Stack."
    )
