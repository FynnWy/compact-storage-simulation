# tests/test_rq4_export_contract.py
"""
Der RQ4-Exportvertrag (Befund J-2, behoben 2026-08-24).

Vorgeschichte
-------------
`summarise_run` las vier Schluessel aus einem Steady-State-Objekt:
`status`, `convergence_retrievals`, `measurement_complete` und
`measurement_window`. Diese Schluessel stammen aus
`metrics/steady_state.py` — der **verworfenen** beta-Stop-Regel. Im
Kampagnenpfad wurde dagegen `Metrics.get_convergence_analysis()` uebergeben,
das sie gar nicht kennt. Ergebnis: drei Spalten blieben in allen 50 geprueften
Kombinationen leer, und `retrievals.csv` markierte gar nichts.

Die eingefrorene RQ4-Methodik ist eine dritte, ganz andere Regel: offline,
auf `abc_level_<Klasse>_<Tiefe>`, mit TVD ueber Bloecke von 50 physischen
Retrievals. Nur sie darf in `runs.csv` stehen.

Diese Tests halten fest:
    * `is_converged` der Legacy-Detektoren wird NICHT als RQ4-Status
      durchgereicht,
    * die drei Zustaende kommen korrekt in der Exportzeile an,
    * es gibt genau eine Implementierung der Regel.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from experiments.run_export import RUN_FIELDS, summarise_run
from metrics.rq4_plateau import (
    RQ4_STATUSES, analyse_engine, analyse_series, total_variation_distance,
)
from simulation.simulation_engine import SimulationEngine


# ====================================================================== #
# Kuenstliche Zeitreihen: alle drei Zustaende deterministisch erzeugen
# ====================================================================== #

def snapshots_aus_abstaenden(schritte):
    """
    Baut Snapshots, deren TVD zwischen benachbarten Bloecken vorgegeben ist.

    Zwei Komponenten genuegen. Verschiebt man Masse `d` von der einen zur
    anderen, aendern sich beide um `d`, und die TVD ist
    `0.5 * (|d| + |d|) = d`. Die Richtung wechselt, damit die Anteile bei
    langen Reihen im Intervall bleiben; auf den Betrag hat das keinen
    Einfluss.

    Ein Snapshot je Block, damit Blockmittel und Snapshot zusammenfallen.
    """
    snaps = []
    anteil = 0.5
    vorzeichen = 1
    for i, d in enumerate([0.0] + list(schritte)):
        anteil += vorzeichen * d
        vorzeichen *= -1
        snaps.append({
            "time": (i + 1) * 100,
            "abc_level_A_0": anteil,
            "abc_level_C_0": 1.0 - anteil,
        })
    return snaps


def zeiten_fuer(snaps, r_pro_block=50):
    """Retrievalzeiten so, dass je Snapshot genau ein Block voll wird."""
    zeiten = []
    for i, s in enumerate(snaps):
        zeiten += [s["time"]] * r_pro_block
    return zeiten


def test_tvd_of_the_synthetic_series_is_what_we_intend():
    """Der Testaufbau selbst muss stimmen, sonst prueft er nichts."""
    snaps = snapshots_aus_abstaenden([0.02, 0.02])

    assert total_variation_distance(
        {k: v for k, v in snaps[0].items() if k.startswith("abc_level_")},
        {k: v for k, v in snaps[1].items() if k.startswith("abc_level_")},
    ) == pytest.approx(0.02)


def test_a_falling_series_never_reaches_a_plateau():
    """Faellt die TVD durchgehend stark, ist der Lauf nicht konvergiert."""
    schritte = [0.32, 0.16, 0.08, 0.04, 0.02, 0.01, 0.005, 0.0025]
    snaps = snapshots_aus_abstaenden(schritte)

    ergebnis = analyse_series(snaps, zeiten_fuer(snaps))

    assert ergebnis["status"] == "not_converged"
    assert ergebnis["converged"] is False
    assert ergebnis["convergence_time"] is None


def test_a_flattening_series_converges():
    schritte = [0.30, 0.15, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02]
    snaps = snapshots_aus_abstaenden(schritte)

    ergebnis = analyse_series(snaps, zeiten_fuer(snaps))

    assert ergebnis["status"] == "converged"
    assert ergebnis["converged"] is True
    assert ergebnis["convergence_time"] is not None
    assert ergebnis["plateau_level"] == pytest.approx(0.02, abs=1e-3)
    assert ergebnis["redivergence"] is False


def test_a_plateau_that_breaks_apart_is_reported_separately():
    """
    `converged_then_rediverged` ist ein eigener Zustand, nicht `converged`.

    Ein Lager, dessen Verteilung wieder deutlich zu wandern beginnt, war zu
    diesem Zeitpunkt nicht im Steady State.

    Das Plateau muss VOR dem Anstieg lang genug sein (P = 2 aufeinander
    folgende Treffer). Steigt die TVD zu frueh wieder an, findet die Regel
    das Plateau erst im Anstieg selbst — auch das ist korrektes Verhalten,
    aber ein anderer Fall.
    """
    schritte = [0.30, 0.15, 0.02, 0.02, 0.02, 0.02, 0.02, 0.20, 0.20, 0.20]
    snaps = snapshots_aus_abstaenden(schritte)

    ergebnis = analyse_series(snaps, zeiten_fuer(snaps))

    assert ergebnis["status"] == "converged_then_rediverged"
    assert ergebnis["converged"] is False
    assert ergebnis["redivergence"] is True
    assert ergebnis["convergence_time"] is None, (
        "Ein wieder auseinanderlaufender Lauf darf keine Konvergenzzeit "
        "melden."
    )


def test_status_is_always_one_of_the_three_frozen_values():
    for schritte in ([0.32, 0.16, 0.08, 0.04, 0.02, 0.01, 0.005, 0.0025],
                     [0.30, 0.15, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
                     [0.30, 0.15, 0.02, 0.02, 0.02, 0.02, 0.02, 0.20,
                      0.20, 0.20]):
        snaps = snapshots_aus_abstaenden(schritte)
        assert analyse_series(snaps, zeiten_fuer(snaps))["status"] in RQ4_STATUSES


# ====================================================================== #
# Der Vertrag der Exportzeile
# ====================================================================== #

def build_engine(sim_time=400):
    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 120
    config.num_robots = 3
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = 42
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.reordering_strategy = "ABC"
    config.placement_strategy = "ABC"
    config.return_blocking_bins = True
    config.t_measure_start = sim_time // 2
    config.t_final = sim_time
    engine = SimulationEngine(config)
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            pass
    return engine


@pytest.fixture(scope="module")
def lauf():
    return build_engine()


def test_the_dead_legacy_columns_are_gone(lauf):
    """
    Keine Spalte darf etwas versprechen, das nicht berechnet wird.

    Die vier Felder kamen aus der verworfenen beta-Stop-Regel und blieben im
    finalen Pfad ausnahmslos leer.
    """
    tot = {"steady_state_status", "convergence_time",
           "convergence_retrievals", "measurement_complete"}

    assert tot & set(RUN_FIELDS) == set()
    assert tot & set(summarise_run("r", "ABC+ABC", 42, lauf)) == set()


def test_the_row_carries_the_offline_rq4_result(lauf):
    zeile = summarise_run("r", "ABC+ABC", 42, lauf)
    erwartet = analyse_engine(lauf)

    assert zeile["rq4_status"] == erwartet["status"]
    assert zeile["rq4_status"] in RQ4_STATUSES
    assert zeile["rq4_convergence_time_ZE"] == erwartet["convergence_time"]
    assert zeile["rq4_convergence_retrievals"] == erwartet[
        "convergence_retrievals"]
    assert zeile["rq4_plateau_level"] == erwartet["plateau_level"]
    assert zeile["rq4_redivergence"] == erwartet["redivergence"]
    assert zeile["rq4_blocks"] == erwartet["blocks"]


def test_rq4_status_is_never_empty(lauf):
    """Der Status ist ein Pflichtfeld — anders als die bedingten Felder."""
    assert summarise_run("r", "ABC+ABC", 42, lauf)["rq4_status"]


def test_an_explicit_rq4_result_is_used_unchanged(lauf):
    """
    Der Treiber darf die Analyse einmal rechnen und weiterreichen, statt sie
    im Export ein zweites Mal zu rechnen.
    """
    vorgabe = {"status": "converged", "convergence_time": 4711,
               "convergence_retrievals": 123, "plateau_level": 0.0042,
               "redivergence": False, "blocks": 9}

    zeile = summarise_run("r", "ABC+ABC", 42, lauf, rq4=vorgabe)

    assert zeile["rq4_status"] == "converged"
    assert zeile["rq4_convergence_time_ZE"] == 4711
    assert zeile["rq4_convergence_retrievals"] == 123


def test_legacy_is_converged_is_not_reused_as_the_rq4_status(lauf):
    """
    Der Kern von J-2.

    `Metrics.get_convergence_analysis()["is_converged"]` stammt aus einem
    anderen Detektor mit einem anderen Signal. Es darf nicht als
    RQ4-Konvergenz durchgereicht werden, solange nicht nachgewiesen ist, dass
    es dieselbe TVD-Regel repraesentiert — und das tut es nicht.
    """
    legacy = lauf.metrics.get_convergence_analysis()
    zeile = summarise_run("r", "ABC+ABC", 42, lauf)

    assert "status" not in legacy, (
        "Der Legacy-Detektor liefert gar keinen Status — genau darum blieb "
        "die alte Spalte leer."
    )
    assert zeile["rq4_status"] == analyse_engine(lauf)["status"]


def test_only_one_implementation_of_the_rule_exists():
    """
    Das Kalibrationsskript und der Export muessen dieselbe Funktion
    benutzen. Zwei Implementierungen koennten auseinanderlaufen, ohne dass
    es jemandem auffaellt.
    """
    import sys
    from pathlib import Path
    closeout = str(Path(__file__).resolve().parents[1]
                   / "experiments" / "closeout")
    if closeout not in sys.path:
        sys.path.insert(0, closeout)
    import analyse_rq4_plateau
    import metrics.rq4_plateau as regel

    assert analyse_rq4_plateau.plateau is regel.plateau
    assert analyse_rq4_plateau.tvd is regel.total_variation_distance
    assert analyse_rq4_plateau.analyse_series is regel.analyse_series


def test_the_frozen_parameters_are_unchanged():
    """Keine Neukalibration, keine Grid-Search, keine neue Schwelle."""
    from metrics.rq4_plateau import (
        RQ4_BLOCK_RETRIEVALS, RQ4_DELTA, RQ4_K, RQ4_P,
        RQ4_REDIVERGENCE_FACTOR,
    )

    assert (RQ4_BLOCK_RETRIEVALS, RQ4_K, RQ4_DELTA, RQ4_P,
            RQ4_REDIVERGENCE_FACTOR) == (50, 2, 0.10, 2, 1.5)


def test_rq4_analysis_consumes_no_randomness(lauf):
    """Postprocessing darf die CRN-Eigenschaft nicht antasten."""
    vorher = {name: lauf.rng_streams.get(name).bit_generator.state
              for name in ("requests", "service", "placement")}

    analyse_engine(lauf)
    summarise_run("r", "ABC+ABC", 42, lauf)

    for name, zustand in vorher.items():
        assert lauf.rng_streams.get(name).bit_generator.state == zustand
