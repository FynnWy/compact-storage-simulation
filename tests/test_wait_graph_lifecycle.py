# tests/test_wait_graph_lifecycle.py
"""
Lifecycle-Tests für Wartekanten im Wait-For-Graph (Hardening, Baseline 58c5ef2).

Hintergrund:
Fix 3 hält Wartekanten bewusst länger am Leben – `_replan_path_around_obstacle`
gibt nur noch die Reservierungen frei, nicht mehr die Kante. Nur dadurch sieht
`detect_cycle()` überhaupt beide Kanten eines Swap-Konflikts.

Daraus entsteht ein neues Risiko: Eine Kante bleibt bestehen, obwohl die
Abhängigkeit nicht mehr existiert → Phantom-Zyklus → falsche Deadlock-
Auflösung.

Diese Datei prüft alle semantischen Cleanup-Punkte einzeln und anschließend,
ob daraus Phantom-Zyklen entstehen können.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


def _build_engine(num_robots=2, width=7, depth=7, seed=42):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 6
    config.bin_num = 60
    config.num_robots = num_robots
    config.simulation_time = 300
    config.random_seed = seed
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def _detector(engine):
    return engine.state.traffic_manager.deadlock_detector


def _make_dummy_task(request_id=9001, bin_id=1):
    from events.event_types import EventType
    from requests_.request import Request
    from simulation.robot_task import RobotTask

    return RobotTask(Request(
        request_id=request_id,
        event_type=EventType.ARRIVAL,
        bin_id=bin_id,
        t_arrival=0,
        t_earliest=0,
        t_latest=1000,
    ))


# ----------------------------------------------------------------------
# Entstehung
# ----------------------------------------------------------------------

def test_wait_edge_is_created_on_blocked_move():
    """
    Blockiert ein Roboter physisch die Zielzelle eines anderen, muss ab der
    Replan-Schwelle eine Wartekante entstehen.
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((3, 3))
    robot_b.set_position((3, 4))
    robot_a.set_path([(3, 4)], target_action=None)

    event = handler.event_builder.build_robot_move_event(
        robot=robot_a, time=engine.state.t
    )
    event.retry_count = handler.max_move_retries_before_replan

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_move(event)

    assert detector.is_waiting(robot_a.robot_id), (
        "Keine Wartekante trotz physischer Blockade."
    )


# ----------------------------------------------------------------------
# Cleanup-Punkte
# ----------------------------------------------------------------------

def test_wait_edge_is_cleared_after_successful_replan():
    """
    Findet der Roboter einen Alternativpfad, ist die Abhängigkeit aufgelöst –
    die Kante muss verschwinden.
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((3, 3))
    robot_b.set_position((4, 3))
    # Ziel liegt NICHT auf der blockierten Zelle → Umplanen ist möglich
    robot_a.set_path([(4, 3), (5, 3)], target_action=None)

    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)
    assert detector.is_waiting(robot_a.robot_id)

    event = handler.event_builder.build_robot_move_event(
        robot=robot_a, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._replan_path_around_obstacle(robot_a, (4, 3), event)

    assert not detector.is_waiting(robot_a.robot_id), (
        "Wartekante blieb nach erfolgreichem Replan bestehen."
    )


def test_wait_edge_survives_impossible_replan():
    """
    Ist die blockierte Zelle das eigene Ziel, kann nicht umgeplant werden.
    Die Kante MUSS bestehen bleiben – nur so kann der Swap-Konflikt später
    als Zyklus erkannt werden. (Das war der Kern von Fix 3.)
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((3, 3))
    robot_b.set_position((3, 4))
    robot_a.set_path([(3, 4)], target_action=None)  # Ziel == blockierte Zelle

    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)

    event = handler.event_builder.build_robot_move_event(
        robot=robot_a, time=engine.state.t
    )

    with contextlib.redirect_stdout(io.StringIO()):
        handler._replan_path_around_obstacle(robot_a, (3, 4), event)

    assert detector.is_waiting(robot_a.robot_id), (
        "Wartekante wurde gelöscht, obwohl der Konflikt unverändert besteht."
    )


def test_wait_edge_is_cleared_on_successful_reserved_path():
    """
    `TrafficManager.request_path` löscht die Kante, sobald ein Pfad
    erfolgreich reserviert werden konnte.
    """
    engine = _build_engine()
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((2, 2))

    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)
    assert detector.is_waiting(robot_a.robot_id)

    with contextlib.redirect_stdout(io.StringIO()):
        path = engine.state.traffic_manager.request_path(
            robot=robot_a,
            target=(4, 4),
            current_time=engine.state.t,
        )

    assert path, "Testaufbau: Pfad hätte reservierbar sein müssen."
    assert not detector.is_waiting(robot_a.robot_id), (
        "Wartekante blieb nach erfolgreicher Pfadreservierung bestehen."
    )


def test_wait_edge_is_cleared_on_evade():
    """
    Weicht ein Roboter aus, ist seine eigene Wartebeziehung aufgelöst.
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((3, 3))
    robot_b.set_position((5, 5))

    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)

    with contextlib.redirect_stdout(io.StringIO()):
        assert handler._evade_robot(robot_a, forbidden_cells={(3, 4)})

    assert not detector.is_waiting(robot_a.robot_id), (
        "Wartekante blieb nach dem Ausweichen bestehen."
    )


def test_wait_edge_is_cleared_when_robot_loses_task():
    """
    Verliert ein Roboter seinen Task (Requeue), gibt
    `release_robot_reservations` auch die Wartekante frei.
    """
    engine = _build_engine()
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)

    engine.state.traffic_manager.release_robot_reservations(robot_a)

    assert not detector.is_waiting(robot_a.robot_id)


def test_wait_edge_is_cleared_by_deadlock_requeue_path():
    """
    Der Requeue-Zweig von `_resolve_move_deadlock` muss die Wartekante des
    Opfers bereinigen (er ruft `release_robot_reservations`).
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    victim, waiting = engine.state.robots
    # Ecke, damit Ausweichen scheitert und der Requeue-Pfad greift
    victim.set_position((0, 0))
    waiting.set_position((1, 0))
    victim.current_task = _make_dummy_task()

    detector.register_wait(victim.robot_id, waiting.robot_id, "path_blocked", 0)

    with contextlib.redirect_stdout(io.StringIO()):
        handler._resolve_move_deadlock(
            victim=victim,
            contested_cell=(0, 1),
            waiting_robot=waiting,
        )

    assert not detector.is_waiting(victim.robot_id), (
        "Wartekante des requeueten Opfers blieb bestehen."
    )


# ----------------------------------------------------------------------
# Phantom-Zyklen
# ----------------------------------------------------------------------

def test_stale_edge_does_not_survive_when_conflict_resolves():
    """
    Kernrisiko des längeren Kantenlebens:
    Löst sich der Konflikt (Blockierer fährt weg), darf keine Kante
    zurückbleiben, die später einen Phantom-Zyklus bildet.
    """
    engine = _build_engine()
    handler = engine.event_handler
    detector = _detector(engine)
    detector.clear_all()

    robot_a, robot_b = engine.state.robots
    robot_a.set_position((3, 3))
    robot_b.set_position((3, 4))
    robot_a.set_path([(3, 4)], target_action=None)

    event = handler.event_builder.build_robot_move_event(
        robot=robot_a, time=engine.state.t
    )
    event.retry_count = handler.max_move_retries_before_replan

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_move(event)

    assert detector.is_waiting(robot_a.robot_id)

    # Konflikt löst sich: Blockierer fährt weg
    robot_b.set_position((6, 6))
    engine.state.set_time(engine.state.t + 1)

    follow_up = handler.event_builder.build_robot_move_event(
        robot=robot_a, time=engine.state.t
    )
    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_move(follow_up)

    assert robot_a.get_position() == (3, 4), (
        "Roboter konnte nach Auflösung des Konflikts nicht weiterfahren."
    )
    assert not detector.is_waiting(robot_a.robot_id), (
        "Veraltete Wartekante überlebte die Auflösung des Konflikts → "
        "Phantom-Zyklus-Risiko."
    )


@pytest.mark.parametrize("num_robots,util,seed", [
    (2, 0.5, 42),
    (3, 2.0, 42),
    (4, 2.0, 7),
    (3, 0.5, 99),
])
def test_no_phantom_cycles_during_full_run(num_robots, util, seed):
    """
    Systemlauf: Jeder erkannte Zyklus muss ein ECHTER Konflikt sein.

    Prüfkriterium: Für jede Kante `A → B` eines erkannten Zyklus muss B
    physisch auf der Zelle stehen, die A als Nächstes betreten will, ODER
    B muss die Port-Reservierung halten, auf die A wartet.
    Andernfalls handelt es sich um eine veraltete Kante.
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

    detector = _detector(engine)
    phantom = []

    original_detect = detector.detect_cycle

    def checked_detect():
        cycle = original_detect()
        if cycle:
            by_id = {r.robot_id: r for r in engine.state.robots}
            for robot_id in cycle:
                info = detector._wait_graph.get(robot_id)
                if info is None:
                    continue
                waiting_robot = by_id.get(robot_id)
                blocker = by_id.get(info["waiting_for"])
                if waiting_robot is None or blocker is None:
                    continue
                next_cell = waiting_robot.get_next_waypoint()
                blocks_cell = blocker.get_position() == next_cell
                holds_port = any(
                    ps.reserved_for_robot == blocker.robot_id
                    and ps.position == next_cell
                    for ps in engine.state.pickstations
                )
                if not blocks_cell and not holds_port:
                    phantom.append(
                        (engine.state.t, robot_id, info["waiting_for"],
                         next_cell, blocker.get_position())
                    )
        return cycle

    detector.detect_cycle = checked_detect

    with contextlib.redirect_stdout(io.StringIO()):
        while True:
            if engine.step() is None:
                break

    assert not phantom, (
        f"{len(phantom)} Phantom-Kante(n) in erkannten Zyklen, "
        f"erste 5: {phantom[:5]}"
    )
