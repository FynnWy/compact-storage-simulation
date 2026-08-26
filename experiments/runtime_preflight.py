# experiments/runtime_preflight.py
"""
Betriebsprognose vor der finalen Kampagne: Hardware, Platz, Laufzeit.

Zweck ist ausschliesslich operativ. Nichts hier veraendert `T_measure_start`,
`T_final`, Seeds, Policies, das Measurement Window, die RQ4-Regel oder eine
KPI. Sagt die Schaetzung 35 Stunden, wird deshalb **nicht** der Horizont
gekuerzt.

Warum Hardware allein nicht reicht
----------------------------------
Die Simulation ist ereignisdiskret, in Python geschrieben und laeuft bewusst
sequentiell. Kernzahl und Taktfrequenz sagen darueber wenig; die tatsaechliche
Rechenzeit haengt an der Ereignisdichte je Policy. `RR+RR` brauchte in der
Kalibration rund 10.993 Simulationsschritte je 1.000 ZE, `ABC+ABC` nur 6.891 —
bei gleichem Horizont ein Unterschied von rund 60 %.

Deshalb zwei Ebenen:

    A  Hardware-Inventar          was steht zur Verfuegung
    B  Mini-Benchmark je Policy   was diese Maschine wirklich schafft

Die Schaetzung extrapoliert je Policy getrennt und summiert, statt einen
einzelnen Messwert mit 50 zu multiplizieren.

Keine neuen Abhaengigkeiten: alles ueber `platform`, `os` und `shutil`.
`psutil` wird benutzt, falls vorhanden, ist aber nicht erforderlich.
"""

import contextlib
import io
import json
import os
import platform
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

#: Horizont des Mini-Benchmarks. Lang genug, dass nicht nur die
#: Initialisierung gemessen wird (die kostet auf der finalen Geometrie
#: mehrere Sekunden), kurz genug, dass die Schaetzung selbst Minuten und
#: nicht Stunden dauert.
BENCHMARK_ZE = 600

#: Seed des Benchmarks. Bewusst KEIN Seed aus `FINAL_SEEDS`, damit eine
#: Benchmark-Kennung niemals mit einer finalen `run_id` kollidieren kann.
BENCHMARK_SEED = 999_001

#: Aus den Kalibrationslaeufen: gemessene Wanduhrzeit je 30.000-ZE-Lauf lag
#: zwischen dem 0,8- und dem 1,35-fachen des Policy-Mittels. Daraus wird die
#: Bandbreite der Prognose gebildet — eine Betriebsspanne, keine Statistik.
SPANNE_UNTEN = 0.8
SPANNE_OBEN = 1.35

#: Grob gemessen an den Kalibrations- und Smokedaten (siehe `schaetze_platz`).
MB = 1024 * 1024


# ====================================================================== #
# A. Hardware
# ====================================================================== #

def hardware_inventar(output_dir=None) -> Dict[str, object]:
    """
    Was diese Maschine bietet. Reine Information, keine Konsequenz.

    Der Runner parallelisiert NICHT automatisch, auch wenn viele Kerne
    gemeldet werden: `ExperimentWriter` schreibt gemeinsame CSV-Dateien.
    """
    info: Dict[str, object] = {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "python": platform.python_version(),
        "logical_cores": os.cpu_count(),
        "physical_cores": None,
        "usable_cores": None,
        "ram_total_bytes": None,
        "ram_available_bytes": None,
        "disk_free_bytes": None,
        "disk_path": None,
    }

    # CPU-Modell, wo die Plattform es hergibt.
    try:
        if platform.system() == "Linux" and Path("/proc/cpuinfo").exists():
            for zeile in Path("/proc/cpuinfo").read_text().splitlines():
                if zeile.lower().startswith("model name"):
                    info["processor"] = zeile.split(":", 1)[1].strip()
                    break
    except OSError:
        pass

    # Tatsaechlich nutzbare Kerne (Affinitaet, cgroup-Limits).
    try:
        info["usable_cores"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        info["usable_cores"] = info["logical_cores"]

    try:
        import psutil  # type: ignore
        info["physical_cores"] = psutil.cpu_count(logical=False)
        speicher = psutil.virtual_memory()
        info["ram_total_bytes"] = speicher.total
        info["ram_available_bytes"] = speicher.available
    except Exception:
        # Ohne psutil: unter Linux ueber sysconf bzw. /proc/meminfo.
        try:
            info["ram_total_bytes"] = (os.sysconf("SC_PAGE_SIZE")
                                       * os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError, AttributeError):
            pass
        try:
            felder = {}
            for zeile in Path("/proc/meminfo").read_text().splitlines():
                schluessel, _, rest = zeile.partition(":")
                felder[schluessel] = rest.strip()
            if "MemAvailable" in felder:
                info["ram_available_bytes"] = (
                    int(felder["MemAvailable"].split()[0]) * 1024)
        except (OSError, ValueError, IndexError):
            pass

    if output_dir is not None:
        pfad = Path(output_dir)
        while not pfad.exists() and pfad != pfad.parent:
            pfad = pfad.parent
        try:
            info["disk_free_bytes"] = shutil.disk_usage(pfad).free
            info["disk_path"] = str(pfad)
        except OSError:
            pass

    return info


def _lesbar(bytes_: Optional[int]) -> str:
    if not bytes_:
        return "unbekannt"
    for einheit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_ < 1024 or einheit == "TB":
            return f"{bytes_:.1f} {einheit}"
        bytes_ /= 1024.0
    return "unbekannt"


# ====================================================================== #
# B. Platzbedarf
# ====================================================================== #

def schaetze_platz(anzahl_runs: int) -> Dict[str, int]:
    """
    Konservative Schaetzung des Platzbedarfs.

    Grundlage sind die gemessenen Groessenordnungen der Kalibration:

        Retrievals je Lauf        rund 950 - 1.800
        Requests je Lauf          rund 3.000 - 6.000
        Distribution-Snapshots    300 je 30.000 ZE, ~30 Spalten
        Logzeilen je Lauf         150.000 - 200.000, im Mittel ~90 B/Zeile
        run_meta je Lauf          RQ4-Folge + Config, wenige KB

    Der Logbedarf dominiert deutlich; alles andere ist Rauschen daneben.
    Aufgeschlagen werden 50 % Sicherheitsreserve.
    """
    log_je_run = 200_000 * 90            # ~18 MB
    csv_je_run = 6_000 * 200 + 1_800 * 220 + 300 * 400   # ~1,7 MB
    meta_je_run = 40 * 1024

    roh = anzahl_runs * (log_je_run + csv_je_run + meta_je_run)
    return {
        "je_run_bytes": log_je_run + csv_je_run + meta_je_run,
        "roh_bytes": roh,
        "empfohlen_bytes": int(roh * 1.5),
    }


def pruefe_platz(output_dir, anzahl_runs: int) -> Dict[str, object]:
    """
    Fail-Fast, wenn der Platz offensichtlich nicht reicht.

    Returns:
        dict mit `ok`, `warnung`, `frei_bytes`, `bedarf_bytes`.
    """
    bedarf = schaetze_platz(anzahl_runs)
    pfad = Path(output_dir)
    while not pfad.exists() and pfad != pfad.parent:
        pfad = pfad.parent
    try:
        frei = shutil.disk_usage(pfad).free
    except OSError:
        return {"ok": True, "warnung": "Freier Speicher nicht ermittelbar.",
                "frei_bytes": None,
                "bedarf_bytes": bedarf["empfohlen_bytes"]}

    ergebnis = {"ok": True, "warnung": None, "frei_bytes": frei,
                "bedarf_bytes": bedarf["empfohlen_bytes"],
                "roh_bytes": bedarf["roh_bytes"]}
    if frei < bedarf["roh_bytes"]:
        ergebnis["ok"] = False
        ergebnis["warnung"] = (
            f"Nur {_lesbar(frei)} frei, konservativ erwartet werden "
            f"{_lesbar(bedarf['roh_bytes'])}.")
    elif frei < bedarf["empfohlen_bytes"]:
        ergebnis["warnung"] = (
            f"{_lesbar(frei)} frei — knapp. Mit Reserve empfohlen: "
            f"{_lesbar(bedarf['empfohlen_bytes'])}.")
    return ergebnis


# ====================================================================== #
# C. Benchmark
# ====================================================================== #

def benchmarke_policy(policy: str, ze: int = BENCHMARK_ZE,
                      seed: int = BENCHMARK_SEED) -> Dict[str, object]:
    """
    Misst die Rechenzeit dieser Policy auf DIESER Maschine.

    Benutzt denselben Config- und Engine-Pfad wie die Kampagne, aber eine
    eigene, kurze Konfiguration mit einem Seed ausserhalb der finalen Menge.
    Der erzeugte Engine wird verworfen; er beruehrt weder die finalen
    Konfigurationen noch deren Zufallsstroeme.
    """
    from experiments.campaign_matrix import build_run_config
    from simulation.simulation_engine import SimulationEngine

    config = build_run_config(policy, seed, sim_time=ze,
                              t_measure_start=None, t_final=None)

    # Aufbau und Rechnen getrennt messen.
    #
    # Der Aufbau der finalen Geometrie (4320 Bins auf 592 zulaessigen
    # Stapeln) kostet mehrere Sekunden und faellt je Lauf genau EINMAL an —
    # egal ob der Lauf 600 oder 30.000 ZE lang ist. Wuerde man ihn in die
    # Rate je 1.000 ZE einrechnen, waere die Hochrechnung auf 30.000 ZE
    # systematisch zu hoch.
    begonnen = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        engine = SimulationEngine(config)
    aufbau = time.time() - begonnen

    begonnen = time.time()
    schritte = 0
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            schritte += 1
    rechnen = time.time() - begonnen

    erreicht = max(engine.state.t, 1)
    return {
        "policy": policy,
        "simulated_ZE": erreicht,
        "setup_seconds": round(aufbau, 2),
        "wall_seconds": round(aufbau + rechnen, 2),
        "steps": schritte,
        # Grenzrate: nur die Rechenzeit, ohne den einmaligen Aufbau.
        "seconds_per_1000_ZE": round(rechnen / erreicht * 1000, 3),
        # Bruttorate zum Vergleich, damit die Trennung nachvollziehbar ist.
        "gross_seconds_per_1000_ZE": round(
            (aufbau + rechnen) / erreicht * 1000, 3),
    }


def benchmarke_alle(policies=None, ze: int = BENCHMARK_ZE) -> List[dict]:
    from experiments.campaign_matrix import FINAL_POLICIES
    return [benchmarke_policy(p, ze=ze)
            for p in (policies or list(FINAL_POLICIES))]


# ====================================================================== #
# D. Schaetzung
# ====================================================================== #

def historische_walltimes(pfad=None) -> Dict[str, float]:
    """
    Wanduhrzeiten der 15 Kalibrationslaeufe, falls maschinenlesbar.

    Sie stammen aus echten 30.000-ZE-Laeufen und sind damit eine bessere
    Grundlage als jede Extrapolation — ABER nur, wenn sie auf derselben
    Maschine entstanden sind. Das laesst sich nicht sicher feststellen,
    weshalb der aktuelle Benchmark im kombinierten Wert hoeher gewichtet
    wird.

    Returns:
        `{policy: mittlere Sekunden je 30.000 ZE}`
    """
    if pfad is None:
        pfad = (Path(__file__).resolve().parent / "closeout" / "results"
                / "rq4_calibration_final.json")
    pfad = Path(pfad)
    if not pfad.exists():
        return {}
    try:
        daten = json.loads(pfad.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    je_policy: Dict[str, List[float]] = {}
    for lauf in daten.get("runs", []):
        zaehler = lauf.get("counters") or {}
        sekunden = zaehler.get("wall_seconds")
        t_end = lauf.get("t_end")
        if not sekunden or not t_end:
            continue
        # Auf 30.000 ZE normieren: ABC+ABC/7 lief bis 42.000.
        je_policy.setdefault(lauf["policy"], []).append(
            sekunden / t_end * 30_000)
    return {p: sum(w) / len(w) for p, w in je_policy.items() if w}


def schaetze_kampagne(benchmarks: List[dict], seeds_je_policy: int,
                      ze_je_run: int, historisch=None) -> Dict[str, object]:
    """
    Rechnet die Benchmarkwerte auf die volle Kampagne hoch.

    Je Policy getrennt, weil die Policies unterschiedlich teuer sind. Ein
    einzelner Messwert mal 50 wuerde die teuerste Policy unterschaetzen.
    """
    historisch = historisch or {}
    je_policy = []
    for b in benchmarks:
        # Je Lauf: einmal Aufbau plus die Grenzrate ueber den vollen Horizont.
        je_lauf = (b.get("setup_seconds", 0.0)
                   + b["seconds_per_1000_ZE"] * ze_je_run / 1000)
        bench = je_lauf * seeds_je_policy
        hist = historisch.get(b["policy"])
        hist_gesamt = hist * seeds_je_policy if hist else None
        if hist_gesamt:
            # Aktuelle Maschine hoeher gewichten: 2 zu 1.
            kombiniert = (2 * bench + hist_gesamt) / 3
        else:
            kombiniert = bench
        je_policy.append({
            "policy": b["policy"],
            "seconds_per_1000_ZE": b["seconds_per_1000_ZE"],
            "benchmark_estimate_s": round(bench),
            "historical_estimate_s": round(hist_gesamt) if hist_gesamt else None,
            "combined_estimate_s": round(kombiniert),
        })

    gesamt = sum(p["combined_estimate_s"] for p in je_policy)
    return {
        "per_policy": je_policy,
        "central_seconds": gesamt,
        "low_seconds": int(gesamt * SPANNE_UNTEN),
        "high_seconds": int(gesamt * SPANNE_OBEN),
        "runs": len(benchmarks) * seeds_je_policy,
    }


def dauer_lesbar(sekunden: Optional[float]) -> str:
    if sekunden is None:
        return "unbekannt"
    sekunden = int(sekunden)
    stunden, rest = divmod(sekunden, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}h {minuten:02d}m"
    if minuten:
        return f"{minuten}m {sek:02d}s"
    return f"{sek}s"


# ====================================================================== #
# E. Laufende Schaetzung waehrend der Kampagne
# ====================================================================== #

def laufende_schaetzung(fertig: List[tuple], offen: List[str],
                        vorab: Optional[dict] = None) -> Dict[str, object]:
    """
    Schaetzt die Restzeit aus den REALEN bisherigen Wanduhrzeiten.

    Args:
        fertig: `[(policy, wall_seconds), ...]` der abgeschlossenen Laeufe.
        offen: Policies der noch ausstehenden Laeufe, je Lauf ein Eintrag.
        vorab: Ergebnis von `schaetze_kampagne` — Rueckfallwert fuer
            Policies, die noch gar nicht beobachtet wurden.

    Policygewichtet, sobald genug Daten da sind: eine Kampagne, die mit der
    guenstigsten Policy beginnt, wuerde sonst systematisch zu optimistisch
    schaetzen.
    """
    if not fertig:
        return {"elapsed_seconds": 0.0, "mean_seconds": None,
                "remaining_seconds": None}

    je_policy: Dict[str, List[float]] = {}
    for policy, sekunden in fertig:
        je_policy.setdefault(policy, []).append(sekunden)
    mittel = {p: sum(w) / len(w) for p, w in je_policy.items()}
    gesamtmittel = sum(s for _, s in fertig) / len(fertig)

    rueckfall = {}
    if vorab:
        anzahl = max(1, vorab.get("runs", 1) // max(1, len(vorab["per_policy"])))
        rueckfall = {p["policy"]: p["combined_estimate_s"] / anzahl
                     for p in vorab["per_policy"]}

    rest = 0.0
    for policy in offen:
        rest += mittel.get(policy, rueckfall.get(policy, gesamtmittel))

    return {
        "elapsed_seconds": sum(s for _, s in fertig),
        "mean_seconds": gesamtmittel,
        "per_policy_mean": mittel,
        "remaining_seconds": rest,
        "finish_estimate": (datetime.now()
                            + timedelta(seconds=rest)).strftime(
                                "%Y-%m-%d %H:%M"),
    }


# ====================================================================== #
# F. Bericht
# ====================================================================== #

def zeige_preflight(hardware: dict, platz: dict, schaetzung: Optional[dict],
                    benchmark_dauer: Optional[float] = None) -> None:
    print("=" * 68)
    print("RUNTIME PREFLIGHT")
    print("=" * 68)
    print("\nHardware:")
    print(f"  Platform  : {hardware['platform']}")
    print(f"  CPU       : {hardware.get('processor') or 'unbekannt'}")
    kerne = f"{hardware.get('logical_cores')} logisch"
    if hardware.get("physical_cores"):
        kerne += f", {hardware['physical_cores']} physisch"
    if hardware.get("usable_cores") != hardware.get("logical_cores"):
        kerne += f", {hardware.get('usable_cores')} nutzbar"
    print(f"  Cores     : {kerne}")
    print(f"  RAM       : {_lesbar(hardware.get('ram_total_bytes'))} gesamt, "
          f"{_lesbar(hardware.get('ram_available_bytes'))} frei")
    print(f"  Python    : {hardware['python']}")
    print(f"  Disk free : {_lesbar(platz.get('frei_bytes'))} "
          f"({hardware.get('disk_path') or '?'})")
    print(f"  Disk need : {_lesbar(platz.get('bedarf_bytes'))} "
          f"(mit 50 % Reserve)")
    if platz.get("warnung"):
        print(f"  WARNUNG   : {platz['warnung']}")

    if schaetzung is None:
        print("\nBenchmark : uebersprungen (--skip-runtime-estimate)")
        print("\nExecution : SEQUENTIAL")
        return

    print(f"\nBenchmark ({BENCHMARK_ZE} ZE je Policy, Seed "
          f"{BENCHMARK_SEED}, Dauer {dauer_lesbar(benchmark_dauer)}):")
    for p in schaetzung["per_policy"]:
        zeile = (f"  {p['policy']:24s} {p['seconds_per_1000_ZE']:8.2f} "
                 f"sec / 1000 ZE  ->  {dauer_lesbar(p['benchmark_estimate_s'])}")
        if p["historical_estimate_s"]:
            zeile += (f"   (historisch "
                      f"{dauer_lesbar(p['historical_estimate_s'])})")
        print(zeile)
    print("  Rate ohne den einmaligen Aufbau je Lauf; der Aufbau ist "
          "separat eingerechnet.")
    print("  Die historischen Werte stammen aus vier PARALLEL gerechneten "
          "Kalibrationslaeufen\n  und sind durch die Konkurrenz um die "
          "Kerne nach oben verzerrt.")

    print(f"\nEstimated {schaetzung['runs']}-run campaign:")
    print(f"  central estimate : {dauer_lesbar(schaetzung['central_seconds'])}")
    print(f"  plausible range  : {dauer_lesbar(schaetzung['low_seconds'])}"
          f" – {dauer_lesbar(schaetzung['high_seconds'])}")
    ziel = datetime.now() + timedelta(seconds=schaetzung["central_seconds"])
    print(f"  finish if started now: {ziel.strftime('%Y-%m-%d %H:%M')}")
    print("\nExecution : SEQUENTIAL")
    print("Die Schaetzung ist eine Betriebsprognose. Sie veraendert weder "
          "Horizonte\nnoch Seeds, Policies, Messfenster, RQ4-Regel oder KPIs.")
