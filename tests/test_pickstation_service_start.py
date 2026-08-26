# tests/test_pickstation_service_start.py
"""
Regressionstests für den Start des Pickstation-Service (Fix 1, 2026-08-19).

Befund (ARCHITEKTUR_KARTE.md, Abschnitt 9.3):
In `_handle_pickstation_complete` stand `_try_start_pickstation_service` ganz
am Ende der Methode, hinter mehreren Early Returns. Der wichtigste davon ist
"No robot available" – unter Last ist praktisch nie ein Robot idle.

Folge: Ein freigewordener Service-Slot der Pickstation blieb ungenutzt, obwohl
weitere Bins in der Service-Queue warteten. Der Service selbst benötigt jedoch
gar keinen Roboter.
"""

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


def _build_engine(num_robots=1):
    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 4
    config.bin_num = 20
    config.num_robots = num_robots
    config.num_pickstations = 1
    config.pickstation_capacity = 1
    config.simulation_time = 200
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def _make_task(engine, request_id, bin_id):
    """Erzeugt einen Task, dessen Target-Bin an der Pickstation liegt."""
    request = Request(
        request_id=request_id,
        event_type=EventType.ARRIVAL,
        bin_id=bin_id,
        t_arrival=0,
        t_earliest=0,
        t_latest=1000,
    )
    task = RobotTask(request)
    task.target_stack_id = "S_1_1"
    task.mark_waiting_at_pickstation()
    return task


def _occupy_all_robots(engine):
    """Sorgt dafür, dass kein Roboter idle ist."""
    for robot in engine.state.robots:
        robot.set_status("busy")
    assert all(r.status != "idle" for r in engine.state.robots)


def _pending_pickstation_complete_events(engine):
    return [
        evt
        for evt in engine.event_handler.event_queue.queue
        if evt.event_type == EventType.PICKSTATION_COMPLETE
    ]


def test_next_service_starts_even_when_no_robot_is_idle():
    """
    Kernszenario des Fixes:

    - Service für Bin A ist fertig (PICKSTATION_COMPLETE)
    - Bin B wartet in der Service-Queue der Pickstation
    - kein Roboter ist idle (Abholung von Bin A kann nicht starten)

    Erwartung: Der Service für Bin B startet trotzdem sofort.
    Vor dem Fix schlägt dieser Test fehl, weil `_handle_pickstation_complete`
    beim Early Return "No robot available" endet, ohne den nächsten Service
    zu starten.
    """
    engine = _build_engine(num_robots=1)
    handler = engine.event_handler
    pickstation = engine.state.get_all_pickstations()[0]

    task_a = _make_task(engine, request_id=901, bin_id=1)
    task_b = _make_task(engine, request_id=902, bin_id=2)

    # Task A wird gerade bedient
    task_a.assigned_pickstation = pickstation.station_id
    pickstation.start_service(task_a)
    engine.active_queue.add_pickstation_task(task_a)

    # Task B wartet in der Service-Queue
    pickstation.enqueue(task_b, current_time=engine.state.t)
    engine.active_queue.add_pickstation_task(task_b)

    _occupy_all_robots(engine)

    assert pickstation.queue_length() == 1
    assert not pickstation.has_capacity()

    event = handler.event_builder.build_pickstation_complete_event(
        task=task_a,
        time=engine.state.t,
    )
    handler._handle_pickstation_complete(event)

    # --- Kern-Assertions -------------------------------------------------
    assert task_b in pickstation.current_tasks, (
        "Nächster Pickstation-Service wurde nicht gestartet, obwohl die "
        "Service-Queue gefüllt war (Service braucht keinen Roboter)."
    )
    assert pickstation.queue_length() == 0, (
        "Wartender Task wurde nicht aus der Service-Queue entnommen."
    )

    follow_up = _pending_pickstation_complete_events(engine)
    assert any(
        evt.payload.get("task") is task_b for evt in follow_up
    ), "Kein PICKSTATION_COMPLETE-Event für den nachrückenden Task erzeugt."

    # Vorbedingung des Szenarios muss erhalten geblieben sein
    assert all(r.status != "idle" for r in engine.state.robots)


def test_service_start_is_not_duplicated_when_robot_is_available():
    """
    Gegenprobe: Ist ein Roboter verfügbar, darf der Fix nicht dazu führen,
    dass zwei Services gleichzeitig für dieselbe Kapazität gestartet werden.
    """
    engine = _build_engine(num_robots=1)
    handler = engine.event_handler
    pickstation = engine.state.get_all_pickstations()[0]

    task_a = _make_task(engine, request_id=911, bin_id=1)
    task_b = _make_task(engine, request_id=912, bin_id=2)
    task_c = _make_task(engine, request_id=913, bin_id=3)

    task_a.assigned_pickstation = pickstation.station_id
    pickstation.start_service(task_a)
    engine.active_queue.add_pickstation_task(task_a)

    pickstation.enqueue(task_b, current_time=engine.state.t)
    pickstation.enqueue(task_c, current_time=engine.state.t)
    engine.active_queue.add_pickstation_task(task_b)
    engine.active_queue.add_pickstation_task(task_c)

    # Robot 0 bleibt idle → Abholpfad wird durchlaufen
    engine.state.robots[0].set_status("idle")

    event = handler.event_builder.build_pickstation_complete_event(
        task=task_a,
        time=engine.state.t,
    )
    handler._handle_pickstation_complete(event)

    assert len(pickstation.current_tasks) <= pickstation.capacity, (
        "Pickstation-Kapazität wurde überschritten."
    )
    assert pickstation.available_slots >= 0
    # Genau ein Task darf nachgerückt sein (capacity == 1)
    assert pickstation.queue_length() == 1


def test_service_start_respects_capacity_and_empty_queue():
    """
    Ist die Service-Queue leer, darf nichts gestartet werden – und der Handler
    darf nicht abbrechen.
    """
    engine = _build_engine(num_robots=1)
    handler = engine.event_handler
    pickstation = engine.state.get_all_pickstations()[0]

    task_a = _make_task(engine, request_id=921, bin_id=1)
    task_a.assigned_pickstation = pickstation.station_id
    pickstation.start_service(task_a)
    engine.active_queue.add_pickstation_task(task_a)

    _occupy_all_robots(engine)

    event = handler.event_builder.build_pickstation_complete_event(
        task=task_a,
        time=engine.state.t,
    )
    handler._handle_pickstation_complete(event)

    assert pickstation.current_tasks == []
    assert pickstation.available_slots == pickstation.capacity
    assert pickstation.queue_length() == 0
