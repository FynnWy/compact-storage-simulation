# tests/test_bin_uniqueness_validation.py
"""
Semantik-Regression für `SimulationEngine._validate_bin_uniqueness`
(Phase 2B, AUDIT-007).

Die Implementierung wurde von O(n²) auf O(n) umgestellt. Die **Semantik darf
sich nicht ändern**: Es müssen exakt dieselben Zustände akzeptiert bzw.
abgelehnt werden wie zuvor.

Geprüfte Fälle:
    V-1  gültiger Zustand wird akzeptiert
    V-2  Bin in zwei Stacks → Duplikat erkannt
    V-3  Bin gleichzeitig im Stack und `at_pickstation` → Duplikat erkannt
    V-4  Bin verschwunden → fehlende Bin erkannt
    V-5  Bin in Transit (kein Stack, nicht an PS) wird als sichtbar gezählt
    V-6  Bin in Transit UND im Stack wird nicht doppelt gezählt
"""

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


def _engine(bins=30):
    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 4
    config.bin_num = bins
    config.num_robots = 1
    config.num_pickstations = 1
    config.simulation_time = 100
    config.random_seed = 42
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def _first_non_empty_stack(engine):
    for stack in engine.state.grid.all_stacks():
        if stack.height() > 0:
            return stack
    raise AssertionError("kein gefüllter Stack")


def _first_other_stack(engine, exclude):
    for stack in engine.state.grid.all_stacks():
        if stack is not exclude:
            return stack
    raise AssertionError("kein zweiter Stack")


# ======================================================================

def test_valid_state_is_accepted():
    """V-1"""
    engine = _engine()
    engine._validate_bin_uniqueness()  # darf nicht werfen


def test_duplicate_in_two_stacks_is_detected():
    """V-2"""
    engine = _engine()
    source = _first_non_empty_stack(engine)
    other = _first_other_stack(engine, source)
    bin_obj = source.peek()

    other.push(bin_obj)  # jetzt in ZWEI Stacks

    with pytest.raises(RuntimeError, match="duplicate bin detected"):
        engine._validate_bin_uniqueness()


def test_bin_in_stack_and_at_pickstation_is_detected():
    """V-3"""
    engine = _engine()
    source = _first_non_empty_stack(engine)
    bin_obj = source.peek()

    bin_obj.set_status("at_pickstation")  # zusätzlich als PS-Bin gezählt

    with pytest.raises(RuntimeError, match="duplicate bin detected"):
        engine._validate_bin_uniqueness()


def test_missing_bin_is_detected():
    """V-4"""
    engine = _engine()
    source = _first_non_empty_stack(engine)
    bin_obj = source.pop()
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    # weder Stack noch Pickstation noch Transit

    with pytest.raises(RuntimeError, match="expected .* bins"):
        engine._validate_bin_uniqueness()


def test_bin_in_transit_counts_as_visible():
    """V-5"""
    engine = _engine()
    source = _first_non_empty_stack(engine)
    bin_obj = source.pop()
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.mark_in_transit()

    engine._validate_bin_uniqueness()  # darf nicht werfen


def test_bin_in_transit_and_in_stack_is_not_double_counted():
    """
    V-6: Eine Bin, die `in_transit` ist und (noch) im Stack liegt, darf nicht
    doppelt gezählt werden – sonst gäbe es ein falsches Duplikat.
    """
    engine = _engine()
    source = _first_non_empty_stack(engine)
    bin_obj = source.peek()
    bin_obj.mark_in_transit()  # bleibt im Stack

    engine._validate_bin_uniqueness()  # darf nicht werfen


def test_validation_runs_during_simulation():
    """Die Prüfung bleibt Teil des Laufzeit-Pfads (nicht abgeschaltet)."""
    import io
    import contextlib

    engine = _engine()
    calls = {"n": 0}
    original = engine._validate_bin_uniqueness

    def counted():
        calls["n"] += 1
        return original()

    engine._validate_bin_uniqueness = counted

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(40):
            if engine.step() is None:
                break

    assert calls["n"] > 0, (
        "Bin-Uniqueness-Validierung läuft nicht mehr im Simulationspfad."
    )
