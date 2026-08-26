# tests/test_drop_redirect.py
"""
Regressionstests für die Drop-Recovery bei vollem/gesperrtem Ziel-Stack
(Begleitfix zu Fix 1, 2026-08-19).

Befund:
`to_stack` einer relocate-/return-Aktion wird zum Planungszeitpunkt gewählt.
Bis der Robot dort ankommt, kann ein anderer Robot den Stack gefüllt haben.
Der Zustand löst sich nicht von allein auf – `_handle_robot_drop` hat den Fall
vorher nur delayed, bis `EventBuilder.max_retries` die Simulation mit
`RuntimeError: Event exceeded max retries` abgebrochen hat.

Der Abbruch ist bereits auf der Baseline `82cfcab` reproduzierbar
(z.B. 6x6, 2 Robots, seed 99 / 555). Fix 1 (Pickstation-Service-Start)
erhöht die Häufigkeit, weil deutlich mehr Returns parallel laufen.
"""

import io
import contextlib

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from simulation.simulation_engine import SimulationEngine


def _build_engine(placement="RANDOM", seed=123):
    config = SimulationConfig()
    config.grid_width = 6
    config.grid_depth = 6
    config.max_stack_height = 4
    config.bin_num = 80
    config.num_robots = 2
    config.simulation_time = 200
    config.random_seed = seed
    config.enable_visualization = False
    config.reordering_strategy = "LOFI"
    config.placement_strategy = placement
    return SimulationEngine(config)


def _fill_stack(engine, stack, max_height):
    """Füllt einen Stack bis zur Maximalhöhe mit vorhandenen freien Bins."""
    for bin_obj in engine.state.bins:
        if stack.height() >= max_height:
            break
        if getattr(bin_obj, "in_transit", False):
            continue
        src = engine.state.grid.get_stack(*bin_obj.get_stack()) \
            if bin_obj.get_stack() is not None else None
        if src is None or src is stack:
            continue
        if src.peek() is not bin_obj:
            continue
        src.pop()
        stack.push(bin_obj)
        engine.event_handler._sync_stack_bin_metadata(src)
        engine.event_handler._sync_stack_bin_metadata(stack)


def test_blocked_drop_is_redirected_to_alternative_stack():
    """
    Ein Drop auf einen vollen Stack muss nach Erreichen der Retry-Schwelle
    auf einen Ausweich-Stack umgeleitet werden statt endlos zu delayen.
    """
    engine = _build_engine()
    handler = engine.event_handler
    max_height = engine.config.max_stack_height

    # Ziel-Stack künstlich volllaufen lassen
    full_stack = engine.state.grid.get_stack(2, 2)
    _fill_stack(engine, full_stack, max_height)
    assert full_stack.height() >= max_height

    robot = engine.state.robots[0]
    robot.set_position((2, 3))

    # Eine Bin "in der Hand" des Roboters simulieren
    carried = None
    for bin_obj in engine.state.bins:
        if bin_obj.get_stack() is None:
            continue
        src = engine.state.grid.get_stack(*bin_obj.get_stack())
        if src is not None and src is not full_stack and src.peek() is bin_obj:
            src.pop()
            engine.event_handler._sync_stack_bin_metadata(src)
            bin_obj.mark_in_transit()
            bin_obj.set_stack(None)
            bin_obj.set_level(None)
            carried = bin_obj
            break
    assert carried is not None

    action = {
        "type": "relocate",
        "from_stack": "S_2_3",
        "to_stack": full_stack.stack_id,
        "bin_id": carried.bin_id,
    }

    event = handler.event_builder.build_robot_drop_event(
        robot=robot,
        action=action,
        request=None,
        time=engine.state.t,
    )
    event.retry_count = handler.max_drop_retries_before_redirect

    events_before = len(engine.state.event_queue)

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert action["to_stack"] != full_stack.stack_id, (
        "Blockierter Drop wurde nicht auf einen Ausweich-Stack umgeleitet."
    )
    assert len(engine.state.event_queue) > events_before, (
        "Nach der Umleitung wurde kein Folge-Event erzeugt."
    )


def test_blocked_drop_still_delays_below_threshold():
    """
    Unterhalb der Schwelle bleibt das bisherige Verhalten (Delay) erhalten –
    kurzzeitige Blockaden lösen sich oft von allein.
    """
    engine = _build_engine()
    handler = engine.event_handler
    max_height = engine.config.max_stack_height

    full_stack = engine.state.grid.get_stack(2, 2)
    _fill_stack(engine, full_stack, max_height)

    robot = engine.state.robots[0]
    robot.set_position((2, 3))

    action = {
        "type": "relocate",
        "from_stack": "S_2_3",
        "to_stack": full_stack.stack_id,
        "bin_id": 0,
    }
    event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=action, request=None, time=engine.state.t
    )
    event.retry_count = 0

    with contextlib.redirect_stdout(io.StringIO()):
        handler._handle_robot_drop(event)

    assert action["to_stack"] == full_stack.stack_id, (
        "Unterhalb der Schwelle darf noch nicht umgeleitet werden."
    )


@pytest.mark.parametrize("seed,placement", [
    (99, "RANDOM"),
    (123, "RANDOM"),
    (555, "ORIGINAL"),
])
def test_known_full_stack_crash_scenarios_run_through(seed, placement):
    """
    Szenarien, die auf der Baseline `82cfcab` mit
    `RuntimeError: Event exceeded max retries (20). action_type=return/relocate`
    abgebrochen sind, müssen jetzt durchlaufen.
    """
    engine = _build_engine(placement=placement, seed=seed)

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(400):
            if engine.step() is None:
                break

    # Kein Crash = Test bestanden; zusätzlich Grundplausibilität
    assert engine.state.t >= 0
