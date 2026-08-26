# tests/test_campaign_resume.py
"""
Betriebsfestigkeit des Kampagnentreibers.

Die finale Kampagne laeuft rund 30 Stunden unbeaufsichtigt. Ein Fehler im
Wiederaufsetzen kostet dann nicht Minuten, sondern die gesamte Rechenzeit.
Am 2026-08-24 wurden drei solche Pfade deterministisch nachgewiesen:

    1. Gezielter Retry eines fehlgeschlagenen Laufs
       (`--policy X --seed Y --resume`) oeffnete den Writer im
       SCHREIBmodus und schnitt die 49 fertigen Laeufe ab.
       Reproduziert: 51 -> 2 Zeilen in `runs.csv`, Exitcode 0.
    2. Voller `--resume` nach einem Fehlschlag liess die Zeile des
       abgebrochenen Versuchs stehen und haengte den geglueckten an —
       zwei wissenschaftliche Replikationen desselben Seeds.
    3. Eine beschaedigte `campaign_status.json` galt als „keine Laeufe
       vorhanden" und fuehrte ebenfalls zum Abschneiden.

Diese Tests halten alle drei fest. Sie rechnen keine echten Simulationen —
gefaked wird ausschliesslich `fahre_lauf`, also der teure Teil. Export,
Bereinigung, Statusfuehrung und Integritaetspruefung laufen echt.
"""

import csv
import json
import types

import pytest

import experiments.run_final_campaign as runner
from experiments.campaign_matrix import (
    FINAL_SEEDS, FINAL_T_FINAL, FINAL_T_MEASURE_START, final_matrix,
)
from experiments.run_export import (
    REQUEST_FIELDS, RETRIEVAL_FIELDS, RUN_FIELDS,
)


# ====================================================================== #
# Ein Engine-Doppelgaenger, der dem echten Export genuegt
# ====================================================================== #

class _Station:
    def __init__(self, station_id):
        self.station_id = station_id

    def get_utilization(self, t):
        return 0.5


class _Metrics:
    def __init__(self, config, anzahl=4):
        start = config.t_measure_start or 0
        # Haelfte vor, Haelfte im Fenster - so ist die Fensterzahl echt
        # kleiner als die Gesamtzahl und der Test kann nicht trivial passen.
        zeiten = ([max(0, start - 10)] * anzahl
                  + [start + 1 + i for i in range(anzahl)])
        self.retrievals = [{
            "t_pickstation": t, "request_id": i, "bin_id": i,
            "abc_class": "A", "access_count_before": 0, "level": 0,
            "stack_height": 2, "levels_from_top": 0, "blocking_bins": 0,
            "blockers_returned": True, "batch_size": 1,
            "t_retrieval_start": t, "dig_duration": 1, "pickstation": 0,
            "robot_id": 0,
        } for i, t in enumerate(zeiten)]
        self.completed_requests = [{
            "time": t, "bin_id": i, "action_type": "ARRIVAL",
            "request_id": i, "arrival_time": max(0, t - 5),
            "earliest_time": 0, "latest_time": t + 5, "tardiness": 0,
            "deadline_missed": False, "time_arrival_to_pickstation": 5,
        } for i, t in enumerate(zeiten)]
        self._snapshots = [
            {"time": t, "abc_level_A_0": 0.5, "abc_level_C_0": 0.5}
            for t in (0, 100, 200)
        ]

    def summary(self):
        return {}

    def get_distribution_timeseries(self):
        return self._snapshots


class _FakeEngine:
    def __init__(self, config):
        self.config = config
        self.state = types.SimpleNamespace(
            t=config.simulation_time,
            pickstations=[_Station(0), _Station(1)])
        self.metrics = _Metrics(config)
        self.rng_streams = types.SimpleNamespace(
            _streams={"requests": None, "service": None})


@pytest.fixture
def treiber(monkeypatch):
    """
    Ersetzt nur `fahre_lauf`. Alles danach ist echter Code.

    `fehler` steuert, welche `run_id`s scheitern sollen.
    """
    zustand = {"fehler": set(), "gerechnet": []}

    def fake_lauf(eintrag, log_ordner, bisher=None):
        log_ordner.mkdir(parents=True, exist_ok=True)
        hauptlog = log_ordner / f"{eintrag['run_id']}.log"
        if (bisher and bisher.get("state") in ("failed", "export_failed")
                and hauptlog.exists()):
            hauptlog.replace(log_ordner
                             / f"{eintrag['run_id']}"
                               f".failed-{bisher.get('versuche', 1)}.log")
        hauptlog.write_text(f"log von {eintrag['run_id']}\n")
        zustand["gerechnet"].append(eintrag["run_id"])
        fehler = ("RuntimeError: absichtlich"
                  if eintrag["run_id"] in zustand["fehler"] else None)
        return _FakeEngine(eintrag["config"]), fehler, 1.0, "x\n"

    monkeypatch.setattr(runner, "fahre_lauf", fake_lauf)
    # Der Preflight-Benchmark wuerde echte Simulationen rechnen.
    monkeypatch.setattr(runner, "preflight",
                        lambda *a, **k: (None, True))
    return zustand


def lies(ordner, name):
    with open(ordner / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def zeilen_je_run(ordner, name="runs.csv"):
    from collections import Counter
    return Counter(z["run_id"] for z in lies(ordner, name))


def bestuecke(ordner, kombinationen, fehlgeschlagen=()):
    """Legt einen Kampagnenbestand an, als haette ein Prozess ihn erzeugt."""
    ordner.mkdir(parents=True, exist_ok=True)
    status = {}
    with open(ordner / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            if rid in fehlgeschlagen:
                status[rid] = {"state": "failed", "policy": pol, "seed": sd,
                               "smoke": False, "versuche": 1,
                               "error": "RuntimeError: absichtlich"}
                continue
            w.writerow({**{f: "" for f in RUN_FIELDS}, "run_id": rid,
                        "policy": pol, "seed": sd,
                        "measurement_mode": "time_window",
                        "t_measure_start": FINAL_T_MEASURE_START,
                        "t_final": FINAL_T_FINAL,
                        "measurement_retrievals": 4,
                        "rq4_status": "converged"})
            status[rid] = {"state": "completed", "policy": pol, "seed": sd,
                           "smoke": False, "versuche": 1, "error": None}
    # `retrievals.csv` mit dem ECHTEN Schema anlegen. Ein verkuerzter Kopf
    # wuerde beim Anhaengen durch den echten Writer die Spalten verschieben
    # — der Test wuerde dann etwas anderes messen als gemeint.
    with open(ordner / "retrievals.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RETRIEVAL_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            if rid in fehlgeschlagen:
                continue
            for i in range(5):
                drin = i < 4
                w.writerow({
                    **{f: "" for f in RETRIEVAL_FIELDS},
                    "run_id": rid, "policy": pol, "seed": sd,
                    "t_pickstation": (FINAL_T_MEASURE_START + 1 + i if drin
                                      else FINAL_T_MEASURE_START - 10),
                    "in_measurement_window": drin})
    with open(ordner / "requests.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REQUEST_FIELDS)
        w.writeheader()
        for rid, pol, sd in kombinationen:
            if rid not in fehlgeschlagen:
                w.writerow({**{f: "" for f in REQUEST_FIELDS},
                            "run_id": rid, "policy": pol, "seed": sd})
    with open(ordner / "distribution.csv", "w", newline="",
              encoding="utf-8") as fh:
        fh.write("run_id,policy,seed,time,abc_level_A_0,abc_level_C_0\n")
        for rid, pol, sd in kombinationen:
            if rid not in fehlgeschlagen:
                fh.write(f"{rid},{pol},{sd},0,0.5,0.5\n")
    (ordner / "run_meta.json").write_text(json.dumps(
        [{"run_id": r, "policy": p, "seed": s}
         for r, p, s in kombinationen if r not in fehlgeschlagen]))
    (ordner / runner.STATUS_DATEI).write_text(json.dumps(status))
    return status


# ====================================================================== #
# TEST A — Fehlschlag, dann voller Resume
# ====================================================================== #

def test_failed_run_is_not_exported_as_a_second_replication(treiber, tmp_path):
    """
    A ok, B ok, C faellt -> `--resume` -> C erneut.

    Danach muss jeder Lauf GENAU EINMAL in jeder laufbezogenen Datei
    stehen. Der abgebrochene Versuch ist Betriebshistorie, keine zweite
    Messreihe.
    """
    ziel = tmp_path / "final"
    argumente = ["--output-dir", str(ziel), "--policy", "baseline_reference",
                 "--policy", "RR+RR", "--policy", "LR+NR", "--seed", "42"]

    treiber["fehler"] = {"LR+NR__seed42"}
    code1 = runner.main(argumente)
    assert code1 == 1, "Ein fehlgeschlagener Lauf muss Exit 1 liefern."

    treiber["fehler"] = set()
    code2 = runner.main(argumente + ["--resume"])

    assert code2 == 0
    erwartete_ids = {"baseline_reference__seed42", "RR+RR__seed42",
                     "LR+NR__seed42"}

    # runs.csv und run_meta.json tragen GENAU EINE Zeile je Lauf.
    zahl = zeilen_je_run(ziel, "runs.csv")
    assert set(zahl) == erwartete_ids
    assert all(v == 1 for v in zahl.values()), (
        f"runs.csv: doppelte Replikation {dict(zahl)}")

    # retrievals/requests tragen eine Zeile je Ereignis. Entscheidend ist,
    # dass der wiederholte Lauf nicht die doppelte Menge hinterlaesst.
    for name in ("retrievals.csv", "requests.csv"):
        zahl = zeilen_je_run(ziel, name)
        assert set(zahl) == erwartete_ids
        einzeln = zahl["baseline_reference__seed42"]
        assert zahl["LR+NR__seed42"] == einzeln, (
            f"{name}: der wiederholte Lauf hat {zahl['LR+NR__seed42']} "
            f"Zeilen statt {einzeln} — Reste des Fehlversuchs.")

    meta = json.loads((ziel / "run_meta.json").read_text())
    ids = [m["run_id"] for m in meta]
    assert len(ids) == len(set(ids)) == 3


def test_the_failed_attempt_is_kept_as_operational_history(treiber, tmp_path):
    """Die Ursache des Fehlschlags bleibt nachlesbar — im Log, nicht in den
    wissenschaftlichen Daten."""
    ziel = tmp_path / "final"
    argumente = ["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "42"]

    treiber["fehler"] = {"ABC+ABC__seed42"}
    runner.main(argumente)
    treiber["fehler"] = set()
    runner.main(argumente + ["--resume"])

    logs = {p.name for p in (ziel / "logs").iterdir()}
    assert "ABC+ABC__seed42.log" in logs
    assert "ABC+ABC__seed42.failed-1.log" in logs, (
        "Das Log des Fehlversuchs wurde ueberschrieben.")
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["ABC+ABC__seed42"]["state"] == "completed"
    assert status["ABC+ABC__seed42"]["versuche"] == 2


def test_a_failed_run_never_reaches_the_scientific_files(treiber, tmp_path):
    ziel = tmp_path / "final"
    treiber["fehler"] = {"ABC+ABC__seed42"}

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--policy", "RR+RR", "--seed", "42"])

    assert code == 1
    ids = {z["run_id"] for z in lies(ziel, "runs.csv")}
    assert "ABC+ABC__seed42" not in ids
    assert "RR+RR__seed42" in ids


# ====================================================================== #
# TEST B — gezielter Retry in einem vollen Bestand
# ====================================================================== #

def test_targeted_resume_never_truncates_the_existing_campaign(treiber,
                                                               tmp_path):
    """
    Der Fall aus dem Arbeitsauftrag: 49 Laeufe fertig, einer fehlgeschlagen,
    gezielter Retry.

    Vor der Behebung loeschte genau dieser Aufruf alle 49 Ergebnisse und
    meldete Erfolg.
    """
    ziel = tmp_path / "final"
    alle = final_matrix()
    bestuecke(ziel, alle, fehlgeschlagen={"ABC+ABC__seed7"})

    vorher = {z["run_id"] for z in lies(ziel, "runs.csv")}
    assert len(vorher) == 49

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "7", "--resume"])

    nachher = zeilen_je_run(ziel, "runs.csv")
    assert code == 0, "Der Retry sollte durchlaufen."
    assert len(nachher) == 50, f"nur {len(nachher)} Laeufe uebrig"
    assert all(v == 1 for v in nachher.values())
    assert vorher <= set(nachher), "Bestehende Laeufe sind verschwunden."
    assert "ABC+ABC__seed7" in nachher


def test_targeted_resume_leaves_completed_runs_untouched(treiber, tmp_path):
    """Die 49 fertigen Zeilen muessen zeichengenau erhalten bleiben."""
    ziel = tmp_path / "final"
    alle = final_matrix()
    bestuecke(ziel, alle, fehlgeschlagen={"ABC+ABC__seed7"})

    vorher = {z["run_id"]: z for z in lies(ziel, "runs.csv")}

    runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "7", "--resume"])

    nachher = {z["run_id"]: z for z in lies(ziel, "runs.csv")}
    for kennung, zeile in vorher.items():
        assert nachher[kennung] == zeile, f"{kennung} wurde veraendert"
    assert treiber["gerechnet"] == ["ABC+ABC__seed7"], (
        "Es wurde mehr gerechnet als der eine Retry.")


def test_headers_are_never_duplicated_on_resume(treiber, tmp_path):
    ziel = tmp_path / "final"
    bestuecke(ziel, final_matrix(), fehlgeschlagen={"ABC+ABC__seed7"})

    runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "7", "--resume"])

    for name in ("runs.csv", "retrievals.csv", "requests.csv"):
        zeilen = (ziel / name).read_text().splitlines()
        kopf = zeilen[0]
        assert sum(1 for z in zeilen[1:] if z == kopf) == 0


# ====================================================================== #
# Beschaedigte Statusdatei
# ====================================================================== #

def test_a_corrupt_status_file_fails_fast_instead_of_truncating(treiber,
                                                                tmp_path):
    ziel = tmp_path / "final"
    bestuecke(ziel, final_matrix()[:10])
    vorher = (ziel / "runs.csv").read_text()
    (ziel / runner.STATUS_DATEI).write_text("{ kein JSON")

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "1", "--resume"])

    assert code == 2
    assert (ziel / "runs.csv").read_text() == vorher, "Bestand veraendert!"


def test_status_file_keeps_a_backup(treiber, tmp_path):
    ziel = tmp_path / "final"
    runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "1", "--seed", "2"])

    assert (ziel / (runner.STATUS_DATEI + ".bak")).exists()


# ====================================================================== #
# Exportfehler
# ====================================================================== #

def test_an_export_failure_never_marks_the_run_completed(treiber, tmp_path,
                                                         monkeypatch):
    """
    Ein Lauf gilt nur als fertig, wenn seine Daten wirklich geschrieben
    wurden. Sonst waere er beim Wiederaufsetzen unsichtbar und fehlte am
    Ende in der Matrix.
    """
    from experiments.run_export import ExperimentWriter

    echt = ExperimentWriter.add_run

    def kaputt(self, run_id, *a, **k):
        if run_id == "RR+RR__seed42":
            raise OSError("No space left on device")
        return echt(self, run_id, *a, **k)

    monkeypatch.setattr(ExperimentWriter, "add_run", kaputt)
    ziel = tmp_path / "final"

    code = runner.main(["--output-dir", str(ziel), "--policy",
                        "baseline_reference", "--policy", "RR+RR",
                        "--seed", "42"])

    assert code == 1
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["RR+RR__seed42"]["state"] == "export_failed"
    assert status["baseline_reference__seed42"]["state"] == "completed"


# ====================================================================== #
# Weitere Betriebsfaelle
# ====================================================================== #

def test_unknown_seed_is_rejected_by_the_cli(treiber, tmp_path):
    """`--seed 5` gehoert nicht zur eingefrorenen Matrix."""
    with pytest.raises(SystemExit):
        runner.main(["--output-dir", str(tmp_path / "x"),
                     "--policy", "ABC+ABC", "--seed", "5"])


def test_all_frozen_seeds_are_accepted(treiber, tmp_path):
    for seed in FINAL_SEEDS:
        eintraege = runner.plan(["ABC+ABC"], [seed])
        assert eintraege[0]["config"].random_seed == seed


def test_run_meta_is_written_after_every_run(treiber, tmp_path):
    """
    Nicht erst beim Schliessen.

    Ein abgebrochener Prozess haette sonst gefuellte CSVs und gar keine
    Metadaten hinterlassen.
    """
    from experiments.run_export import ExperimentWriter

    ziel = tmp_path / "final"
    gesehen = []
    echt = ExperimentWriter.add_run

    def beobachte(self, run_id, *a, **k):
        ergebnis = echt(self, run_id, *a, **k)
        meta_datei = self.dir / "run_meta.json"
        gesehen.append(len(json.loads(meta_datei.read_text()))
                       if meta_datei.exists() else 0)
        return ergebnis

    ExperimentWriter.add_run = beobachte
    try:
        runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                     "--seed", "1", "--seed", "2", "--seed", "3"])
    finally:
        ExperimentWriter.add_run = echt

    assert gesehen == [1, 2, 3], (
        f"run_meta.json wuchs nicht je Lauf: {gesehen}")
