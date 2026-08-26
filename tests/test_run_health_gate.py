# tests/test_run_health_gate.py
"""
Das letzte Gate: ein formal fertiger Lauf ist noch kein gueltiger Lauf.

Ein Lauf kann technisch bis `T_final` durchlaufen und trotzdem unterwegs
eine harte Correctness-/Liveness-Verletzung gehabt haben. Er darf dann nicht
stillschweigend als wissenschaftliche Replikation in den finalen Daten
landen.

Geprueft werden ausschliesslich die zwei eingefrorenen harten Signale:

    move_recovery_unresolved    eine Bewegungs-Recovery scheiterte
    task_deadlock               ein Task-Deadlock wurde erkannt

Ausdruecklich KEIN Performancefilter. Die Tests unten belegen beide
Richtungen: die Verletzung blockiert, und niedriger Durchsatz,
`not_converged` oder erfolgreiche Recoveries blockieren NICHT.

Befund 2026-08-24
-----------------
Die frueheren Zaehler suchten die Zeichenketten `"[MOVE_RECOVERY]"` und
`"MOVE_RECOVERY_UNRESOLVED"`. Beide werden von der Simulation nie
ausgegeben — die Groesse war strukturell immer 0 und konnte gar nicht
anschlagen. `test_the_production_markers_still_exist` koppelt die Zaehler
jetzt an den Produktionscode, damit ein Umbenennen auffaellt statt die
Messgroesse still zu toeten.
"""

import json
import types
from pathlib import Path

import pytest

import experiments.run_final_campaign as runner
from experiments.campaign_matrix import final_matrix
from experiments.run_export import RUN_FIELDS
from experiments.run_health import (
    HARTE_SIGNALE, MARKER_MOVE_STALL_RECOVERY, MARKER_MOVE_STALL_UNRESOLVED,
    MARKER_TASK_DEADLOCK, evaluate_run_health, health_aus_log,
    zaehle_health_signale,
)

from tests.test_campaign_resume import (  # noqa: F401  (Fixture-Import)
    _FakeEngine, bestuecke, lies, treiber, zeilen_je_run,
)


# ====================================================================== #
# Die Marker muessen im Produktionscode wirklich vorkommen
# ====================================================================== #

def test_the_production_markers_still_exist():
    """
    Die Kopplung, die vorher fehlte.

    Zaehlt der Export einen String, den die Simulation nicht schreibt,
    ist die Messgroesse tot — genau das war bei
    `MOVE_RECOVERY_UNRESOLVED` der Fall. Dieser Test schlaegt an, sobald
    jemand einen Marker umbenennt.
    """
    quelle = (Path(__file__).resolve().parents[1]
              / "simulation" / "event_handler.py").read_text()

    assert MARKER_MOVE_STALL_RECOVERY in quelle
    assert MARKER_MOVE_STALL_UNRESOLVED in quelle
    assert MARKER_TASK_DEADLOCK in quelle


def wirksame_stringliterale(pfad):
    """
    Alle Stringliterale eines Moduls OHNE Docstrings.

    Die Unterscheidung ist wichtig: `run_health.py` beschreibt den alten,
    toten Zaehler in seinem Docstring ausfuehrlich — das ist erwuenschte
    Dokumentation. Verboten ist nur, ihn wieder zu BENUTZEN.
    """
    import ast

    baum = ast.parse(pfad.read_text())
    docstrings = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef)):
            erst = knoten.body[0] if knoten.body else None
            if (isinstance(erst, ast.Expr)
                    and isinstance(erst.value, ast.Constant)
                    and isinstance(erst.value.value, str)):
                docstrings.add(id(erst.value))
    return {k.value for k in ast.walk(baum)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
            and id(k) not in docstrings}


def test_the_old_counter_strings_are_never_used_again():
    """
    Die alten, nie erzeugten Zeichenketten duerfen nicht mehr gezaehlt
    werden — beschrieben werden duerfen sie sehr wohl.
    """
    wurzel = Path(__file__).resolve().parents[1]
    tot = {"MOVE_RECOVERY_UNRESOLVED", "[MOVE_RECOVERY]"}

    for datei in (wurzel / "experiments" / "run_final_campaign.py",
                  wurzel / "experiments" / "run_health.py",
                  wurzel / "experiments" / "run_export.py"):
        benutzt = wirksame_stringliterale(datei) & tot
        assert not benutzt, (
            f"{datei.name} benutzt wieder {benutzt} — Strings, die die "
            f"Simulation nie ausgibt.")


# ====================================================================== #
# Die reine Bewertungsfunktion
# ====================================================================== #

def test_a_clean_run_is_healthy():
    ergebnis = evaluate_run_health(
        {"move_stall_recoveries": 0, "move_recovery_unresolved": 0,
         "task_deadlock": 0})

    assert ergebnis["healthy"] is True
    assert ergebnis["violations"] == []


def test_unresolved_recovery_is_a_hard_violation():
    ergebnis = evaluate_run_health({"move_recovery_unresolved": 1})

    assert ergebnis["healthy"] is False
    assert ergebnis["violations"] == ["move_recovery_unresolved=1"]


def test_task_deadlock_is_a_hard_violation():
    ergebnis = evaluate_run_health({"task_deadlock": 1})

    assert ergebnis["healthy"] is False
    assert ergebnis["violations"] == ["task_deadlock=1"]


def test_successful_recoveries_alone_are_not_a_violation():
    """
    Ein erfolgreich behandelter Recovery-Fall ist kein Fehler.

    Genau diese Verwechslung wuerde aus dem Correctness-Gate einen
    Robustheitsfilter machen.
    """
    ergebnis = evaluate_run_health(
        {"move_stall_recoveries": 42, "move_recovery_unresolved": 0,
         "task_deadlock": 0})

    assert ergebnis["healthy"] is True
    assert ergebnis["move_stall_recoveries"] == 42


def test_only_the_two_frozen_signals_gate():
    """Die Liste der harten Signale ist klein und eingefroren."""
    assert HARTE_SIGNALE == ("move_recovery_unresolved", "task_deadlock")

    # Alles andere, was in Logs vorkommt, darf nicht gaten.
    harmlos = {"deadlock_detected": 200, "unbury": 5,
               "drop_bury_redirect": 300, "stale_pickup_no_task": 7,
               "move_stall_recoveries": 12}
    assert evaluate_run_health(harmlos)["healthy"] is True


# ====================================================================== #
# Zaehlen aus dem Log
# ====================================================================== #

GESUNDES_LOG = (
    "[DEADLOCK] Detected cycle a->b\n"
    "[DEADLOCK] Detected cycle b->c\n"
    "[UNBURY] t=10 bin=3\n"
    "[REPLAN][DROP_BURY] t=11\n"
    f"{MARKER_MOVE_STALL_RECOVERY} t=12 robot=1 grund=stall\n"
)

LOG_MIT_UNGELOESTEM_STALL = GESUNDES_LOG + (
    f"{MARKER_MOVE_STALL_RECOVERY} t=13 robot=2 "
    f"{MARKER_MOVE_STALL_UNRESOLVED} (Kandidaten: [3])\n"
)

LOG_MIT_TASK_DEADLOCK = GESUNDES_LOG + (
    f"{MARKER_TASK_DEADLOCK}[RESTORE_BURIED] t=14 task=99\n"
)


def test_counting_separates_attempts_from_failures():
    zahlen = zaehle_health_signale(LOG_MIT_UNGELOESTEM_STALL)

    assert zahlen["move_stall_recoveries"] == 2, "beide Versuche zaehlen"
    assert zahlen["move_recovery_unresolved"] == 1, "nur der gescheiterte"
    assert zahlen["task_deadlock"] == 0


def test_a_healthy_log_yields_no_violation():
    ergebnis = health_aus_log(GESUNDES_LOG)

    assert ergebnis["healthy"] is True
    assert ergebnis["move_stall_recoveries"] == 1


def test_normal_deadlock_detections_are_not_task_deadlocks():
    """
    `[DEADLOCK] Detected` ist die NORMALE, erfolgreich behandelte
    Erkennung. Sie darf nicht mit `[TASK_DEADLOCK]` verwechselt werden —
    in gesunden Laeufen kommt sie 0 bis 9 Mal vor.
    """
    log = "[DEADLOCK] Detected cycle\n" * 50

    assert health_aus_log(log)["healthy"] is True
    assert zaehle_health_signale(log)["task_deadlock"] == 0


def test_task_deadlock_is_counted_from_the_real_marker():
    assert health_aus_log(LOG_MIT_TASK_DEADLOCK)["task_deadlock"] == 1
    assert health_aus_log(LOG_MIT_TASK_DEADLOCK)["healthy"] is False


# ====================================================================== #
# Das Gate im Kampagnentreiber
# ====================================================================== #

@pytest.fixture
def treiber_mit_log(monkeypatch):
    """
    Wie `treiber`, aber das Log je Lauf ist steuerbar.

    Gefaked wird nur `fahre_lauf` — Gate, Export, Status und
    Abschlusspruefung laufen echt.
    """
    zustand = {"logs": {}, "gerechnet": []}

    def fake_lauf(eintrag, log_ordner, bisher=None):
        log_ordner.mkdir(parents=True, exist_ok=True)
        hauptlog = log_ordner / f"{eintrag['run_id']}.log"
        if (bisher and bisher.get("state") in runner.GESCHEITERT
                and hauptlog.exists()):
            hauptlog.replace(log_ordner / f"{eintrag['run_id']}"
                                          f".failed-{bisher.get('versuche', 1)}"
                                          f".log")
        log = zustand["logs"].get(eintrag["run_id"], GESUNDES_LOG)
        hauptlog.write_text(log)
        zustand["gerechnet"].append(eintrag["run_id"])
        return _FakeEngine(eintrag["config"]), None, 1.0, log

    monkeypatch.setattr(runner, "fahre_lauf", fake_lauf)
    monkeypatch.setattr(runner, "preflight", lambda *a, **k: (None, True))
    return zustand


def test_an_unresolved_recovery_never_becomes_completed(treiber_mit_log,
                                                        tmp_path, capsys):
    ziel = tmp_path / "final"
    treiber_mit_log["logs"]["ABC+ABC__seed42"] = LOG_MIT_UNGELOESTEM_STALL

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--policy", "RR+RR", "--seed", "42"])
    ausgabe = capsys.readouterr().out

    assert code != 0, "Ein Health-Failure muss die Kampagne scheitern lassen."
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["ABC+ABC__seed42"]["state"] == "health_failed"
    assert status["ABC+ABC__seed42"]["health_violations"] == [
        "move_recovery_unresolved=1"]
    assert status["RR+RR__seed42"]["state"] == "completed"

    ids = {z["run_id"] for z in lies(ziel, "runs.csv")}
    assert "ABC+ABC__seed42" not in ids, (
        "Der ungesunde Lauf steht in den wissenschaftlichen Daten.")
    assert "RR+RR__seed42" in ids
    assert "[HEALTH]" in ausgabe


def test_a_task_deadlock_never_becomes_completed(treiber_mit_log, tmp_path):
    ziel = tmp_path / "final"
    treiber_mit_log["logs"]["ABC+ABC__seed42"] = LOG_MIT_TASK_DEADLOCK

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "42"])

    assert code != 0
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["ABC+ABC__seed42"]["state"] == "health_failed"
    assert status["ABC+ABC__seed42"]["task_deadlock"] == 1
    assert not (ziel / "runs.csv").exists() or not [
        z for z in lies(ziel, "runs.csv")
        if z["run_id"] == "ABC+ABC__seed42"]


def test_a_healthy_run_is_completed_as_before(treiber_mit_log, tmp_path):
    ziel = tmp_path / "final"

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "42"])

    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert code == 0
    assert status["ABC+ABC__seed42"]["state"] == "completed"
    zeile = lies(ziel, "runs.csv")[0]
    assert zeile["move_stall_recoveries"] == "1"
    assert zeile["move_recovery_unresolved"] == "0"
    assert zeile["task_deadlock"] == "0"


def test_successful_recoveries_do_not_block_a_run(treiber_mit_log, tmp_path):
    """`MOVE_STALL_RECOVERY > 0`, aber keine gescheiterte — bleibt gueltig."""
    ziel = tmp_path / "final"
    treiber_mit_log["logs"]["ABC+ABC__seed42"] = (
        f"{MARKER_MOVE_STALL_RECOVERY} t=1 robot=0\n" * 25)

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "42"])

    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert code == 0
    assert status["ABC+ABC__seed42"]["state"] == "completed"
    assert lies(ziel, "runs.csv")[0]["move_stall_recoveries"] == "25"


def test_poor_performance_alone_never_blocks_a_run(treiber_mit_log, tmp_path):
    """
    Der entscheidende Gegenbeweis: das Gate ist kein Performancefilter.

    Der Lauf hat wenige Retrievals und `not_converged` — beides legitime
    Simulationsergebnisse — aber keine harte Verletzung.
    """
    ziel = tmp_path / "final"
    treiber_mit_log["logs"]["ABC+ABC__seed42"] = (
        "[DEADLOCK] Detected cycle\n" * 200)

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "42"])

    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    zeile = lies(ziel, "runs.csv")[0]
    assert code == 0
    assert status["ABC+ABC__seed42"]["state"] == "completed"
    assert zeile["rq4_status"] == "not_converged", (
        "Testaufbau: der Lauf soll gerade NICHT konvergiert sein.")
    assert int(zeile["physical_retrievals"]) < 20, (
        "Testaufbau: der Lauf soll wenige Retrievals haben.")


# ====================================================================== #
# Resume nach einem Health-Failure
# ====================================================================== #

def test_resume_after_a_health_failure_leaves_no_duplicate(treiber_mit_log,
                                                           tmp_path):
    ziel = tmp_path / "final"
    argumente = ["--output-dir", str(ziel), "--policy", "baseline_reference",
                 "--policy", "ABC+ABC", "--seed", "42"]

    treiber_mit_log["logs"]["ABC+ABC__seed42"] = LOG_MIT_TASK_DEADLOCK
    assert runner.main(argumente) != 0

    treiber_mit_log["logs"]["ABC+ABC__seed42"] = GESUNDES_LOG
    code = runner.main(argumente + ["--resume"])

    assert code == 0
    zahl = zeilen_je_run(ziel, "runs.csv")
    assert set(zahl) == {"baseline_reference__seed42", "ABC+ABC__seed42"}
    assert all(v == 1 for v in zahl.values()), f"Duplikat: {dict(zahl)}"

    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["ABC+ABC__seed42"]["state"] == "completed"
    assert status["ABC+ABC__seed42"]["versuche"] == 2
    logs = {p.name for p in (ziel / "logs").iterdir()}
    assert "ABC+ABC__seed42.failed-1.log" in logs, (
        "Das Log des ungesunden Versuchs wurde ueberschrieben.")


def test_targeted_resume_after_health_failure_keeps_the_other_runs(
        treiber_mit_log, tmp_path):
    """
    49 Laeufe fertig, einer `health_failed`, gezielter Retry.

    Kein Truncate, keine Dublette, die uebrigen 49 feldweise unveraendert.
    """
    ziel = tmp_path / "final"
    alle = final_matrix()
    bestuecke(ziel, alle, fehlgeschlagen={"ABC+ABC__seed7"})
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    status["ABC+ABC__seed7"] = {
        "state": "health_failed", "policy": "ABC+ABC", "seed": 7,
        "smoke": False, "versuche": 1,
        "health_violations": ["task_deadlock=1"], "task_deadlock": 1}
    (ziel / runner.STATUS_DATEI).write_text(json.dumps(status))
    vorher = {z["run_id"]: z for z in lies(ziel, "runs.csv")}
    assert len(vorher) == 49

    code = runner.main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                        "--seed", "7", "--resume"])

    nachher = {z["run_id"]: z for z in lies(ziel, "runs.csv")}
    assert code == 0
    assert len(nachher) == 50
    for kennung, zeile in vorher.items():
        assert nachher[kennung] == zeile, f"{kennung} wurde veraendert"
    assert treiber_mit_log["gerechnet"] == ["ABC+ABC__seed7"]
    neu = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert neu["ABC+ABC__seed7"]["state"] == "completed"
    assert neu["ABC+ABC__seed7"]["versuche"] == 2


def test_a_deterministic_health_failure_is_not_retried_automatically(
        treiber_mit_log, tmp_path, capsys):
    """
    Bleibt der Fehler bestehen, wird nicht endlos wiederholt und kein Seed
    ersetzt — der Runner endet mit Exit != 0 und benennt den Lauf.
    """
    ziel = tmp_path / "final"
    argumente = ["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "42"]
    treiber_mit_log["logs"]["ABC+ABC__seed42"] = LOG_MIT_TASK_DEADLOCK

    assert runner.main(argumente) != 0
    capsys.readouterr()
    code = runner.main(argumente + ["--resume"])
    ausgabe = capsys.readouterr().out

    assert code != 0
    assert treiber_mit_log["gerechnet"].count("ABC+ABC__seed42") == 2, (
        "Genau ein Retry je Aufruf, keine automatische Schleife.")
    assert "ABC+ABC__seed42" in ausgabe
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    assert status["ABC+ABC__seed42"]["versuche"] == 2
    assert set(status) == {"ABC+ABC__seed42"}, "Es wurde ein Seed ersetzt."


# ====================================================================== #
# Der Abschlusscheck kennt Health-Failures
# ====================================================================== #

def test_the_integrity_check_rejects_a_health_failed_run(tmp_path):
    from experiments.run_final_campaign import pruefe_integritaet

    ziel = tmp_path / "final"
    alle = final_matrix()
    bestuecke(ziel, alle)
    status = json.loads((ziel / runner.STATUS_DATEI).read_text())
    status["LR+NR__seed13"] = {"state": "health_failed", "policy": "LR+NR",
                               "seed": 13, "task_deadlock": 1}
    eintraege = [{"run_id": r, "policy": p, "seed": s} for r, p, s in alle]

    befunde = pruefe_integritaet(ziel, eintraege, status)

    assert any("Correctness-/Liveness-Verletzung" in b for b in befunde)


def test_the_integrity_check_rejects_a_nonzero_hard_signal_in_the_csv(
        tmp_path):
    """
    Auch ein von Hand zusammengefuehrter Bestand wird geprueft: steht in
    `runs.csv` ein Lauf mit `task_deadlock > 0`, schlaegt der Check an.
    """
    import csv

    from experiments.run_final_campaign import pruefe_integritaet

    ziel = tmp_path / "final"
    alle = final_matrix()
    status = bestuecke(ziel, alle)
    zeilen = list(csv.DictReader(open(ziel / "runs.csv")))
    zeilen[2]["task_deadlock"] = "1"
    with open(ziel / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        w.writeheader()
        w.writerows(zeilen)
    eintraege = [{"run_id": r, "policy": p, "seed": s} for r, p, s in alle]

    befunde = pruefe_integritaet(ziel, eintraege, status)

    assert any("task_deadlock" in b for b in befunde)
