# tests/test_campaign_integrity_and_preflight.py
"""
Abschlusspruefung und Betriebsprognose des Kampagnentreibers.

Zwei Dinge, die eine 30-Stunden-Kampagne braucht und die vorher fehlten:

* ein Integritaetscheck, der am Ende sagt, ob der Bestand wirklich der
  Versuchsplan ist — statt nur „50 Runs abgeschlossen" zu melden;
* eine Laufzeitprognose, die auf DIESER Maschine gemessen ist, statt aus
  Kernzahlen geraten zu werden.

Die Prognose ist rein operativ. Diese Tests halten unter anderem fest, dass
sie weder Konfigurationen noch Zufallsstroeme der finalen Laeufe beruehrt.
"""

import csv
import json

import pytest

from experiments import runtime_preflight as rp
from experiments.campaign_matrix import (
    FINAL_POLICIES, FINAL_SEEDS, FINAL_SIMULATION_TIME, FINAL_T_FINAL,
    FINAL_T_MEASURE_START, final_matrix,
)
from experiments.run_export import (
    REQUEST_FIELDS, RETRIEVAL_FIELDS, RUN_FIELDS,
)
from experiments.run_final_campaign import pruefe_integritaet


# ====================================================================== #
# Ein vollstaendiger, gesunder Bestand
# ====================================================================== #

def schreibe_bestand(ordner, kombinationen, fenster=4):
    ordner.mkdir(parents=True, exist_ok=True)
    status = {}
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            w.writerow({**{f: "" for f in RUN_FIELDS}, "run_id": rid,
                        "policy": pol, "seed": sd,
                        "measurement_mode": "time_window",
                        "t_measure_start": FINAL_T_MEASURE_START,
                        "t_final": FINAL_T_FINAL,
                        "measurement_retrievals": fenster,
                        "rq4_status": "converged"})
            status[rid] = {"state": "completed", "policy": pol, "seed": sd}
    with open(ordner / "retrievals.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RETRIEVAL_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            for _ in range(fenster):
                w.writerow({**{f: "" for f in RETRIEVAL_FIELDS},
                            "run_id": rid, "policy": pol, "seed": sd,
                            "in_measurement_window": True})
    with open(ordner / "requests.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REQUEST_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            w.writerow({**{f: "" for f in REQUEST_FIELDS}, "run_id": rid,
                        "policy": pol, "seed": sd})
    with open(ordner / "distribution.csv", "w", encoding="utf-8") as fh:
        fh.write("run_id,time\n")
        for rid, _, _ in kombinationen:
            fh.write(f"{rid},0\n")
    (ordner / "run_meta.json").write_text(json.dumps(
        [{"run_id": r} for r, _, _ in kombinationen]))
    return status


@pytest.fixture
def gesund(tmp_path):
    ordner = tmp_path / "final"
    status = schreibe_bestand(ordner, final_matrix())
    return ordner, status


def eintraege_voll():
    return [{"run_id": r, "policy": p, "seed": s} for r, p, s in final_matrix()]


# ====================================================================== #
# Der Integritaetscheck
# ====================================================================== #

def test_a_complete_campaign_passes(gesund):
    ordner, status = gesund
    assert pruefe_integritaet(ordner, eintraege_voll(), status) == []


def test_a_missing_run_is_detected(gesund):
    ordner, status = gesund
    zeilen = [z for z in csv.DictReader(open(ordner / "runs.csv"))
              if z["run_id"] != "ABC+ABC__seed7"]
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen)

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("fehlende Laeufe" in b for b in befunde)
    assert any("ABC+ABC__seed7" in b for b in befunde)


def test_a_duplicated_run_id_is_detected(gesund):
    ordner, status = gesund
    zeilen = list(csv.DictReader(open(ordner / "runs.csv")))
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen + [zeilen[0]])

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("doppelte run_id" in b for b in befunde)


def test_a_window_inconsistency_is_detected(gesund):
    """Genau der Befund J-1, jetzt als Abnahmekriterium."""
    ordner, status = gesund
    zeilen = list(csv.DictReader(open(ordner / "runs.csv")))
    zeilen[0]["measurement_retrievals"] = "99"
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen)

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("Retrievals im Fenster" in b for b in befunde)


def test_a_wrong_horizon_is_detected(gesund):
    ordner, status = gesund
    zeilen = list(csv.DictReader(open(ordner / "runs.csv")))
    zeilen[3]["t_final"] = "42000"
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen)

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("t_final" in b for b in befunde)


def test_an_empty_rq4_status_is_detected(gesund):
    ordner, status = gesund
    zeilen = list(csv.DictReader(open(ordner / "runs.csv")))
    zeilen[5]["rq4_status"] = ""
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen)

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("rq4_status leer" in b for b in befunde)


def test_a_run_not_marked_completed_is_detected(gesund):
    ordner, status = gesund
    status["RR+RR__seed13"]["state"] = "failed"

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("nicht abgeschlossene" in b for b in befunde)


def test_a_foreign_run_id_in_a_child_file_is_detected(gesund):
    ordner, status = gesund
    with open(ordner / "distribution.csv", "a", encoding="utf-8") as fh:
        fh.write("GESPENST__seed1,0\n")

    befunde = pruefe_integritaet(ordner, eintraege_voll(), status)

    assert any("unbekannte run_ids" in b for b in befunde)


# ====================================================================== #
# Hardware und Platz
# ====================================================================== #

def test_hardware_inventory_reports_the_basics(tmp_path):
    info = rp.hardware_inventar(tmp_path)

    assert info["logical_cores"] and info["logical_cores"] >= 1
    assert info["python"]
    assert info["disk_free_bytes"] is None or info["disk_free_bytes"] > 0


def test_disk_check_fails_fast_when_space_is_obviously_short(tmp_path,
                                                             monkeypatch):
    """
    50 Runs brauchen konservativ rund 1 GB. Mit 10 MB frei darf die
    Kampagne nicht starten — nach 20 Stunden „No space left on device" ist
    die teuerste Variante dieses Fehlers.
    """
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 0, "used": 0,
                                 "free": 10 * 1024 * 1024})())

    ergebnis = rp.pruefe_platz(tmp_path, 50)

    assert ergebnis["ok"] is False
    assert "frei" in ergebnis["warnung"]


def test_disk_check_passes_with_ample_space(tmp_path, monkeypatch):
    import shutil

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 0, "used": 0,
                                 "free": 500 * 1024 ** 3})())

    ergebnis = rp.pruefe_platz(tmp_path, 50)

    assert ergebnis["ok"] is True
    assert ergebnis["warnung"] is None


def test_space_estimate_grows_with_the_number_of_runs():
    assert (rp.schaetze_platz(50)["roh_bytes"]
            > rp.schaetze_platz(5)["roh_bytes"])


# ====================================================================== #
# Schaetzung
# ====================================================================== #

SYNTH = [
    {"policy": "baseline_reference", "seconds_per_1000_ZE": 60.0},
    {"policy": "RR+RR", "seconds_per_1000_ZE": 90.0},
    {"policy": "LR+NR", "seconds_per_1000_ZE": 80.0},
    {"policy": "ABC+ABC", "seconds_per_1000_ZE": 50.0},
    {"policy": "POPULARITY+POPULARITY", "seconds_per_1000_ZE": 70.0},
]


def test_estimate_extrapolates_per_policy_not_once_times_fifty():
    """
    Die Policies sind unterschiedlich teuer. Ein Messwert mal 50 wuerde die
    teuerste systematisch unterschaetzen.
    """
    s = rp.schaetze_kampagne(SYNTH, seeds_je_policy=10,
                             ze_je_run=FINAL_SIMULATION_TIME)

    erwartet = sum(b["seconds_per_1000_ZE"] * 30 * 10 for b in SYNTH)
    assert s["central_seconds"] == pytest.approx(erwartet, rel=1e-6)
    assert s["runs"] == 50
    # Der billigste Messwert mal 50 waere deutlich zu niedrig.
    assert s["central_seconds"] > 50.0 * 30 * 50 * 0.9


def test_estimate_range_brackets_the_central_value():
    s = rp.schaetze_kampagne(SYNTH, 10, FINAL_SIMULATION_TIME)

    assert s["low_seconds"] < s["central_seconds"] < s["high_seconds"]


def test_historical_walltimes_are_blended_but_weighted_lower():
    """
    Historische Vollaufzeiten sind wertvoll, stammen aber moeglicherweise
    von anderer Hardware. Der aktuelle Benchmark wiegt deshalb doppelt.
    """
    historisch = {b["policy"]: 3000.0 for b in SYNTH}

    ohne = rp.schaetze_kampagne(SYNTH, 10, FINAL_SIMULATION_TIME)
    mit = rp.schaetze_kampagne(SYNTH, 10, FINAL_SIMULATION_TIME,
                               historisch=historisch)

    assert mit["central_seconds"] != ohne["central_seconds"]
    for eintrag in mit["per_policy"]:
        bench = eintrag["benchmark_estimate_s"]
        hist = eintrag["historical_estimate_s"]
        assert eintrag["combined_estimate_s"] == pytest.approx(
            (2 * bench + hist) / 3, rel=0.01)


def test_historical_walltimes_are_read_from_the_calibration(tmp_path):
    datei = tmp_path / "kalib.json"
    datei.write_text(json.dumps({"runs": [
        {"policy": "ABC+ABC", "t_end": 30000,
         "counters": {"wall_seconds": 1500}},
        {"policy": "ABC+ABC", "t_end": 42000,
         "counters": {"wall_seconds": 2100}},
    ]}))

    werte = rp.historische_walltimes(datei)

    # Beide auf 30.000 ZE normiert: 1500 und 1500.
    assert werte["ABC+ABC"] == pytest.approx(1500.0)


def test_missing_calibration_file_is_not_an_error(tmp_path):
    assert rp.historische_walltimes(tmp_path / "gibtsnicht.json") == {}


# ====================================================================== #
# Laufende ETA
# ====================================================================== #

def test_running_eta_uses_real_walltimes():
    fertig = [("ABC+ABC", 100.0), ("ABC+ABC", 140.0)]
    offen = ["ABC+ABC", "ABC+ABC"]

    s = rp.laufende_schaetzung(fertig, offen)

    assert s["mean_seconds"] == pytest.approx(120.0)
    assert s["remaining_seconds"] == pytest.approx(240.0)
    assert s["finish_estimate"]


def test_running_eta_is_policy_weighted():
    """
    Eine Kampagne, die mit der guenstigsten Policy beginnt, darf die
    restlichen nicht mit deren Tempo hochrechnen.
    """
    fertig = [("ABC+ABC", 100.0), ("RR+RR", 300.0)]
    offen = ["RR+RR", "RR+RR"]

    s = rp.laufende_schaetzung(fertig, offen)

    assert s["remaining_seconds"] == pytest.approx(600.0)


def test_running_eta_falls_back_to_the_preflight_for_unseen_policies():
    vorab = rp.schaetze_kampagne(SYNTH, 10, FINAL_SIMULATION_TIME)
    fertig = [("ABC+ABC", 100.0)]

    s = rp.laufende_schaetzung(fertig, ["POPULARITY+POPULARITY"], vorab)

    # 70 s/1000 ZE * 30 = 2100 s je Lauf, nicht die 100 s von ABC.
    assert s["remaining_seconds"] == pytest.approx(2100.0, rel=0.01)


def test_running_eta_without_data_returns_nothing():
    assert rp.laufende_schaetzung([], ["ABC+ABC"])["remaining_seconds"] is None


# ====================================================================== #
# Die Prognose darf das Experiment nicht beruehren
# ====================================================================== #

def test_the_benchmark_seed_can_never_collide_with_a_final_run_id():
    assert rp.BENCHMARK_SEED not in FINAL_SEEDS
    kennungen = {k for k, _, _ in final_matrix()}
    for policy in FINAL_POLICIES:
        assert f"{policy}__seed{rp.BENCHMARK_SEED}" not in kennungen


def test_the_benchmark_uses_its_own_short_horizon():
    from experiments.campaign_matrix import build_run_config

    config = build_run_config("ABC+ABC", rp.BENCHMARK_SEED,
                              sim_time=rp.BENCHMARK_ZE,
                              t_measure_start=None, t_final=None)

    assert config.simulation_time == rp.BENCHMARK_ZE != FINAL_SIMULATION_TIME
    assert config.t_measure_start is None


def test_the_benchmark_leaves_the_final_configuration_untouched():
    """
    Die Prognose erzeugt eigene Engines. Danach muss eine frisch gebaute
    finale Konfiguration unveraendert sein — Horizont, Fenster, Seed.
    """
    from experiments.campaign_matrix import build_run_config

    vorher = vars(build_run_config("ABC+ABC", 7)).copy()
    rp.benchmarke_policy("ABC+ABC", ze=50)
    nachher = vars(build_run_config("ABC+ABC", 7))

    assert nachher == vorher
    assert nachher["t_measure_start"] == FINAL_T_MEASURE_START
    assert nachher["t_final"] == FINAL_T_FINAL
    assert nachher["random_seed"] == 7


def test_the_benchmark_does_not_advance_a_final_engine_rng():
    """
    Der Benchmark baut eigene Engines mit eigenem Seed. Ein danach
    gebauter finaler Engine muss denselben Zufallszustand haben wie einer
    davor — sonst waere CRN verletzt.
    """
    from experiments.campaign_matrix import build_run_config
    from simulation.simulation_engine import SimulationEngine

    def zustand():
        e = SimulationEngine(build_run_config("ABC+ABC", 7, sim_time=1))
        return [e.rng_streams.get(n).bit_generator.state
                for n in ("requests", "service", "placement")]

    vorher = zustand()
    rp.benchmarke_policy("RR+RR", ze=50)
    assert zustand() == vorher


def test_estimate_runtime_mode_writes_nothing(tmp_path, monkeypatch, capsys):
    from experiments import run_final_campaign as runner

    monkeypatch.setattr(runner, "benchmarke_alle",
                        lambda policies=None: list(SYNTH))
    ziel = tmp_path / "final"

    code = runner.main(["--estimate-runtime", "--output-dir", str(ziel),
                        "--policy", "ABC+ABC"])
    ausgabe = capsys.readouterr().out

    assert code == 0
    assert "RUNTIME PREFLIGHT" in ausgabe
    assert "kein finaler Run" in ausgabe
    assert not ziel.exists() or not any(ziel.iterdir()), (
        "Der Schaetzmodus hat geschrieben.")


def test_estimate_runtime_mode_does_not_touch_the_status_file(tmp_path,
                                                              monkeypatch):
    from experiments import run_final_campaign as runner

    monkeypatch.setattr(runner, "benchmarke_alle",
                        lambda policies=None: list(SYNTH))
    ziel = tmp_path / "final"
    ziel.mkdir()
    (ziel / runner.STATUS_DATEI).write_text('{"x": {"state": "completed"}}')
    vorher = (ziel / runner.STATUS_DATEI).read_text()

    runner.main(["--estimate-runtime", "--output-dir", str(ziel)])

    assert (ziel / runner.STATUS_DATEI).read_text() == vorher
