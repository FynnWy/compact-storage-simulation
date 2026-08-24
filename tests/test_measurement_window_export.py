# tests/test_measurement_window_export.py
"""
Gemeinsames Zeitfenster im Export (2026-08-22).

Die finale Kampagne laesst alle 50 Runs bis zur selben festen Zeit laufen und
wertet nur `[t_measure_start, t_final]` aus. Das ist keine Kosmetik: das
System laeuft bewusst gesaettigt, die Tardiness misst das Alter des
Rueckstands und waechst mit der Lauflaenge. Nur ueber identische
Zeitintervalle sind `deadline_miss_rate` und `mean_tardiness` zwischen
Policies vergleichbar.

Geprueft wird das Verhalten des Exports, nicht seine Interna:
was landet im Fenster, worauf beziehen sich Durchsatz und Service-KPIs, und
bleibt das alte Verhalten erhalten, wenn kein Fenster gesetzt ist.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from experiments.run_export import (
    measurement_window, retrieval_rows, summarise_run,
)
from simulation.simulation_engine import SimulationEngine


def build_engine(t_measure_start=None, t_final=None, sim_time=1200):
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 120
    config.num_robots = 4
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = 42
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.reordering_strategy = "ABC"
    config.placement_strategy = "ABC"
    config.return_blocking_bins = True
    config.t_measure_start = t_measure_start
    config.t_final = t_final
    engine = SimulationEngine(config)
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            pass
    return engine


def summarise(engine):
    return summarise_run("r1", "ABC+ABC", 42, engine)


@pytest.fixture(scope="module")
def lauf_mit_fenster():
    engine = build_engine(t_measure_start=600, t_final=1200)
    return engine, summarise(engine)


def test_only_retrievals_inside_the_window_are_counted(lauf_mit_fenster):
    engine, zeile = lauf_mit_fenster
    im_fenster = [r for r in engine.metrics.retrievals
                  if 600 <= r["t_pickstation"] <= 1200]

    assert zeile["measurement_mode"] == "time_window"
    assert zeile["t_measure_start"] == 600
    assert zeile["t_final"] == 1200
    assert zeile["physical_retrievals"] == len(engine.metrics.retrievals)
    assert zeile["measurement_retrievals"] == len(im_fenster)
    assert len(im_fenster) < len(engine.metrics.retrievals), (
        "Testaufbau untauglich: das Fenster umfasst den ganzen Lauf."
    )


def test_throughput_uses_the_window_length_not_the_run_length(lauf_mit_fenster):
    engine, zeile = lauf_mit_fenster
    im_fenster = [r for r in engine.metrics.retrievals
                  if 600 <= r["t_pickstation"] <= 1200]

    assert zeile["bin_throughput"] == pytest.approx(len(im_fenster) / 600)


def test_service_kpis_use_the_same_window_as_the_throughput(lauf_mit_fenster):
    """
    Verspaetung und Durchsatz muessen sich auf dasselbe Intervall beziehen.

    Sonst waere `mean_tardiness` ueber den ganzen Lauf gemittelt, waehrend
    `bin_throughput` nur das Fenster misst — der gepaarte Policy-Vergleich
    waere nicht mehr sauber.
    """
    engine, zeile = lauf_mit_fenster
    im_fenster = [r for r in engine.metrics.completed_requests
                  if r.get("time") is not None and 600 <= r["time"] <= 1200]

    assert zeile["requests_completed"] == len(im_fenster)
    assert zeile["requests_evaluated"] == len(im_fenster)
    assert zeile["request_throughput"] == pytest.approx(len(im_fenster) / 600)


def test_station_counts_add_up_to_the_window_retrievals(lauf_mit_fenster):
    """Die Retrievals je Station beziehen sich ebenfalls auf das Fenster."""
    engine, zeile = lauf_mit_fenster
    im_fenster = [r for r in engine.metrics.retrievals
                  if 600 <= r["t_pickstation"] <= 1200]

    summe = (zeile["retrievals_ps0"] or 0) + (zeile["retrievals_ps1"] or 0)
    assert summe == len(im_fenster)


def test_station_utilisation_is_a_full_run_diagnostic(lauf_mit_fenster):
    """
    `pickstation_utilisation_*` ist KUMULATIV ueber den ganzen Lauf.

    `Pickstation.get_utilization` teilt die gesamte Servicezeit durch die
    Laufzeit; eine fensterbezogene Auslastung gaebe es nur mit zusaetzlicher
    Telemetrie. Die Groesse ist deshalb ausdruecklich diagnostisch und darf
    nicht als fensterbezogene KPI gelesen werden. Fuer die Lastverteilung im
    Fenster sind `retrievals_ps0/ps1` zustaendig.
    """
    engine, zeile = lauf_mit_fenster
    erwartet = engine.state.pickstations[0].get_utilization(engine.state.t)

    assert zeile["pickstation_utilisation_ps0"] == pytest.approx(erwartet)
    assert zeile["pickstation_utilisation_ps0"] is not None, (
        "Die KPI war frueher immer None (falscher Methodenname im Export)."
    )


def test_without_a_window_the_whole_run_is_evaluated():
    """
    Ohne konfiguriertes Fenster gilt der ganze Lauf.

    Der frühere dritte Modus `steady_state` (Fenster aus einer festen Zahl
    Retrievals nach der β-Konvergenz) existiert nicht mehr. Er gehörte zur
    verworfenen Stop-Regel und war die zweite, unabhängige Fensterdefinition,
    aus der Befund J-1 entstand. Es gibt jetzt genau zwei Modi:
    `time_window` und `full_run`.
    """
    engine = build_engine(t_measure_start=None, t_final=None, sim_time=600)
    zeile = summarise(engine)

    assert zeile["measurement_mode"] == "full_run"
    assert zeile["t_measure_start"] is None
    assert zeile["measurement_retrievals"] == len(engine.metrics.retrievals)


# ====================================================================== #
# EINE Fensterquelle: runs.csv und retrievals.csv müssen übereinstimmen
# ====================================================================== #

def test_retrieval_flag_matches_the_run_level_window_count(lauf_mit_fenster):
    """
    Der Kern von Befund J-1.

    `runs.csv.measurement_retrievals` und die Zahl der in `retrievals.csv`
    markierten Zeilen müssen für JEDEN Lauf exakt übereinstimmen — nicht nur
    aggregiert über die Kampagne. Vorher markierte `retrieval_rows` aus dem
    alten Steady-State-Fenster und lieferte durchgehend `False`.
    """
    engine, zeile = lauf_mit_fenster
    markiert = [r for r in retrieval_rows("r1", "ABC+ABC", 42, engine)
                if r["in_measurement_window"]]

    assert len(markiert) == zeile["measurement_retrievals"]
    assert len(markiert) > 0, "Testaufbau untauglich: leeres Fenster."


def test_every_marked_retrieval_lies_inside_the_window(lauf_mit_fenster):
    """Die Markierung stimmt zeilenweise, nicht nur in der Summe."""
    engine, _ = lauf_mit_fenster

    for zeile in retrieval_rows("r1", "ABC+ABC", 42, engine):
        drin = 600 <= zeile["t_pickstation"] <= 1200
        assert zeile["in_measurement_window"] is drin, (
            f"t={zeile['t_pickstation']} falsch markiert"
        )


def test_no_silent_fallback_to_the_legacy_window(lauf_mit_fenster):
    """
    Ist ein Zeitfenster gesetzt, darf nichts mehr auf die alte
    Steady-State-Definition zurückfallen — auch dann nicht, wenn die alte
    Regel für denselben Lauf ein völlig anderes Fenster liefern würde.
    """
    engine, zeile = lauf_mit_fenster
    from metrics.steady_state import analyse_run

    legacy = analyse_run(engine.metrics.retrievals, block_size=10)
    legacy_fenster = legacy.get("measurement_window") or []
    markiert = sum(1 for r in retrieval_rows("r1", "ABC+ABC", 42, engine)
                   if r["in_measurement_window"])

    assert zeile["measurement_mode"] == "time_window"
    assert markiert == zeile["measurement_retrievals"]
    assert markiert != len(legacy_fenster) or not legacy_fenster, (
        "Testaufbau untauglich: die alte Regel liefert zufällig dieselbe "
        "Fenstergröße, der Unterschied wäre nicht sichtbar."
    )


# ====================================================================== #
# Grenzfälle der Fenstergrenzen
# ====================================================================== #

class _FakeMetrics:
    def __init__(self, zeiten):
        self.retrievals = [
            {"t_pickstation": t, "request_id": i, "bin_id": i,
             "abc_class": "A", "access_count_before": 0, "level": 0,
             "stack_height": 1, "levels_from_top": 0, "blocking_bins": 0,
             "blockers_returned": True, "batch_size": 1,
             "t_retrieval_start": t, "dig_duration": 1, "pickstation": 0,
             "robot_id": 0}
            for i, t in enumerate(zeiten)
        ]


class _FakeState:
    t = 1000


class _FakeConfig:
    t_measure_start = 200
    t_final = 800


class _FakeEngine:
    """Minimaler Doppelgänger: nur was die Fensterlogik anfasst."""

    def __init__(self, zeiten):
        self.metrics = _FakeMetrics(zeiten)
        self.state = _FakeState()
        self.config = _FakeConfig()


@pytest.mark.parametrize("zeitpunkt,erwartet", [
    (199, False),   # unmittelbar VOR T_measure_start
    (200, True),    # AUF T_measure_start          -> inklusive
    (500, True),    # mitten im Fenster
    (800, True),    # AUF T_final                  -> inklusive
    (801, False),   # unmittelbar NACH T_final
])
def test_window_boundaries_are_inclusive_on_both_ends(zeitpunkt, erwartet):
    """
    Die Grenzsemantik wird NICHT neu erfunden.

    `summarise_run` filtert seit 2026-08-22 mit
    `t_measure_start <= t_pickstation <= t_final`, also beidseitig
    inklusive. Genau das wird hier festgeschrieben, damit die gemeinsame
    Fensterquelle sie nicht unbemerkt verschiebt.
    """
    engine = _FakeEngine([zeitpunkt])
    modus, t_start, t_ende = measurement_window(engine)
    zeilen = list(retrieval_rows("r1", "p", 1, engine))

    assert (modus, t_start, t_ende) == ("time_window", 200, 800)
    assert zeilen[0]["in_measurement_window"] is erwartet


def test_boundary_count_matches_between_both_exports():
    """Über alle fünf Grenzfälle zusammen: beide Seiten zählen gleich."""
    engine = _FakeEngine([199, 200, 500, 800, 801])
    modus, t_start, t_ende = measurement_window(engine)
    markiert = sum(1 for r in retrieval_rows("r1", "p", 1, engine)
                   if r["in_measurement_window"])
    im_fenster = [r for r in engine.metrics.retrievals
                  if t_start <= r["t_pickstation"] <= t_ende]

    assert markiert == len(im_fenster) == 3
