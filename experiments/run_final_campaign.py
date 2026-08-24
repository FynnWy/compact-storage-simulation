#!/usr/bin/env python3
"""
Treiber der finalen 50-Run-Kampagne.

    5 Policies x 10 Seeds = 50 Runs,  jeder von t = 0 bis t = 30.000 ZE,
    ausgewertet ausschliesslich im Fenster [20.000, 30.000].

Warum ein neues Skript und nicht `run_experiments.py`
-----------------------------------------------------
`run_experiments.py` ist der historische Vergleichslauf und in fuenf Punkten
nicht der eingefrorene Versuchsplan: 2.000 ZE statt 30.000, fuenf alte Seeds
statt der zehn festgelegten, kein Messfenster, der alte Exporter, abweichende
Policy-Namen. Ihn umzubauen wuerde seine urspruengliche Funktion
verwischen — er bleibt unangetastet.

Was dieses Skript NICHT tut
---------------------------
Es fasst keine Simulationslogik an. Es liest den fertigen Lauf aus, wendet
die Offline-RQ4-Regel an und schreibt CSV/JSON. Es zieht keine Zufallszahl;
die CRN-Eigenschaft der Kampagne bleibt unberuehrt.

Aufruf
------
    # Planpruefung, rechnet nichts
    python3 -m experiments.run_final_campaign --dry-run --output-dir results/final

    # kurzer End-to-End-Rauchtest ueber denselben Pfad
    python3 -m experiments.run_final_campaign --smoke --output-dir /tmp/smoke

    # die echte Kampagne
    python3 -m experiments.run_final_campaign --output-dir results/final

    # Teilmenge / Fortsetzung
    python3 -m experiments.run_final_campaign --output-dir results/final \\
        --policy "ABC+ABC" --seed 7 --resume

Exitcode 0 nur, wenn jeder gerechnete Run fehlerfrei war.
"""

import argparse
import contextlib
import io
import json
import sys
import time
import traceback
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from experiments.campaign_matrix import (  # noqa: E402
    FINAL_POLICIES, FINAL_SEEDS, FINAL_SIMULATION_TIME, FINAL_T_FINAL,
    FINAL_T_MEASURE_START, build_run_config, check_final_config, check_matrix,
    final_matrix, run_id as make_run_id,
)
from experiments.run_export import (  # noqa: E402
    RUN_SCOPED_CSVS, ExperimentWriter, purge_runs,
)
from metrics.rq4_plateau import analyse_engine  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402

#: Der Rauchtest ist technisch klar vom FINAL-Modus getrennt: eigener
#: Horizont, eigenes Fenster, eigener Seed, und er weigert sich, in ein
#: Verzeichnis zu schreiben, das schon finale Ergebnisse enthaelt.
SMOKE_SIM_TIME = 600
SMOKE_T_MEASURE_START = 300
SMOKE_SEEDS = (42,)

STATUS_DATEI = "campaign_status.json"


# ====================================================================== #
# Plan
# ====================================================================== #

def plan(policies=None, seeds=None, smoke=False):
    """Die zu rechnenden Kombinationen samt Konfiguration."""
    if smoke:
        gewaehlt_policies = list(policies or FINAL_POLICIES)
        gewaehlt_seeds = list(seeds or SMOKE_SEEDS)
        sim_time = SMOKE_SIM_TIME
        t_start, t_ende = SMOKE_T_MEASURE_START, SMOKE_SIM_TIME
    else:
        gewaehlt_policies = list(policies or FINAL_POLICIES)
        gewaehlt_seeds = list(seeds or FINAL_SEEDS)
        sim_time = FINAL_SIMULATION_TIME
        t_start, t_ende = FINAL_T_MEASURE_START, FINAL_T_FINAL

    eintraege = []
    for policy in gewaehlt_policies:
        for seed in gewaehlt_seeds:
            eintraege.append({
                "run_id": make_run_id(policy, seed),
                "policy": policy,
                "seed": seed,
                "config": build_run_config(
                    policy, seed, sim_time=sim_time,
                    t_measure_start=t_start, t_final=t_ende),
            })
    return eintraege


# ====================================================================== #
# Statusdatei: Run-Level-Restart
# ====================================================================== #

class StatusKaputt(Exception):
    """Die Statusdatei ist unlesbar — das darf niemals stillschweigend
    als „keine Laeufe vorhanden" durchgehen."""


def lade_status(ordner: Path) -> dict:
    """
    Laedt `campaign_status.json`.

    Eine beschaedigte Datei fuehrt zu einer Ausnahme, NICHT zu einem leeren
    Wert. Die alte Fassung fing den `JSONDecodeError` und lieferte `{}`;
    daraufhin galten alle Laeufe als offen, der Writer oeffnete im
    Schreibmodus und loeschte den gesamten bisherigen Kampagnenbestand —
    ohne Fehlermeldung und mit Exitcode 0.
    """
    datei = ordner / STATUS_DATEI
    if not datei.exists():
        return {}
    try:
        inhalt = json.loads(datei.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise StatusKaputt(
            f"{datei} ist unlesbar ({exc}).\n"
            f"Die Datei sagt, welche Laeufe fertig sind. Sie zu ignorieren "
            f"wuerde bereits gerechnete Ergebnisse ueberschreiben.\n"
            f"Bitte pruefen und ggf. aus {STATUS_DATEI}.bak wiederherstellen."
        ) from exc
    if not isinstance(inhalt, dict):
        raise StatusKaputt(f"{datei} enthaelt kein Objekt, sondern "
                           f"{type(inhalt).__name__}.")
    return inhalt


def schreibe_status(ordner: Path, status: dict) -> None:
    """Atomar schreiben, vorherige Fassung als `.bak` behalten."""
    ziel = ordner / STATUS_DATEI
    if ziel.exists():
        try:
            (ordner / (STATUS_DATEI + ".bak")).write_text(ziel.read_text())
        except OSError:
            pass
    tmp = ordner / (STATUS_DATEI + ".tmp")
    tmp.write_text(json.dumps(status, indent=2, ensure_ascii=False))
    tmp.replace(ziel)


def hat_bestand(ordner: Path) -> bool:
    """Liegen im Ordner schon Kampagnendaten?"""
    return any((ordner / name).exists() and (ordner / name).stat().st_size
               for name in RUN_SCOPED_CSVS)


# ====================================================================== #
# Ein Lauf
# ====================================================================== #

def fahre_lauf(eintrag, log_ordner: Path, bisher=None):
    """
    Rechnet einen Lauf und leitet dessen Ausgabe in eine eigene Datei um.

    Gemessen wurden 150.000-200.000 Logzeilen je 30.000-ZE-Lauf. Auf der
    Konsole der Kampagne waeren das rund acht Millionen Zeilen; die
    Umleitung ist deshalb Pflicht und keine Kosmetik. Sie beeinflusst den
    Ablauf nicht — es wird nur `stdout` umgehaengt.

    Args:
        bisher: Statuseintrag eines frueheren Versuchs, falls vorhanden.
            Ein fehlgeschlagener Versuch behaelt sein Log unter
            `<run_id>.failed-<n>.log`; nur so bleibt die Ursache nach einem
            geglueckten Retry noch nachlesbar.
    """
    log_ordner.mkdir(parents=True, exist_ok=True)
    hauptlog = log_ordner / f"{eintrag['run_id']}.log"
    if bisher and bisher.get("state") in ("failed", "export_failed") \
            and hauptlog.exists():
        nummer = bisher.get("versuche", 1)
        hauptlog.replace(
            log_ordner / f"{eintrag['run_id']}.failed-{nummer}.log")

    engine = SimulationEngine(eintrag["config"])
    fehler = None
    begonnen = time.time()
    puffer = io.StringIO()

    with contextlib.redirect_stdout(puffer):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            fehler = f"{type(exc).__name__}: {exc}"
            puffer.write("\n" + traceback.format_exc())

    hauptlog.write_text(puffer.getvalue())
    return engine, fehler, round(time.time() - begonnen, 1), puffer.getvalue()


def zaehle(log: str, marke: str) -> int:
    return log.count(marke)


# ====================================================================== #
# Kampagne
# ====================================================================== #

def fahre_kampagne(eintraege, ordner: Path, resume: bool, smoke: bool,
                   preflight=None):
    ordner.mkdir(parents=True, exist_ok=True)
    status = lade_status(ordner)

    offen = [e for e in eintraege
             if status.get(e["run_id"], {}).get("state") != "completed"]
    uebersprungen = len(eintraege) - len(offen)
    if uebersprungen:
        print(f"[RESUME] {uebersprungen} bereits abgeschlossene Runs "
              f"uebersprungen")

    if not offen:
        print("[DONE] nichts zu tun, alle Runs sind abgeschlossen")
        return abschlusspruefung(ordner, eintraege, status, smoke)

    # ------------------------------------------------------------------ #
    # Schreibmodus: haengt am BESTAND, nicht an der Zahl uebersprungener
    # Laeufe.
    #
    # Die alte Regel lautete `"a" if (resume and uebersprungen) else "w"`.
    # Beim gezielten Wiederholen eines einzelnen fehlgeschlagenen Laufs
    # (`--policy X --seed Y --resume`) besteht der Plan aber nur aus genau
    # diesem einen Lauf: `uebersprungen` ist 0, der Modus wurde `"w"`, und
    # der Writer hat die Dateien mit allen 49 fertigen Laeufen abgeschnitten.
    # Am 2026-08-24 reproduziert: 51 -> 2 Zeilen in `runs.csv`, Exitcode 0.
    # ------------------------------------------------------------------ #
    bestand = hat_bestand(ordner)
    modus = "a" if bestand else "w"

    # Wiederholte Laeufe zuerst bereinigen, damit am Ende genau ein
    # wissenschaftlicher Datensatz je `run_id` steht.
    if bestand:
        entfernt = purge_runs(ordner, {e["run_id"] for e in offen})
        if entfernt:
            print(f"[PURGE] fruehere Zeilen wiederholter Laeufe entfernt: "
                  f"{entfernt}")

    fehlerhaft = []
    dauern = []

    with ExperimentWriter(ordner, mode=modus) as writer:
        for nummer, eintrag in enumerate(offen, start=1):
            kennung = eintrag["run_id"]
            print(f"[START] {nummer}/{len(offen)} {kennung}", flush=True)

            engine, fehler, dauer, log = fahre_lauf(eintrag, ordner / "logs",
                                                    status.get(kennung))

            grunddaten = {
                "policy": eintrag["policy"],
                "seed": eintrag["seed"],
                "t_end": engine.state.t,
                "physical_retrievals": len(engine.metrics.retrievals),
                "wall_seconds": dauer,
                "log_lines": len(log.splitlines()),
                "smoke": smoke,
                "versuche": status.get(kennung, {}).get("versuche", 0) + 1,
            }

            if fehler:
                # Ein abgebrochener Lauf ist KEIN wissenschaftlicher
                # Datensatz: sein Horizont ist unvollstaendig. Er wird
                # deshalb nicht exportiert, sondern nur in Status und Log
                # festgehalten (Betriebshistorie, keine Replikation).
                status[kennung] = {**grunddaten, "state": "failed",
                                   "rq4_status": None, "error": fehler}
                schreibe_status(ordner, status)
                fehlerhaft.append(kennung)
                print(f"[ERROR] {kennung}: {fehler}", flush=True)
                print(f"        nicht exportiert; Log unter "
                      f"logs/{kennung}.failed-{grunddaten['versuche']}.log",
                      flush=True)
                continue

            rq4 = analyse_engine(engine)
            recoveries = zaehle(log, "[MOVE_RECOVERY]")
            unresolved = zaehle(log, "MOVE_RECOVERY_UNRESOLVED")

            # Erst exportieren, dann als `completed` markieren. Schlaegt der
            # Export fehl, bleibt der Lauf offen und wird beim naechsten
            # `--resume` wiederholt — nie als fertig gemeldet.
            try:
                writer.add_run(kennung, eintrag["policy"], eintrag["seed"],
                               engine, rq4=rq4, error=None,
                               recoveries=recoveries, unresolved=unresolved)
            except Exception as exc:
                status[kennung] = {**grunddaten, "state": "export_failed",
                                   "rq4_status": rq4["status"],
                                   "error": f"{type(exc).__name__}: {exc}"}
                schreibe_status(ordner, status)
                print(f"[ERROR] {kennung}: Export fehlgeschlagen: {exc}",
                      flush=True)
                print("        Lauf gilt NICHT als abgeschlossen.",
                      flush=True)
                return 1

            status[kennung] = {**grunddaten, "state": "completed",
                               "rq4_status": rq4["status"], "error": None}
            schreibe_status(ordner, status)
            dauern.append((eintrag["policy"], dauer))

            print(f"[DONE ] {kennung} t_end={engine.state.t} "
                  f"retr={len(engine.metrics.retrievals)} "
                  f"rq4={rq4['status']} {dauer}s", flush=True)
            fortschritt(nummer, len(offen), dauern, offen, preflight)

    if fehlerhaft:
        print(f"\n[FAIL] {len(fehlerhaft)} Run(s) fehlgeschlagen: "
              f"{fehlerhaft}")
        print("Seeds werden NICHT ersetzt und Kombinationen NICHT "
              "uebersprungen. Ursache klaeren, dann --resume.")
        return 1

    print(f"\n[OK] {len(offen)} Run(s) gerechnet -> {ordner}")
    return abschlusspruefung(ordner, eintraege, status, smoke)


# ====================================================================== #
# Final Integrity Check
# ====================================================================== #

def pruefe_integritaet(ordner: Path, eintraege, status, smoke=False):
    """
    Prueft den fertigen Kampagnenbestand gegen den Versuchsplan.

    Der Runner soll nach ~30 Stunden nicht einfach „fertig" melden. Geprueft
    wird, was eine spaetere Auswertung stillschweigend falsch machen wuerde:
    fehlende oder doppelte Laeufe, Zeilen ohne bekannten Lauf, ein
    verrutschtes Messfenster, ein leerer RQ4-Status.

    Returns:
        Liste der Befunde. Leer heisst: alles in Ordnung.
    """
    befunde = []
    erwartet = {e["run_id"] for e in eintraege}
    voll = not smoke and len(eintraege) == len(FINAL_POLICIES) * len(FINAL_SEEDS)

    # --- runs.csv ---------------------------------------------------- #
    runs_datei = ordner / "runs.csv"
    if not runs_datei.exists():
        return [f"{runs_datei.name} fehlt"]
    with open(runs_datei, newline="", encoding="utf-8") as fh:
        runs = list(csv.DictReader(fh))

    ids = [r["run_id"] for r in runs]
    doppelt = sorted({i for i in ids if ids.count(i) > 1})
    fehlend = sorted(erwartet - set(ids))
    fremd = sorted(set(ids) - erwartet)
    if doppelt:
        befunde.append(f"doppelte run_id in runs.csv: {doppelt}")
    if fehlend:
        befunde.append(f"fehlende Laeufe in runs.csv: {fehlend}")
    if fremd:
        befunde.append(f"unerwartete Laeufe in runs.csv: {fremd}")

    if voll:
        if len(runs) != 50:
            befunde.append(f"{len(runs)} Zeilen in runs.csv statt 50")
        policies = {r["policy"] for r in runs}
        seeds = {int(r["seed"]) for r in runs}
        if policies != set(FINAL_POLICIES):
            befunde.append(f"Policy-Menge weicht ab: {sorted(policies)}")
        if seeds != set(FINAL_SEEDS):
            befunde.append(f"Seed-Menge weicht ab: {sorted(seeds)}")

    # --- Statusdatei --------------------------------------------------- #
    nicht_fertig = sorted(k for k in erwartet
                          if status.get(k, {}).get("state") != "completed")
    if nicht_fertig:
        befunde.append(f"nicht abgeschlossene Laeufe: {nicht_fertig}")

    # --- Fenster, RQ4, Fehlerspalte ------------------------------------ #
    soll_start = str(SMOKE_T_MEASURE_START if smoke else FINAL_T_MEASURE_START)
    soll_ende = str(SMOKE_SIM_TIME if smoke else FINAL_T_FINAL)
    for r in runs:
        kennung = r["run_id"]
        if r.get("measurement_mode") != "time_window":
            befunde.append(f"{kennung}: measurement_mode="
                           f"{r.get('measurement_mode')!r}")
        if r.get("t_measure_start") != soll_start:
            befunde.append(f"{kennung}: t_measure_start="
                           f"{r.get('t_measure_start')!r}, erwartet "
                           f"{soll_start}")
        if r.get("t_final") != soll_ende:
            befunde.append(f"{kennung}: t_final={r.get('t_final')!r}, "
                           f"erwartet {soll_ende}")
        if not r.get("rq4_status"):
            befunde.append(f"{kennung}: rq4_status leer")
        if r.get("error"):
            befunde.append(f"{kennung}: error={r['error']!r}")

    # --- Fensterkonsistenz je Lauf ------------------------------------- #
    markiert = {}
    retr_datei = ordner / "retrievals.csv"
    if retr_datei.exists():
        with open(retr_datei, newline="", encoding="utf-8") as fh:
            for zeile in csv.DictReader(fh):
                if zeile.get("in_measurement_window") == "True":
                    markiert[zeile["run_id"]] = markiert.get(
                        zeile["run_id"], 0) + 1
    for r in runs:
        erwartete_zahl = int(r.get("measurement_retrievals") or 0)
        ist = markiert.get(r["run_id"], 0)
        if ist != erwartete_zahl:
            befunde.append(
                f"{r['run_id']}: runs.csv nennt {erwartete_zahl} Retrievals "
                f"im Fenster, retrievals.csv markiert {ist}")

    # --- Fremde run_ids in den uebrigen Dateien ------------------------ #
    for name in ("retrievals.csv", "requests.csv", "distribution.csv"):
        pfad = ordner / name
        if not pfad.exists():
            befunde.append(f"{name} fehlt")
            continue
        with open(pfad, newline="", encoding="utf-8") as fh:
            leser = csv.DictReader(fh)
            if not leser.fieldnames or "run_id" not in leser.fieldnames:
                befunde.append(f"{name} hat keine Spalte run_id")
                continue
            gesehen = {z["run_id"] for z in leser}
        unbekannt = sorted(gesehen - set(ids))
        ohne = sorted(set(ids) - gesehen)
        if unbekannt:
            befunde.append(f"{name} verweist auf unbekannte run_ids: "
                           f"{unbekannt}")
        if ohne:
            befunde.append(f"{name} enthaelt nichts fuer: {ohne}")

    # --- run_meta.json -------------------------------------------------- #
    meta_datei = ordner / "run_meta.json"
    if not meta_datei.exists():
        befunde.append("run_meta.json fehlt")
    else:
        try:
            meta = json.loads(meta_datei.read_text())
        except json.JSONDecodeError as exc:
            befunde.append(f"run_meta.json unlesbar: {exc}")
            meta = []
        meta_ids = [m.get("run_id") for m in meta]
        if sorted(set(meta_ids)) != sorted(set(ids)):
            befunde.append("run_meta.json deckt sich nicht mit runs.csv")
        if len(meta_ids) != len(set(meta_ids)):
            befunde.append("doppelte run_id in run_meta.json")

    return befunde


def abschlusspruefung(ordner: Path, eintraege, status, smoke=False) -> int:
    """Fuehrt den Integritaetscheck aus und bestimmt den Exitcode."""
    print("\n" + "=" * 68)
    print("FINAL CAMPAIGN INTEGRITY CHECK"
          + ("  (SMOKE)" if smoke else ""))
    print("=" * 68)

    befunde = pruefe_integritaet(ordner, eintraege, status, smoke)
    if befunde:
        for b in befunde:
            print(f"  BEFUND: {b}")
        print("\nFINAL CAMPAIGN INTEGRITY CHECK: FAIL")
        print("Die Kampagne wird NICHT als erfolgreich gemeldet.")
        return 1

    print(f"  {len(eintraege)} Laeufe, je genau ein Datensatz")
    print("  Fenster, RQ4-Status und Querverweise konsistent")
    print("\nFINAL CAMPAIGN INTEGRITY CHECK: PASS")
    return 0


# ====================================================================== #
# Dry Run
# ====================================================================== #

def dry_run(eintraege, ordner: Path, smoke: bool) -> int:
    """
    Prueft den Plan, ohne zu rechnen.

    Geprueft wird genau das, woran die Kampagne sonst erst nach Stunden
    scheitern wuerde: Vollstaendigkeit und Eindeutigkeit der Matrix, die
    Policy-Konfiguration jeder einzelnen Kombination, die Horizonte, der
    Exporter und das Ausgabeziel.
    """
    print("=" * 68)
    print("CAMPAIGN DRY RUN" + ("  (SMOKE-Parameter)" if smoke else ""))
    print("=" * 68)

    kombinationen = [(e["run_id"], e["policy"], e["seed"]) for e in eintraege]
    fehler = []

    voll = (not smoke
            and len(eintraege) == len(FINAL_POLICIES) * len(FINAL_SEEDS))
    if voll:
        fehler += check_matrix(kombinationen)
    else:
        ids = [k[0] for k in kombinationen]
        if len(set(ids)) != len(ids):
            fehler.append("doppelte run_id in der Teilmenge")

    print(f"\nKombinationen : {len(eintraege)}")
    print(f"Policies      : {sorted({e['policy'] for e in eintraege})}")
    print(f"Seeds         : {sorted({e['seed'] for e in eintraege})}")
    print(f"eindeutige IDs: {len({e['run_id'] for e in eintraege})}")

    print("\nKonfigurationspruefung je Kombination:")
    abweichende = 0
    for eintrag in eintraege:
        config = eintrag["config"]
        if smoke:
            probleme = [
                f"simulation_time={config.simulation_time}"
                for _ in [1] if config.simulation_time != SMOKE_SIM_TIME
            ]
        else:
            probleme = check_final_config(config)
        # Policy-Zuordnung unabhaengig nachrechnen.
        soll = FINAL_POLICIES[eintrag["policy"]]
        ist = (config.reordering_strategy, config.placement_strategy,
               config.return_blocking_bins)
        if ist != soll:
            probleme.append(f"Policy-Konfiguration ist={ist} soll={soll}")
        if config.random_seed != eintrag["seed"]:
            probleme.append(f"random_seed={config.random_seed}")
        if probleme:
            abweichende += 1
            print(f"  ABWEICHUNG {eintrag['run_id']}: {probleme}")
    if not abweichende:
        muster = eintraege[0]["config"]
        print(f"  alle {len(eintraege)} Konfigurationen entsprechen dem "
              f"eingefrorenen Szenario")
        print(f"  Grid {muster.grid_width}x{muster.grid_depth} "
              f"H={muster.max_stack_height} bins={muster.bin_num} "
              f"robots={muster.num_robots} ps={muster.num_pickstations} "
              f"cap={muster.pickstation_capacity}")
        print(f"  Zipf={muster.zipf_parameter} util={muster.request_utilization} "
              f"scheduler={muster.scheduler_strategy} "
              f"deadline_slack={muster.deadline_slack} "
              f"pop_warmup={muster.popularity_warmup_retrievals}")
        print(f"  Horizont 0 ... {muster.simulation_time}, Fenster "
              f"[{muster.t_measure_start}, {muster.t_final}]")
        print(f"  stop_on_convergence={muster.stop_on_convergence}")
    else:
        fehler.append(f"{abweichende} Konfiguration(en) weichen ab")

    print(f"\nExporter      : experiments.run_export.ExperimentWriter")
    print(f"Ausgabeziel   : {ordner}")
    verbotene = ("closeout", "pilot", "calib", "debug")
    if any(teil in ordner.as_posix().lower() for teil in verbotene):
        fehler.append(f"Ausgabeziel {ordner} liegt in einem Diagnosepfad "
                      f"({verbotene})")
    belegt = ordner.exists() and any(ordner.iterdir())
    print(f"Ziel belegt   : {belegt}")

    print("\n" + "-" * 68)
    if fehler:
        for f in fehler:
            print(f"FEHLER: {f}")
        print("\nVERDICT: CAMPAIGN DRY RUN FAIL")
        return 1
    print("VERDICT: CAMPAIGN DRY RUN PASS")
    print("Es wurde nichts gerechnet und nichts geschrieben.")
    return 0


# ====================================================================== #
# CLI
# ====================================================================== #

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Finale 50-Run-Kampagne (5 Policies x 10 Seeds).")
    p.add_argument("--output-dir", required=True,
                   help="Zielordner der Kampagnendaten.")
    p.add_argument("--dry-run", action="store_true",
                   help="Nur den Plan pruefen, nichts rechnen.")
    p.add_argument("--smoke", action="store_true",
                   help="Kurzer End-to-End-Test ueber denselben Pfad. "
                        "Eigener Horizont, NIE die finalen Parameter.")
    p.add_argument("--policy", action="append", default=None,
                   choices=list(FINAL_POLICIES),
                   help="Teilmenge; mehrfach angebbar.")
    p.add_argument("--seed", action="append", type=int, default=None,
                   help="Teilmenge; mehrfach angebbar.")
    p.add_argument("--resume", action="store_true",
                   help="Bereits abgeschlossene Runs ueberspringen.")
    args = p.parse_args(argv)

    ordner = Path(args.output_dir).resolve()
    eintraege = plan(args.policy, args.seed, smoke=args.smoke)

    if args.dry_run:
        return dry_run(eintraege, ordner, args.smoke)

    # Kein stilles Ueberschreiben eines belegten finalen Ausgabeordners.
    if ordner.exists() and any(ordner.iterdir()) and not args.resume:
        print(f"FEHLER: {ordner} ist nicht leer.\n"
              f"Entweder einen anderen --output-dir waehlen oder --resume "
              f"benutzen. Ein stilles Ueberschreiben findet nicht statt.")
        return 2

    if args.smoke:
        status = lade_status(ordner)
        if any(not v.get("smoke") for v in status.values()):
            print(f"FEHLER: {ordner} enthaelt finale Laeufe. Der Rauchtest "
                  f"schreibt nicht in ein finales Ergebnisverzeichnis.")
            return 2
        print(f"[SMOKE] Horizont {SMOKE_SIM_TIME} ZE, Fenster "
              f"[{SMOKE_T_MEASURE_START}, {SMOKE_SIM_TIME}] — "
              f"NICHT die finalen Parameter")

    return fahre_kampagne(eintraege, ordner, args.resume, args.smoke)


if __name__ == "__main__":
    sys.exit(main())
