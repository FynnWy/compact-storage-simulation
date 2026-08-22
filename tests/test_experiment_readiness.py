# tests/test_experiment_readiness.py
"""
Absicherung der wissenschaftlichen Messinfrastruktur (Phase 5).

Geprüft werden die Eigenschaften, auf die sich die finale Experimentkampagne
und beide Masterarbeiten stützen:

* die Retrieval-Tabelle liefert die Rohdaten für Mellers RQ1 und RQ3,
* die primäre KPI zählt physische Retrievals, nicht Requests,
* die Steady-State-Regel ist transparent und verhält sich vernünftig,
* die Pickstation-Zuordnung ist im finalen Layout nachweislich neutral,
* keine Policy erhält Look-ahead auf exogene Größen.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from metrics.steady_state import SteadyStateDetector, analyse_run
from simulation.simulation_engine import SimulationEngine


def build_engine(reordering="LOFI", placement="RANDOM", rbb=True,
                 seed=42, sim_time=300, width=12, depth=18, bins=1150,
                 robots=5, zipf=1.0):
    """
    Kleines Szenario. Die geprüften Eigenschaften (Vollständigkeit der
    Retrieval-Tabelle, Batching-Semantik, KPI-Abgrenzung) sind von der
    Gridgröße unabhängig; die Testsuite soll schnell bleiben.

    Ausnahme: `test_pickstation_choice_is_distance_only_in_the_final_layout`
    prüft ausdrücklich die FINALE Geometrie und setzt sie explizit.
    """
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 8
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = 0.6
    config.enable_visualization = False
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = zipf
    config.reordering_strategy = reordering
    config.placement_strategy = placement
    config.return_blocking_bins = rbb
    return SimulationEngine(config)


def run(engine):
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            return exc
    return None


# ======================================================================
# 1. Retrieval-Tabelle – Rohdaten für RQ1 und RQ3
# ======================================================================

def test_retrieval_table_has_one_row_per_physical_retrieval():
    """
    Genau eine Zeile je physischem Target-Retrieval – nicht je Request.

    Das ist die Grundlage der primären KPI: Durch Batching können mehrere
    Requests durch EIN Retrieval bedient werden.
    """
    engine = build_engine(sim_time=300)
    run(engine)

    rows = engine.metrics.retrievals
    zusammenfassung = engine.metrics.summary()

    assert rows, "Kein Retrieval erfasst"
    assert zusammenfassung["physical_retrievals"] == len(rows)
    assert len(rows) == len(engine.metrics.request_digging_depths), (
        "Retrieval-Tabelle und Digging-Depth-Liste zählen unterschiedlich"
    )

    # Jede Bin-Ankunft ist genau einmal vertreten.
    schluessel = [(r["request_id"], r["t_pickstation"]) for r in rows]
    assert len(schluessel) == len(set(schluessel))


def test_retrieval_rows_are_complete_for_rq3():
    """
    RQ3 braucht je Retrieval: Level vor dem Digging, Stackhöhe, Anzahl
    Blocking Bins und die ABC-Klasse. Keines der Felder darf fehlen.
    """
    engine = build_engine(sim_time=300)
    run(engine)

    max_height = engine.config.max_stack_height
    for row in engine.metrics.retrievals:
        assert row["level"] is not None
        assert row["stack_height"] is not None
        assert row["levels_from_top"] is not None
        assert row["blocking_bins"] is not None
        assert row["abc_class"] in ("A", "B", "C")

        assert 0 <= row["level"] < row["stack_height"] <= max_height
        assert row["levels_from_top"] == row["stack_height"] - 1 - row["level"]


def test_blocking_bins_matches_the_position_in_the_stack():
    """
    β (`blocking_bins`) und `levels_from_top` messen fast immer dasselbe –
    aber nicht per Definition.

    `levels_from_top` ist ein SNAPSHOT: die Anzahl Bins über der Target-Bin
    in dem Moment, in dem der Task den Zielstapel zum ersten Mal ansieht
    (`TopAccessStrategy`, `task.target_stack_id is None`). `blocking_bins`
    ist der TATSÄCHLICHE Umlagerungsaufwand, den der Task bis zum Retrieval
    geleistet hat (`len(task.temp_storage)`).

    In einem Mehrrobotersystem können beide auseinanderlaufen, in beide
    Richtungen:

    * kleiner – ein Blocker wird zwischenzeitlich von einem anderen Task
      übernommen (Ownership-Transfer), der eigene Aufwand sinkt;
    * größer – ein anderer Roboter legt während des laufenden Digs eine Bin
      auf den Zielstapel, die dann zusätzlich abgeräumt werden muss.
      Nachgewiesen im Trace: Dig-Start t=95 auf S_0_3, fremder Push t=137,
      Abräumen t=150 – gemeldet werden 5 Blocker bei `levels_from_top = 4`.

    Der zweite Fall ist keine Folge der Initial-Eligibility: er tritt auch
    auf dem alten Startzustand auf (Seeds 3 und 7). Eine Assertion
    `blocking_bins <= levels_from_top` war deshalb faktisch falsch und lief
    bei Seed 42 nur zufällig durch.

    Geprüft wird daher, was tatsächlich gelten muss:
    die beiden Größen stimmen in der großen Mehrzahl der Retrievals exakt
    überein, Abweichungen bleiben selten und bleiben in der Größenordnung
    eines Stapels. Läuft das auseinander, misst die Digging-Tiefe etwas
    anderes als gedacht.
    """
    engine = build_engine(sim_time=300)
    run(engine)

    rows = engine.metrics.retrievals
    assert rows

    max_height = engine.config.max_stack_height
    exakt = sum(1 for r in rows if r["blocking_bins"] == r["levels_from_top"])
    zu_viel = [r for r in rows if r["blocking_bins"] > r["levels_from_top"]]

    for row in rows:
        assert row["blocking_bins"] >= 0
        abweichung = abs(row["blocking_bins"] - row["levels_from_top"])
        assert abweichung <= max_height, (
            f"Digging-Tiefe {row['blocking_bins']} weicht um {abweichung} von "
            f"levels_from_top {row['levels_from_top']} ab – mehr als eine "
            f"volle Stapelhöhe ({max_height}) ist nicht durch Interferenz "
            f"erklärbar."
        )

    assert exakt / len(rows) > 0.8, (
        f"Nur {exakt}/{len(rows)} Retrievals stimmen exakt überein – "
        f"die Digging-Tiefe misst offenbar etwas anderes."
    )

    assert len(zu_viel) / len(rows) < 0.2, (
        f"{len(zu_viel)}/{len(rows)} Retrievals melden MEHR Blocker als beim "
        f"Dig-Start über der Target-Bin lagen. Vereinzelt ist das durch "
        f"Fremdablage auf dem Zielstapel erklärbar, häufig nicht."
    )


def test_batch_size_is_recorded_after_batching_is_attached():
    """
    `batch_size` muss die tatsächliche Zahl gemeinsam bedienter Requests
    enthalten. Wird die Zeile zu früh geschrieben, steht dort konstant 1.
    """
    engine = build_engine(sim_time=300, zipf=1.5)  # starke Konzentration
    run(engine)

    rows = engine.metrics.retrievals
    assert rows
    assert all(r["batch_size"] >= 1 for r in rows)
    assert max(r["batch_size"] for r in rows) > 1, (
        "Kein einziges Batching erfasst – batch_size wird zu früh geschrieben."
    )


def test_request_throughput_and_bin_throughput_differ_under_batching():
    """
    Der fachliche Kern der KPI-Entscheidung: Requests und physische
    Retrievals sind NICHT dieselbe Größe.
    """
    engine = build_engine(sim_time=300, zipf=1.5)
    run(engine)

    rows = engine.metrics.retrievals
    assert rows

    bediente_requests = sum(r["batch_size"] for r in rows)
    physische_retrievals = len(rows)

    # Gemessen an der Retrieval-Tabelle selbst, nicht an `requests_completed`.
    # Letzteres hängt zusätzlich davon ab, wie viele Requests beim Laufende
    # noch in Bearbeitung sind, und wäre als Nachweis unsauber.
    assert bediente_requests > physische_retrievals, (
        f"{bediente_requests} bediente Requests bei {physische_retrievals} "
        f"Retrievals – ohne Batching-Effekt taugt das Szenario nicht als "
        f"Nachweis."
    )

    # Im finalen Setup (20x30, 4320 Bins, Zipf 1.5) wurde ein Verhältnis von
    # 2,1 Requests je physischem Retrieval gemessen. Deshalb ist die
    # Request-Zahl KEIN Ersatz für eine Bin-basierte Throughput-Größe.
    assert engine.metrics.summary()["physical_retrievals"] == physische_retrievals


# ======================================================================
# 2. Steady-State-Regel
# ======================================================================

def test_detector_reports_not_converged_while_the_signal_still_drifts():
    detector = SteadyStateDetector(block_size=2, threshold=0.10,
                                   required_stable_pairs=2)
    for wert in [4, 4, 3, 3, 2, 2, 1, 1]:
        detector.observe(wert, time=0)

    assert not detector.is_converged()
    assert detector.convergence_time() is None


def test_detector_converges_on_a_stable_signal():
    detector = SteadyStateDetector(block_size=2, threshold=0.10,
                                   required_stable_pairs=2)
    werte = [4, 4, 2, 2, 2, 2, 2, 2]
    for i, wert in enumerate(werte):
        detector.observe(wert, time=i * 10)

    assert detector.is_converged()
    assert detector.convergence_retrievals() == 8
    assert detector.convergence_time() == 70


def test_detector_treats_a_dig_free_warehouse_as_steady():
    """
    Natural Slotting kann β auf 0 drücken. Zwei Blöcke ohne Digging sind ein
    Steady State – die relative Änderung darf dort nicht explodieren.
    """
    detector = SteadyStateDetector(block_size=2, threshold=0.10,
                                   required_stable_pairs=2)
    for wert in [3, 3, 0, 0, 0, 0, 0, 0]:
        detector.observe(wert, time=0)

    assert detector.is_converged()


def test_detector_needs_more_than_one_stable_pair():
    """Ein einzelner Zufallstreffer darf keine Konvergenz auslösen."""
    detector = SteadyStateDetector(block_size=2, threshold=0.10,
                                   required_stable_pairs=2)
    for wert in [4, 4, 4, 4, 1, 1]:   # stabil, dann Sprung
        detector.observe(wert, time=0)

    assert not detector.is_converged()


def test_analyse_run_marks_non_converged_runs_explicitly():
    """
    Ein Lauf ohne Konvergenz darf nicht stillschweigend wie ein konvergierter
    behandelt werden.
    """
    driftend = [{"blocking_bins": b, "t_pickstation": i}
                for i, b in enumerate([6, 5, 4, 3, 2, 1])]
    ergebnis = analyse_run(driftend, block_size=2, threshold=0.05,
                           measurement_retrievals=2)

    assert ergebnis["status"] == "not_converged"
    assert ergebnis["measurement_window"] == []
    assert ergebnis["measurement_complete"] is False


def test_analyse_run_cuts_the_measurement_window_after_convergence():
    zeilen = [{"blocking_bins": 2, "t_pickstation": i} for i in range(20)]
    zeilen[0]["blocking_bins"] = 9
    zeilen[1]["blocking_bins"] = 9

    ergebnis = analyse_run(zeilen, block_size=2, threshold=0.10,
                           measurement_retrievals=5)

    assert ergebnis["status"] == "converged"
    assert len(ergebnis["measurement_window"]) == 5
    assert ergebnis["measurement_complete"] is True
    # Das Fenster beginnt NACH dem Konvergenzpunkt.
    start = ergebnis["convergence_retrievals"]
    assert ergebnis["measurement_window"][0] is zeilen[start]


def test_steady_state_rule_works_on_a_real_run():
    """
    Ende-zu-Ende: Auf echten Laufdaten liefert die Regel eine erklärbare
    Aussage – entweder Konvergenz mit Zeitpunkt oder sauber `not_converged`.
    """
    engine = build_engine(sim_time=400)
    run(engine)

    ergebnis = analyse_run(engine.metrics.retrievals, block_size=10,
                           threshold=0.15, measurement_retrievals=10)

    assert ergebnis["status"] in ("converged", "not_converged")
    assert ergebnis["blocks_completed"] >= 1
    if ergebnis["status"] == "converged":
        assert ergebnis["convergence_time"] is not None
        assert ergebnis["convergence_retrievals"] > 0


# ======================================================================
# 3. Experimentelle Neutralität
# ======================================================================

def test_pickstation_choice_is_distance_only_in_the_final_layout():
    """
    Im finalen Layout (20x30, 2 Pickstations) ist ein exakter
    Distanzgleichstand geometrisch unmöglich: Er verlangte x = 9.5.

    Die Regel reduziert sich damit auf „minimale Manhattan-Distanz", der
    `effective_load`-Tie-Break ist unerreichbar und kann das Experiment nicht
    beeinflussen.

    Der Test hält das fest, damit eine spätere Änderung der Gridbreite oder
    Stationsanordnung nicht unbemerkt einen lastabhängigen Mechanismus
    aktiviert.
    """
    engine = build_engine(sim_time=50, width=20, depth=30, bins=4320, robots=8)
    stations = engine.state.pickstations
    assert len(stations) == 2

    gleichstaende = [
        (x, y)
        for x in range(engine.config.grid_width)
        for y in range(engine.config.grid_depth)
        if (abs(x - stations[0].position[0]) + abs(y - stations[0].position[1]))
        == (abs(x - stations[1].position[0]) + abs(y - stations[1].position[1]))
    ]

    assert gleichstaende == [], (
        f"{len(gleichstaende)} Positionen mit Distanzgleichstand – der "
        f"lastabhängige Tie-Break wird erreichbar und muss neu bewertet werden."
    )


def test_both_pickstations_are_actually_used():
    engine = build_engine(sim_time=400)
    run(engine)

    bedient = {p.station_id: p.total_tasks_processed
               for p in engine.state.pickstations}
    assert len(bedient) == 2
    assert all(v > 0 for v in bedient.values()), (
        f"Eine Pickstation bleibt ungenutzt: {bedient}"
    )


def test_no_policy_can_read_future_service_times():
    """
    `request.service_time` ist eine exogene Größe, die vor Simulationsbeginn
    feststeht. Läse eine Policy oder der Scheduler sie, hätte sie Look-ahead
    auf die Zukunft.

    Erlaubt ist ausschließlich der EventBuilder, der die Dauer beim Start des
    Pickstation-Service auswertet.
    """
    import inspect

    import simulation.scheduler as scheduler_mod
    import strategies.relocation_selection as reloc_mod
    import strategies.reordering_blocking_bins_selector as reorder_mod
    import strategies.target_bin_placement_selector as placement_mod
    import strategies.top_access_strategy as top_mod

    for modul in (scheduler_mod, reloc_mod, reorder_mod, placement_mod, top_mod):
        quelle = inspect.getsource(modul)
        assert "service_time" not in quelle, (
            f"{modul.__name__} liest `service_time` – das wäre Look-ahead auf "
            f"eine exogene Zufallsgröße."
        )


def test_ownership_release_is_wired_in_the_production_engine():
    """
    Die Freigabe der globalen Blocker-Ownership hängt an der Injektion der
    ActiveQueue in die Strategie. Der Produktionspfad muss sie immer setzen.
    """
    engine = build_engine(placement="RANDOM", rbb=False, sim_time=50)
    strategie = engine.scheduler.strategy

    assert strategie._active_queue is engine.active_queue, (
        "Ohne diese Injektion bleibt bei return_blocking_bins=False verwaiste "
        "Blocker-Ownership zurück."
    )


def test_metrics_do_not_consume_randomness():
    """
    Die Messinfrastruktur darf keine Zufallsentscheidungen treffen – sonst
    wäre die Common-Random-Numbers-Eigenschaft aus Phase 4 zerstört.
    """
    engine = build_engine(sim_time=300)

    zustand_vorher = {
        name: engine.rng_streams.get(name).bit_generator.state
        for name in ("requests", "service")
    }

    run(engine)
    engine.metrics.summary()
    engine.distribution_metrics.snapshot()
    analyse_run(engine.metrics.retrievals, block_size=5)

    for name, vorher in zustand_vorher.items():
        assert engine.rng_streams.get(name).bit_generator.state == vorher, (
            f"Der exogene Strom {name!r} wurde nach dem Lauf weiterbewegt."
        )
