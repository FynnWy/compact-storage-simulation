# experiments/run_export.py
"""
Datenexport der finalen Experimentkampagne.

Entwurfsentscheidung: kompakte semantische Daten statt Eventlog
---------------------------------------------------------------
Ein vollständiger Log jedes ROBOT_MOVE-Events wäre um Größenordnungen größer
und beantwortet keine der vier Forschungsfragen zusätzlich. Gemessen wurden im
finalnahen Setup rund 40.000 Bewegungsereignisse je 1.000 ZE gegenüber rund
60 physischen Retrievals – ein Verhältnis von etwa 700 : 1.

Exportiert werden deshalb vier Ebenen:

    requests.csv      eine Zeile je bedientem Request: Ankunft, Deadline,
                      Fertigstellung, Verspätung – Rohdaten der sekundären
                      Service-KPIs
    runs.csv          eine Zeile je Lauf (Policy x Seed): Setup, primäre KPI,
                      erklärende KPIs, Steady-State-Ergebnis, Diagnose
    retrievals.csv    eine Zeile je physischem Retrieval (Command Cycle):
                      Level, Stackhöhe, Blocking Bins, ABC-Klasse, Batchgröße
    distribution.csv  eine Zeile je Verteilungs-Snapshot: räumliche Lage der
                      Bins über die Zeit (RQ3/RQ4)
    run_meta.json     vollständige Konfiguration je Lauf, für Reproduzierbarkeit

Alle drei CSV-Dateien sind lange Tabellen mit `run_id` als Schlüssel und
lassen sich direkt mit `pandas.read_csv` auswerten. Kein Datenbanksystem,
keine Excel-Abhängigkeit.
"""

import csv
import json
from pathlib import Path


RUN_FIELDS = [
    # Identität
    "run_id", "policy", "seed",
    "reordering_strategy", "placement_strategy", "return_blocking_bins",
    # Setup
    "grid_width", "grid_depth", "max_stack_height", "bin_num",
    "num_robots", "num_pickstations", "request_utilization",
    "zipf_parameter", "simulation_time",
    # Primäre KPI
    "t_end", "physical_retrievals", "bin_throughput",
    # Sekundäre KPIs
    "requests_completed", "request_throughput",
    "mean_blocking_bins", "p_beta_zero",
    "mean_levels_from_top", "share_retrievals_top20pct",
    "mean_dig_duration", "mean_batch_size",
    "deadline_slack", "requests_evaluated", "deadline_miss_rate",
    "mean_tardiness", "median_tardiness", "p95_tardiness", "mean_flow_time",
    "pickstation_utilisation_mean",
    # Steady State (RQ4)
    "steady_state_status", "convergence_time", "convergence_retrievals",
    "measurement_retrievals", "measurement_complete",
    # Diagnose / Laufgesundheit
    "move_stall_recoveries", "move_recovery_unresolved", "error",
]

REQUEST_FIELDS = [
    "run_id", "policy", "seed",
    "request_id", "bin_id", "arrival_time", "deadline",
    "completion_time", "flow_time", "lateness", "tardiness", "on_time",
]

RETRIEVAL_FIELDS = [
    "run_id", "policy", "seed",
    "t_pickstation", "request_id", "bin_id", "abc_class",
    "access_count_before", "level", "stack_height", "levels_from_top",
    "blocking_bins", "blockers_returned", "batch_size",
    "t_retrieval_start", "dig_duration", "pickstation", "robot_id",
    "in_measurement_window",
]


def _quantil(werte, q):
    """Einfaches Quantil auf einer bereits sortierten Liste."""
    if not werte:
        return None
    return werte[min(len(werte) - 1, int(len(werte) * q))]


def _mittel(werte):
    werte = [w for w in werte if w is not None]
    return sum(werte) / len(werte) if werte else None


def summarise_run(run_id, policy, seed, engine, steady, error=None,
                  recoveries=0, unresolved=0):
    """
    Baut die Zeile für `runs.csv`.

    Die primäre KPI `bin_throughput` wird über das Measurement Window
    berechnet, sofern der Lauf konvergiert ist – sonst über den gesamten Lauf,
    dann aber mit `steady_state_status = not_converged` gekennzeichnet.
    """
    config = engine.config
    zusammenfassung = engine.metrics.summary()
    alle = engine.metrics.retrievals
    fenster = steady.get("measurement_window") or []
    basis = fenster if fenster else alle

    if fenster and len(fenster) > 1:
        dauer = fenster[-1]["t_pickstation"] - fenster[0]["t_pickstation"]
    else:
        dauer = engine.state.t
    dauer = max(dauer, 1)

    def anteil_oben(zeilen):
        if not zeilen:
            return None
        treffer = sum(
            1 for r in zeilen
            if r["levels_from_top"] is not None
            and r["levels_from_top"] < max(1, round(0.2 * r["stack_height"]))
        )
        return treffer / len(zeilen)

    # Sekundäre Service-KPIs über alle bedienten Requests des Laufs.
    _tard = sorted(max(0, r["time"] - r["latest_time"])
                   for r in engine.metrics.completed_requests
                   if "latest_time" in r)
    _flow = [r["time"] - r["arrival_time"]
             for r in engine.metrics.completed_requests
             if "arrival_time" in r]

    auslastungen = []
    for station in engine.state.pickstations:
        if hasattr(station, "utilization"):
            try:
                auslastungen.append(station.utilization(engine.state.t))
            except TypeError:
                pass

    return {
        "run_id": run_id,
        "policy": policy,
        "seed": seed,
        "reordering_strategy": config.reordering_strategy,
        "placement_strategy": config.placement_strategy,
        "return_blocking_bins": config.return_blocking_bins,
        "grid_width": config.grid_width,
        "grid_depth": config.grid_depth,
        "max_stack_height": config.max_stack_height,
        "bin_num": config.bin_num,
        "num_robots": config.num_robots,
        "num_pickstations": config.num_pickstations,
        "request_utilization": config.request_utilization,
        "zipf_parameter": config.zipf_parameter,
        "simulation_time": config.simulation_time,
        "t_end": engine.state.t,
        "physical_retrievals": len(alle),
        # PRIMÄRE KPI: physische Bin-Retrievals je Zeiteinheit.
        "bin_throughput": (len(basis) / dauer) if basis else 0.0,
        "requests_completed": zusammenfassung.get("requests_completed"),
        "request_throughput": (
            (zusammenfassung.get("requests_completed") or 0) / max(engine.state.t, 1)
        ),
        "mean_blocking_bins": _mittel([r["blocking_bins"] for r in basis]),
        "p_beta_zero": (
            sum(1 for r in basis if r["blocking_bins"] == 0) / len(basis)
            if basis else None
        ),
        "mean_levels_from_top": _mittel([r["levels_from_top"] for r in basis]),
        "share_retrievals_top20pct": anteil_oben(basis),
        "mean_dig_duration": _mittel([r["dig_duration"] for r in basis]),
        "mean_batch_size": _mittel([r["batch_size"] for r in basis]),
        "deadline_slack": getattr(config, "deadline_slack", None),
        "requests_evaluated": len(_tard),
        "deadline_miss_rate": (
            sum(1 for t in _tard if t > 0) / len(_tard) if _tard else None
        ),
        "mean_tardiness": _mittel(_tard),
        "median_tardiness": _quantil(_tard, 0.5),
        "p95_tardiness": _quantil(_tard, 0.95),
        "mean_flow_time": _mittel(_flow),
        "pickstation_utilisation_mean": _mittel(auslastungen),
        "steady_state_status": steady.get("status"),
        "convergence_time": steady.get("convergence_time"),
        "convergence_retrievals": steady.get("convergence_retrievals"),
        "measurement_retrievals": len(fenster),
        "measurement_complete": steady.get("measurement_complete"),
        "move_stall_recoveries": recoveries,
        "move_recovery_unresolved": unresolved,
        "error": error,
    }


def request_rows(run_id, policy, seed, engine):
    """
    Zeilen für `requests.csv`.

    Fertigstellung ist die ANKUNFT DER TARGET-BIN AN DER PICKSTATION – der
    Zeitpunkt, an dem der Request fachlich bedient ist. Die anschließende
    Rücklagerung gehört zum Systemaufwand, nicht zur Servicezeit des Kunden.

    Batching: `Metrics.record_target_bin_at_pickstation` wird für den primären
    UND für jeden gebatchten Request einzeln aufgerufen. Jeder Request wird
    also gegen seine EIGENE Deadline bewertet, obwohl mehrere durch dasselbe
    physische Retrieval bedient werden. Ein Batch zählt hier als N Zeilen,
    in `retrievals.csv` als eine.
    """
    for eintrag in engine.metrics.completed_requests:
        if "request_id" not in eintrag:
            continue
        ankunft = eintrag["arrival_time"]
        deadline = eintrag["latest_time"]
        fertig = eintrag["time"]
        yield {
            "run_id": run_id,
            "policy": policy,
            "seed": seed,
            "request_id": eintrag["request_id"],
            "bin_id": eintrag.get("bin_id"),
            "arrival_time": ankunft,
            "deadline": deadline,
            "completion_time": fertig,
            "flow_time": fertig - ankunft,
            "lateness": fertig - deadline,
            "tardiness": max(0, fertig - deadline),
            "on_time": fertig <= deadline,
        }


def retrieval_rows(run_id, policy, seed, engine, steady):
    """Zeilen für `retrievals.csv`, inkl. Markierung des Measurement Windows."""
    fenster = steady.get("measurement_window") or []
    im_fenster = {id(r) for r in fenster}

    for row in engine.metrics.retrievals:
        eintrag = {"run_id": run_id, "policy": policy, "seed": seed}
        eintrag.update({k: row.get(k) for k in RETRIEVAL_FIELDS
                        if k not in ("run_id", "policy", "seed",
                                     "in_measurement_window")})
        eintrag["in_measurement_window"] = id(row) in im_fenster
        yield eintrag


class ExperimentWriter:
    """
    Schreibt die vier Dateien inkrementell – ein Lauf nach dem anderen.

    Inkrementell, damit eine lange Kampagne bei einem Abbruch nicht die
    bereits gerechneten Läufe verliert.
    """

    def __init__(self, output_dir):
        self.dir = Path(output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._runs = open(self.dir / "runs.csv", "w", newline="", encoding="utf-8")
        self._retr = open(self.dir / "retrievals.csv", "w", newline="", encoding="utf-8")
        self._req = open(self.dir / "requests.csv", "w", newline="", encoding="utf-8")
        self._dist = open(self.dir / "distribution.csv", "w", newline="", encoding="utf-8")
        self._run_writer = csv.DictWriter(self._runs, fieldnames=RUN_FIELDS)
        self._retr_writer = csv.DictWriter(self._retr, fieldnames=RETRIEVAL_FIELDS)
        self._req_writer = csv.DictWriter(self._req, fieldnames=REQUEST_FIELDS)
        self._run_writer.writeheader()
        self._retr_writer.writeheader()
        self._req_writer.writeheader()
        self._dist_writer = None
        self._meta = []

    def add_run(self, run_id, policy, seed, engine, steady, error=None,
                recoveries=0, unresolved=0):
        self._run_writer.writerow(
            summarise_run(run_id, policy, seed, engine, steady, error,
                          recoveries, unresolved))
        self._runs.flush()

        for zeile in retrieval_rows(run_id, policy, seed, engine, steady):
            self._retr_writer.writerow(zeile)
        self._retr.flush()

        for zeile in request_rows(run_id, policy, seed, engine):
            self._req_writer.writerow(zeile)
        self._req.flush()

        snapshots = engine.metrics.get_distribution_timeseries() or []
        for snapshot in snapshots:
            flach = {"run_id": run_id, "policy": policy, "seed": seed}
            for key, value in snapshot.items():
                if isinstance(value, (int, float, str, bool)) or value is None:
                    flach[key] = value
            if self._dist_writer is None:
                self._dist_writer = csv.DictWriter(
                    self._dist, fieldnames=list(flach.keys()))
                self._dist_writer.writeheader()
            self._dist_writer.writerow(
                {k: flach.get(k) for k in self._dist_writer.fieldnames})
        self._dist.flush()

        self._meta.append({
            "run_id": run_id,
            "policy": policy,
            "seed": seed,
            "config": {
                k: v for k, v in vars(engine.config).items()
                if isinstance(v, (int, float, str, bool)) or v is None
            },
            "rng_streams": list(engine.rng_streams._streams.keys()),
            "steady_state": {
                k: v for k, v in steady.items() if k != "measurement_window"
            },
        })

    def close(self):
        self._runs.close()
        self._retr.close()
        self._req.close()
        self._dist.close()
        with open(self.dir / "run_meta.json", "w", encoding="utf-8") as fh:
            json.dump(self._meta, fh, indent=2, ensure_ascii=False)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
