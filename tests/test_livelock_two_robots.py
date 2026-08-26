# tests/test_livelock_two_robots.py
"""
Deterministischer Regressionstest für das 2-Robot-Livelock (Fix 3, 2026-08-19).

Reproduktion aus ARCHITEKTUR_KARTE.md 9.2:
    7x7, max_height 6, 100 Bins, 2 Robots, Seed 42, util 0.5, sim_time 500
    → ab t≈9 vollständiger Stillstand der Nutzarbeit
    → 0 Targets in 500 ZE, 551 [REPLAN], 694 [BLOCKED], 0 [DEADLOCK]

Wichtig: Dieser Test prüft **echten Nutzfortschritt**, nicht "keine Exception"
und nicht "weniger Warnungen".

Progress-Bedingung (auf Basis des bestehenden Systems):
    Ein Fortschrittsereignis ist jeder der folgenden Zustandsübergänge:
      - eine Target-Bin erreicht die Pickstation  (task.target_at_pickstation)
      - ein Pickstation-Service ist abgeschlossen (task.pickstation_completed)
      - eine Target-Bin ist zurückgelagert        (task.target_returned)
      - ein Request ist vollständig abgeschlossen (metrics requests_completed)
    Diese Ereignisse sind monoton und lassen sich pro Zeitschritt zählen.

    Die Simulation macht Fortschritt, wenn zwischen zwei Fortschrittsereignissen
    nie mehr als MAX_STALL_WINDOW Zeiteinheiten vergehen.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


# Zeitfenster, innerhalb dessen mindestens ein Fortschrittsereignis
# auftreten muss. Großzügig gewählt: ein vollständiger Retrieve-Zyklus
# im 7x7-Grid dauert deutlich unter 100 ZE.
MAX_STALL_WINDOW = 120


def _build_livelock_engine(seed=42, num_robots=2, util=0.5, sim_time=500):
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


def _progress_counter(engine):
    """
    Zählt kumulierte Fortschrittsereignisse über alle bekannten Tasks.

    Monoton steigend – ein Rückgang ist nicht möglich, weil die zugrunde
    liegenden Task-Flags nur einmal gesetzt werden.
    """
    tasks = {}

    for task in engine.active_queue.waiting_tasks:
        tasks[id(task)] = task
    for task in engine.active_queue.pickstation_tasks.values():
        tasks[id(task)] = task
    for robot in engine.state.robots:
        if robot.current_task is not None:
            tasks[id(robot.current_task)] = robot.current_task

    live = 0
    for task in tasks.values():
        live += 1 if getattr(task, "target_at_pickstation", False) else 0
        live += 1 if getattr(task, "pickstation_completed", False) else 0
        live += 1 if getattr(task, "target_returned", False) else 0

    completed = engine.metrics.summary().get("requests_completed", 0) or 0

    # Abgeschlossene Tasks verschwinden aus den Containern; ihre drei
    # Fortschrittsereignisse werden über den Completion-Zähler bewahrt.
    return completed * 4 + live


def run_and_measure(engine, max_steps=60000):
    """
    Lässt die Simulation laufen und misst das längste Zeitfenster ohne
    Fortschrittsereignis.
    """
    best = 0
    last_progress_time = 0
    max_gap = 0
    error = None

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        try:
            for _ in range(max_steps):
                if engine.step() is None:
                    break

                current = _progress_counter(engine)
                if current > best:
                    best = current
                    last_progress_time = engine.state.t

                gap = engine.state.t - last_progress_time
                if gap > max_gap:
                    max_gap = gap
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            error = exc

    output = buf.getvalue()
    summary = engine.metrics.summary()

    return {
        "error": error,
        "t_end": engine.state.t,
        "progress_events": best,
        "max_gap": max_gap,
        "requests_completed": summary.get("requests_completed", 0) or 0,
        "replans": output.count("[REPLAN"),
        "blocked": output.count("[BLOCKED"),
        "warnings": output.count("[WARNING"),
        "deadlocks": output.count("[DEADLOCK"),
    }


def test_two_robot_scenario_makes_real_progress():
    """
    Das bekannte Livelock-Szenario muss echten Nutzfortschritt erreichen.

    Baseline `82cfcab`: requests_completed = 0, max_gap = 500 (kompletter
    Stillstand ab t≈9).
    """
    engine = _build_livelock_engine(seed=42, num_robots=2, util=0.5)
    result = run_and_measure(engine)

    assert result["error"] is None, f"Simulation abgebrochen: {result['error']}"

    assert result["requests_completed"] > 0, (
        f"Kein einziger Request abgeschlossen – Livelock besteht fort. "
        f"replans={result['replans']} blocked={result['blocked']} "
        f"warnings={result['warnings']}"
    )

    assert result["max_gap"] <= MAX_STALL_WINDOW, (
        f"Längste Phase ohne Nutzfortschritt: {result['max_gap']} ZE "
        f"(erlaubt: {MAX_STALL_WINDOW}). "
        f"requests_completed={result['requests_completed']}"
    )


def test_two_robot_scenario_does_not_become_a_static_deadlock():
    """
    Gegenprobe zum Erfolgskriterium: Der Fix darf den Livelock nicht einfach
    durch dauerhaften Stillstand ersetzen. Beide Roboter müssen sich im
    Verlauf bewegt haben.
    """
    engine = _build_livelock_engine(seed=42, num_robots=2, util=0.5)

    start_positions = {r.robot_id: r.get_position() for r in engine.state.robots}
    seen_positions = {r.robot_id: set() for r in engine.state.robots}

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(60000):
            if engine.step() is None:
                break
            for robot in engine.state.robots:
                seen_positions[robot.robot_id].add(robot.get_position())

    for robot_id, positions in seen_positions.items():
        assert len(positions) > 1, (
            f"Robot {robot_id} hat sich nie bewegt (statischer Deadlock), "
            f"Startposition {start_positions[robot_id]}"
        )


def test_manhattan_fallback_respects_blocked_cells():
    """
    Der Manhattan-Fallback in `ActionCostModel.calculate_path` darf keinen
    Pfad durch eine bekannt blockierte Zelle liefern.

    Vor dem Fix lieferte er genau diesen Pfad – der physische Move scheiterte
    danach garantiert und erzeugte die Replan-Endlosschleife.
    """
    engine = _build_livelock_engine()
    cost_model = engine.event_handler.event_builder.cost_model

    # Ohne traffic_manager greift direkt der Fallback
    path = cost_model.calculate_path(
        from_position=(2, 2),
        to_position=(2, 3),
        robot=None,
        state=None,
        current_time=0,
        blocked_cells={(2, 3)},
    )
    assert path == [], f"Fallback lieferte Pfad durch blockierte Zelle: {path}"

    # Ohne Blockade weiterhin der normale Pfad
    path = cost_model.calculate_path(
        from_position=(2, 2),
        to_position=(2, 3),
        robot=None,
        state=None,
        current_time=0,
    )
    assert path == [(2, 3)]


def test_swap_conflict_is_detected_and_resolved():
    """
    Direkter Test des Swap-Konflikts:
    Zwei benachbarte Roboter wollen jeweils auf die Zelle des anderen.
    Die Recovery muss einen der beiden tatsächlich ausweichen lassen –
    Delay oder reines Replanning genügen nicht.
    """
    engine = _build_livelock_engine(num_robots=2)
    handler = engine.event_handler

    robot_a, robot_b = engine.state.robots

    robot_a.set_position((3, 3))
    robot_b.set_position((3, 4))
    robot_a.set_path([(3, 4)], target_action=None)
    robot_b.set_path([(3, 3)], target_action=None)

    detector = engine.state.traffic_manager.deadlock_detector
    detector.clear_all()

    # Wartekanten wie im realen Konflikt registrieren
    detector.register_wait(robot_a.robot_id, robot_b.robot_id, "path_blocked", 0)
    detector.register_wait(robot_b.robot_id, robot_a.robot_id, "path_blocked", 0)

    assert detector.detect_cycle() is not None, (
        "Wait-Graph erkennt den Swap-Konflikt nicht."
    )

    positions_before = {r.robot_id: r.get_position() for r in engine.state.robots}

    with contextlib.redirect_stdout(io.StringIO()):
        resolved = handler._resolve_move_deadlock(
            victim=robot_b,
            contested_cell=(3, 4),
            waiting_robot=robot_a,
        )
        # Ausweich-Move ausführen
        for _ in range(20):
            if engine.step() is None:
                break
            if robot_b.get_position() != positions_before[robot_b.robot_id]:
                break

    assert resolved, "Deadlock-Recovery meldete keinen Erfolg."
    assert robot_b.get_position() != positions_before[robot_b.robot_id], (
        "Opfer hat die umstrittene Zelle nicht geräumt – der Konflikt besteht "
        "unverändert fort (verbotenes Anti-Pattern: Zustand geändert, "
        "Konflikt gleich)."
    )


@pytest.mark.parametrize("seed", [1, 2, 3, 42])
def test_low_load_two_robot_scenarios_make_progress(seed):
    """
    Niedriglast-Szenarien (util 0.5): Hier trat der deterministische Livelock
    auf, weil sich Konflikte nicht durch Fremdbewegung auflösen.
    """
    engine = _build_livelock_engine(seed=seed, num_robots=2, util=0.5)
    result = run_and_measure(engine)

    assert result["error"] is None, f"seed={seed}: {result['error']}"
    assert result["requests_completed"] > 0, (
        f"seed={seed}: keine Completions (max_gap={result['max_gap']})"
    )
    assert result["max_gap"] <= MAX_STALL_WINDOW, (
        f"seed={seed}: max_gap={result['max_gap']} ZE ohne Nutzfortschritt"
    )
