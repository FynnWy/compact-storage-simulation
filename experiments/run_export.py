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

from metrics.rq4_plateau import analyse_engine


# ====================================================================== #
# Measurement Window — EINE Quelle
# ====================================================================== #

def measurement_window(engine):
    """
    Die eine Definition des Auswertungsfensters.

    Rueckgabe: `(modus, t_start, t_ende)`.

    Vorher gab es zwei voneinander unabhaengige Definitionen: `summarise_run`
    filterte auf `[t_measure_start, t_final]`, `retrieval_rows` markierte
    dagegen aus dem alten, retrievalgezaehlten Steady-State-Fenster. Beide
    Definitionen konnten verschiedene Mengen meinen — und taten es auch: im
    Trockenlauf der 50er-Matrix war `in_measurement_window` durchgehend
    `False`, waehrend `runs.csv` 3 bis 13 Retrievals im Fenster zaehlte
    (Befund J-1, 2026-08-24).

    Deshalb entscheidet ausschliesslich diese Funktion, und alle Exportteile
    fragen sie. Die Semantik ist die bereits getestete aus `summarise_run`:
    beidseitig INKLUSIVE Grenzen auf `t_pickstation`.

    Ohne konfiguriertes Fenster (Tests, Diagnoselaeufe) gilt der ganze Lauf.
    Der alte retrievalgezaehlte Steady-State-Modus existiert nicht mehr: er
    gehoert zur verworfenen beta-Stop-Regel und haette als zweite
    Fensterdefinition genau das Problem reproduziert, das J-1 ausmacht.
    """
    config = engine.config
    t_start = getattr(config, "t_measure_start", None)
    t_ende = getattr(config, "t_final", None) or engine.state.t
    if t_start is None:
        return "full_run", None, engine.state.t
    return "time_window", t_start, t_ende


def is_in_measurement_window(zeitpunkt, modus, t_start, t_ende):
    """Gehoert ein Zeitpunkt zum Auswertungsfenster?"""
    if zeitpunkt is None:
        return False
    if modus != "time_window":
        return True
    return t_start <= zeitpunkt <= t_ende


def retrievals_in_window(retrievals, modus, t_start, t_ende):
    return [r for r in retrievals
            if is_in_measurement_window(r.get("t_pickstation"),
                                        modus, t_start, t_ende)]


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
    "pickstation_utilisation_ps0", "pickstation_utilisation_ps1",
    "retrievals_ps0", "retrievals_ps1",
    # Measurement Window (gemeinsames Zeitfenster aller Runs)
    "measurement_retrievals", "measurement_mode", "t_measure_start", "t_final",
    # RQ4 — offline aus der vollstaendigen Zeitreihe ab t=0.
    #
    # Die frueheren Spalten `steady_state_status`, `convergence_time`,
    # `convergence_retrievals` und `measurement_complete` stammten aus der
    # verworfenen beta-Stop-Regel (`metrics/steady_state.py`) und blieben im
    # Kampagnenpfad ausnahmslos leer, weil die gelesenen Schluessel dort gar
    # nicht existierten (Befund J-2, 2026-08-24). Eine Spalte, die etwas
    # verspricht und leer bleibt, ist schlechter als keine Spalte — sie sind
    # deshalb entfernt und durch die Felder der TATSAECHLICH eingefrorenen
    # Regel ersetzt (`metrics/rq4_plateau.py`).
    #
    # `rq4_status` ist immer gesetzt. Die uebrigen Felder sind bewusst
    # bedingt: `rq4_convergence_time_ZE` und `rq4_convergence_retrievals`
    # existieren nur bei `converged`, `rq4_plateau_level` nur, wenn ueberhaupt
    # ein Plateau gefunden wurde.
    "rq4_status", "rq4_convergence_time_ZE", "rq4_convergence_retrievals",
    "rq4_plateau_level", "rq4_redivergence", "rq4_blocks",
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


def summarise_run(run_id, policy, seed, engine, rq4=None, error=None,
                  recoveries=0, unresolved=0):
    """
    Baut die Zeile für `runs.csv`.

    Alle Performance-KPIs beziehen sich auf das Measurement Window, das
    `measurement_window()` liefert — dieselbe Quelle, die auch
    `retrieval_rows` benutzt.

    Args:
        rq4: Ergebnis der eingefrorenen Offline-RQ4-Regel. Wird `None`
            übergeben, rechnet der Export es selbst aus der vollständigen
            Zeitreihe des Laufs (`metrics.rq4_plateau.analyse_engine`). Es
            gibt genau eine Implementierung dieser Regel; das
            Kalibrationsskript benutzt dieselbe.

    Der frühere Parameter `steady` (Ergebnis von
    `metrics.steady_state.analyse_run`) ist entfallen. Er gehörte zur
    verworfenen β-Stop-Regel, und die Felder, die der Export daraus las,
    existierten im Kampagnenpfad gar nicht (Befund J-2).
    """
    config = engine.config
    zusammenfassung = engine.metrics.summary()
    alle = engine.metrics.retrievals

    # GEMEINSAMES ZEITFENSTER (2026-08-22, eine Quelle seit 2026-08-24)
    #
    # Die finale Kampagne laesst alle 50 Runs bis zur selben festen Zeit
    # laufen und wertet nur [t_measure_start, t_final] aus. Nur so sind
    # Durchsatz UND Verspaetung zwischen Policies vergleichbar: das System
    # laeuft gesaettigt, die Tardiness misst das Alter des Rueckstands und
    # waechst mit der Lauflaenge.
    fenster_modus, t_start, t_ende = measurement_window(engine)
    fenster = retrievals_in_window(alle, fenster_modus, t_start, t_ende)
    basis = fenster
    dauer = max((t_ende - t_start) if t_start is not None else engine.state.t, 1)

    if rq4 is None:
        rq4 = analyse_engine(engine)

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
    # Requests fuer die Service-KPIs auf dasselbe Fenster beziehen wie die
    # Retrievals. Sonst waeren `deadline_miss_rate` und `mean_tardiness` ueber
    # den ganzen Lauf gemittelt, waehrend `bin_throughput` nur das Fenster
    # misst - und die gepaarten Policy-Vergleiche waeren nicht mehr sauber.
    _requests = [r for r in engine.metrics.completed_requests
                 if is_in_measurement_window(r.get("time"), fenster_modus,
                                             t_start, t_ende)]

    _tard = sorted(max(0, r["time"] - r["latest_time"])
                   for r in _requests
                   if "latest_time" in r)
    _flow = [r["time"] - r["arrival_time"]
             for r in _requests
             if "arrival_time" in r]

    # BEFUND 2026-08-22: Die Abfrage lautete `hasattr(station, "utilization")`,
    # die Methode heisst aber `get_utilization`. Die Liste blieb deshalb IMMER
    # leer und `pickstation_utilisation_mean` war in jedem Lauf `None` - eine
    # still ausgefallene KPI.
    auslastungen = []
    for station in engine.state.pickstations:
        try:
            auslastungen.append(station.get_utilization(engine.state.t))
        except (AttributeError, TypeError):
            auslastungen.append(None)

    # Lastverteilung je Station.
    #
    # Ein Mittelwert kann eine starke Asymmetrie vollstaendig verdecken
    # (100 %/0 % und 50 %/50 % ergeben beide 50 %). Beobachtet wurde genau
    # das: waehrend PS_0 blockiert war, lief PS_1 leer (Klasse C).
    #
    # Exportiert wird das Minimum: Auslastung und Zahl der physischen
    # Retrievals JE Station. Anteile und eine etwaige Imbalance lassen sich
    # daraus ableiten und brauchen keine eigene gespeicherte KPI. Die
    # Stationszuordnung je Retrieval steht ohnehin schon in `retrievals.csv`.
    je_station = {}
    for zeile in basis:
        station_id = zeile.get("pickstation")
        je_station[station_id] = je_station.get(station_id, 0) + 1
    stationen = [s.station_id for s in engine.state.pickstations]

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
        "requests_completed": len(_requests),
        "request_throughput": len(_requests) / dauer,
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
        "pickstation_utilisation_ps0": (
            auslastungen[0] if len(auslastungen) > 0 else None),
        "pickstation_utilisation_ps1": (
            auslastungen[1] if len(auslastungen) > 1 else None),
        "retrievals_ps0": (
            je_station.get(stationen[0], 0) if len(stationen) > 0 else None),
        "retrievals_ps1": (
            je_station.get(stationen[1], 0) if len(stationen) > 1 else None),
        "measurement_retrievals": len(fenster),
        "measurement_mode": fenster_modus,
        "t_measure_start": t_start,
        "t_final": t_ende,
        "rq4_status": rq4.get("status"),
        "rq4_convergence_time_ZE": rq4.get("convergence_time"),
        "rq4_convergence_retrievals": rq4.get("convergence_retrievals"),
        "rq4_plateau_level": rq4.get("plateau_level"),
        "rq4_redivergence": rq4.get("redivergence"),
        "rq4_blocks": rq4.get("blocks"),
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


def retrieval_rows(run_id, policy, seed, engine):
    """
    Zeilen für `retrievals.csv`, inkl. Markierung des Measurement Windows.

    `in_measurement_window` kommt aus derselben Quelle wie das Fenster in
    `summarise_run`. Damit gilt für jeden einzelnen Run:

        sum(retrievals.csv.in_measurement_window)
        == runs.csv.measurement_retrievals

    Bis 2026-08-24 markierte diese Funktion aus dem alten,
    retrievalgezählten Steady-State-Fenster. Dessen Schlüssel existierte im
    Kampagnenpfad nicht, die Spalte war deshalb durchgehend `False` —
    während `runs.csv` korrekt zählte. Zwei Fensterbegriffe in einem Export
    (Befund J-1).
    """
    modus, t_start, t_ende = measurement_window(engine)

    for row in engine.metrics.retrievals:
        eintrag = {"run_id": run_id, "policy": policy, "seed": seed}
        eintrag.update({k: row.get(k) for k in RETRIEVAL_FIELDS
                        if k not in ("run_id", "policy", "seed",
                                     "in_measurement_window")})
        eintrag["in_measurement_window"] = is_in_measurement_window(
            row.get("t_pickstation"), modus, t_start, t_ende)
        yield eintrag


#: Die Dateien, die eine Zeile je Lauf oder je Ereignis eines Laufs tragen
#: und deshalb beim Wiederholen eines Laufs bereinigt werden muessen.
RUN_SCOPED_CSVS = ("runs.csv", "retrievals.csv", "requests.csv",
                   "distribution.csv")


def purge_runs(output_dir, run_ids):
    """
    Entfernt alle Zeilen der genannten Laeufe aus den Ausgabedateien.

    Warum das noetig ist
    --------------------
    Ein wiederholter Lauf darf am Ende GENAU EINEN wissenschaftlichen
    Datensatz haben. Ohne Bereinigung entsteht beim `--resume` nach einem
    Fehlschlag eine zweite Zeile mit derselben `run_id`: der abgebrochene
    Versuch und der geglueckte. Eine Auswertung, die nach `run_id`
    gruppiert, saehe zwei Replikationen desselben Seeds — nachgewiesen am
    2026-08-24 fuer `runs.csv` und `run_meta.json`.

    Der abgebrochene Versuch geht nicht verloren: er bleibt in
    `campaign_status.json` und in seiner Logdatei erhalten. Er ist
    Betriebshistorie, keine Messreihe.

    Die Bereinigung schreibt jede Datei ueber eine temporaere Datei und
    `replace()`, ist also gegen einen Abbruch mitten im Schreiben robust.

    Args:
        output_dir: Kampagnenordner.
        run_ids: Menge der zu entfernenden `run_id`s.

    Returns:
        dict `{dateiname: entfernte_zeilen}` — nur fuer Dateien, in denen
        tatsaechlich etwas entfernt wurde.
    """
    ordner = Path(output_dir)
    ids = set(run_ids)
    entfernt = {}
    if not ids:
        return entfernt

    for name in RUN_SCOPED_CSVS:
        pfad = ordner / name
        if not pfad.exists() or not pfad.stat().st_size:
            continue
        with open(pfad, newline="", encoding="utf-8") as fh:
            leser = csv.DictReader(fh)
            felder = leser.fieldnames
            if not felder or "run_id" not in felder:
                continue
            alle = list(leser)
        behalten = [z for z in alle if z.get("run_id") not in ids]
        weg = len(alle) - len(behalten)
        if not weg:
            continue
        tmp = pfad.with_suffix(pfad.suffix + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            schreiber = csv.DictWriter(fh, fieldnames=felder)
            schreiber.writeheader()
            schreiber.writerows(behalten)
        tmp.replace(pfad)
        entfernt[name] = weg

    meta_datei = ordner / "run_meta.json"
    if meta_datei.exists():
        try:
            meta = json.loads(meta_datei.read_text())
        except json.JSONDecodeError:
            meta = None
        if isinstance(meta, list):
            behalten = [m for m in meta if m.get("run_id") not in ids]
            if len(behalten) != len(meta):
                tmp = meta_datei.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(behalten, indent=2,
                                          ensure_ascii=False))
                tmp.replace(meta_datei)
                entfernt["run_meta.json"] = len(meta) - len(behalten)

    return entfernt


class ExperimentWriter:
    """
    Schreibt die vier Dateien inkrementell – ein Lauf nach dem anderen.

    Inkrementell, damit eine lange Kampagne bei einem Abbruch nicht die
    bereits gerechneten Läufe verliert.
    """

    def __init__(self, output_dir, mode="w"):
        """
        Args:
            mode: `"w"` schreibt die Dateien neu, `"a"` haengt an bereits
                vorhandene an. Das Anhaengen braucht der Run-Level-Restart
                der Kampagne (`--resume`): schon gerechnete Laeufe duerfen
                nicht verloren gehen und auch nicht doppelt erscheinen.
                Kopfzeilen werden im Anhaengemodus nicht wiederholt.
        """
        if mode not in ("w", "a"):
            raise ValueError(f"mode muss 'w' oder 'a' sein, nicht {mode!r}")
        self.dir = Path(output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode

        def oeffne(name):
            pfad = self.dir / name
            vorhanden = mode == "a" and pfad.exists() and pfad.stat().st_size
            return open(pfad, mode, newline="", encoding="utf-8"), bool(vorhanden)

        self._runs, runs_da = oeffne("runs.csv")
        self._retr, retr_da = oeffne("retrievals.csv")
        self._req, req_da = oeffne("requests.csv")
        self._dist, dist_da = oeffne("distribution.csv")
        self._run_writer = csv.DictWriter(self._runs, fieldnames=RUN_FIELDS)
        self._retr_writer = csv.DictWriter(self._retr, fieldnames=RETRIEVAL_FIELDS)
        self._req_writer = csv.DictWriter(self._req, fieldnames=REQUEST_FIELDS)
        if not runs_da:
            self._run_writer.writeheader()
        if not retr_da:
            self._retr_writer.writeheader()
        if not req_da:
            self._req_writer.writeheader()
        self._dist_writer = None
        self._dist_header_geschrieben = dist_da

        # Beim Anhaengen die bereits geschriebenen Metadaten uebernehmen,
        # sonst wuerde `close()` sie beim naechsten Lauf ueberschreiben.
        self._meta = []
        meta_datei = self.dir / "run_meta.json"
        if mode == "a" and meta_datei.exists():
            try:
                self._meta = json.loads(meta_datei.read_text())
            except json.JSONDecodeError:
                self._meta = []

    def add_run(self, run_id, policy, seed, engine, rq4=None, error=None,
                recoveries=0, unresolved=0):
        if rq4 is None:
            rq4 = analyse_engine(engine)
        self._run_writer.writerow(
            summarise_run(run_id, policy, seed, engine, rq4, error,
                          recoveries, unresolved))
        self._runs.flush()

        for zeile in retrieval_rows(run_id, policy, seed, engine):
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
                if not self._dist_header_geschrieben:
                    self._dist_writer.writeheader()
                    self._dist_header_geschrieben = True
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
            # Vollstaendige RQ4-Auswertung inklusive der TVD-Folge. Damit ist
            # jede Statuszuweisung im Nachhinein nachrechenbar, ohne den Lauf
            # zu wiederholen.
            "rq4": rq4,
            "measurement_window": dict(zip(
                ("mode", "t_measure_start", "t_final"),
                measurement_window(engine))),
        })
        # Nach JEDEM Lauf schreiben, nicht erst beim Schliessen.
        #
        # Die CSVs werden je Lauf geflusht, `run_meta.json` wurde dagegen nur
        # in `close()` erzeugt. Ein abgebrochener Prozess (OOM, Neustart,
        # SIGKILL) haette nach 30 gerechneten Laeufen vier gefuellte CSVs und
        # GAR KEINE Metadaten hinterlassen — und beim Fortsetzen waeren die
        # fehlenden 30 Eintraege stillschweigend nicht mehr aufgetaucht.
        self._schreibe_meta()

    def _schreibe_meta(self):
        tmp = self.dir / "run_meta.json.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._meta, fh, indent=2, ensure_ascii=False)
        tmp.replace(self.dir / "run_meta.json")

    def close(self):
        self._runs.close()
        self._retr.close()
        self._req.close()
        self._dist.close()
        self._schreibe_meta()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
