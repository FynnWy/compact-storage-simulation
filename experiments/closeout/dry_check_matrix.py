#!/usr/bin/env python3
"""
Trockenlauf der finalen Kampagnenmatrix: 5 Policies x 10 Seeds = 50 Runs.

Zweck ist NICHT, Ergebnisse zu erzeugen, sondern zu belegen, dass die
Kampagne strukturell durchlaeuft, bevor sie 50 x 30.000 ZE kostet:

* jede der 50 Kombinationen startet und laeuft ohne Ausnahme,
* das gemeinsame Zeitfenster `[t_measure_start, t_final]` greift
  (`measurement_mode == "time_window"`),
* `summarise_run` liefert fuer jede Kombination eine vollstaendige
  `runs.csv`-Zeile ohne fehlende Pflichtfelder,
* die Seeds erzeugen paarweise verschiedene Nachfragestroeme (CRN-Prinzip:
  gleicher Seed -> gleicher Strom ueber alle Policies hinweg),
* keine Kombination hinterlaesst einen verwaisten Roboter.

Der Horizont ist bewusst kurz. Ein struktureller Fehler (fehlendes Feld,
falscher Fenstermodus, Exception in einer Policy) zeigt sich sofort; die
Laufzeitfrage ist durch die Kalibration getrennt beantwortet.

Aufruf:
    dry_check_matrix.py [sim_time] [t_measure_start] [policy[,policy...]]
"""
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from experiments.campaign_matrix import (  # noqa: E402
    FINAL_POLICIES, FINAL_SEEDS, build_run_config,
)
from experiments.run_export import (  # noqa: E402
    RUN_FIELDS, request_rows, retrieval_rows, summarise_run,
)
from simulation.simulation_engine import SimulationEngine  # noqa: E402

#: Dieselbe Quelle wie der Kampagnentreiber - keine zweite Matrixdefinition.
SEEDS = list(FINAL_SEEDS)
POLICIES = dict(FINAL_POLICIES)

# Felder, die auch bei einem kurzen Lauf gefuellt sein MUESSEN. Rein
# statistische Felder (Quantile der Tardiness) duerfen leer bleiben, wenn im
# kurzen Fenster kein einziger Request verspaetet fertig wurde - das ist eine
# Eigenschaft des Kurzlaufs, kein Strukturfehler.
PFLICHT = [
    "run_id", "policy", "seed",
    "reordering_strategy", "placement_strategy", "return_blocking_bins",
    "grid_width", "grid_depth", "max_stack_height", "bin_num",
    "num_robots", "num_pickstations", "request_utilization",
    "zipf_parameter", "simulation_time",
    "t_end", "physical_retrievals", "bin_throughput",
    "requests_completed", "request_throughput",
    "measurement_mode", "t_measure_start", "t_final",
    # RQ4: der Status ist immer gesetzt. Konvergenzzeit, Retrievalzahl und
    # Plateauniveau sind ausdruecklich BEDINGT - sie existieren nur, wenn ein
    # Plateau gefunden wurde. In einem Kurzlauf mit weniger als R=50
    # Retrievals gibt es keinen einzigen Block; `not_converged` ist dann die
    # korrekte Antwort und kein Strukturfehler.
    "rq4_status",
]


def gestrandete(engine):
    """Roboter mit Task, aber ohne jedes zukuenftige Event."""
    treffer = []
    for r in engine.state.robots:
        if r.current_task is None:
            continue
        hat_event = False
        for item in engine.state.event_queue.queue:
            ev = item[-1] if isinstance(item, tuple) else item
            payload = ev.payload if isinstance(ev.payload, dict) else {}
            if getattr(payload.get("robot"), "robot_id", None) == r.robot_id:
                hat_event = True
                break
        if not hat_event:
            treffer.append(r.robot_id)
    return treffer


def nachfrage_fingerprint(engine):
    """
    Hash ueber den VORAB erzeugten Nachfragestrom.

    Wichtig: gehasht wird `future_request_queue` VOR dem Lauf, nicht die
    Menge der fertig bedienten Requests. Welche Requests ein Lauf schafft,
    haengt von der Policy ab - ein Hash darueber wuerde CRN scheinbar
    verletzen, obwohl der Eingangsstrom identisch ist.
    """
    roh = "|".join(
        f"{r.request_id}:{r.target_box_id}:{r.arrival_time}:{r.latest_time}"
        for _, r in sorted(engine.state.future_request_queue.queue,
                           key=lambda x: x[1].request_id)
    )
    return hashlib.sha256(roh.encode()).hexdigest()[:16]


def einer(policy, seed, sim_time, t_measure_start):
    config = build_run_config(policy, seed, sim_time=sim_time,
                              t_measure_start=t_measure_start,
                              t_final=sim_time)
    engine = SimulationEngine(config)
    fingerprint = nachfrage_fingerprint(engine)

    fehler = None
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            fehler = f"{type(exc).__name__}: {exc}"

    run_id = f"{policy}__seed{seed}"
    zeile = summarise_run(run_id, policy, seed, engine, error=fehler)
    anfragen = list(request_rows(run_id, policy, seed, engine))
    entnahmen = list(retrieval_rows(run_id, policy, seed, engine))

    fehlend = [f for f in PFLICHT if zeile.get(f) in (None, "")]
    unbekannt = [f for f in zeile if f not in RUN_FIELDS]

    # Konsistenz der ZWEI Fensterdefinitionen im selben Export:
    # `runs.csv` aggregiert ueber [t_measure_start, t_final];
    # `retrievals.csv` markiert jede Zeile mit `in_measurement_window`.
    # Beide muessen dieselbe Menge meinen, sonst widersprechen sich die
    # Run-Level-KPI und jede Analyse auf Retrieval-Ebene.
    markiert = sum(1 for r in entnahmen if r["in_measurement_window"])
    erwartet = zeile.get("measurement_retrievals")

    return {
        "policy": policy,
        "seed": seed,
        "error": fehler,
        "t_end": zeile.get("t_end"),
        "mode": zeile.get("measurement_mode"),
        "retr": zeile.get("physical_retrievals"),
        "req": len(anfragen),
        "retr_rows": len(entnahmen),
        "im_fenster": markiert,
        "erwartet_im_fenster": erwartet,
        "fenster_konsistent": markiert == erwartet,
        "fehlende_felder": fehlend,
        "unbekannte_felder": unbekannt,
        "gestrandet": gestrandete(engine),
        "fingerprint": fingerprint,
    }


def main():
    sim_time = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    t_start = int(sys.argv[2]) if len(sys.argv) > 2 else sim_time // 2
    policies = (sys.argv[3].split(",") if len(sys.argv) > 3
                else list(POLICIES))
    # Optionale Seed-Teilmenge: die volle Matrix passt nicht in ein
    # Zeitbudget, die langsameren Policies muessen geteilt werden.
    seeds = ([int(s) for s in sys.argv[4].split(",")] if len(sys.argv) > 4
             else SEEDS)

    # Inkrementell: die Matrix passt nicht in ein Zeitbudget. Jeder Aufruf
    # rechnet die uebergebenen Policies und ersetzt deren Zeilen; das Urteil
    # wird ueber ALLE bisher gerechneten Zeilen gebildet.
    ziel = HERE / "results" / "matrix_dry_check.json"
    zeilen = []
    if ziel.exists():
        alt = json.loads(ziel.read_text())
        if (alt.get("sim_time") == sim_time
                and alt.get("t_measure_start") == t_start):
            zeilen = [z for z in alt.get("runs", [])
                      if not (z["policy"] in policies and z["seed"] in seeds)]

    for policy in policies:
        for seed in seeds:
            e = einer(policy, seed, sim_time, t_start)
            zeilen.append(e)
            print(f"{e['policy']:24s} seed={e['seed']:<4d} t_end={e['t_end']:<5} "
                  f"mode={e['mode']:<12s} retr={e['retr']:<4} "
                  f"req={e['req']:<4d} "
                  f"imFenster={e['im_fenster']}/{e['erwartet_im_fenster']} "
                  f"strand={e['gestrandet']} fp={e['fingerprint']} "
                  f"fehlend={e['fehlende_felder']} err={e['error']}")

    print()
    fehler = [z for z in zeilen if z["error"]]
    luecken = [z for z in zeilen if z["fehlende_felder"]]
    fremd = [z for z in zeilen if z["unbekannte_felder"]]
    strand = [z for z in zeilen if z["gestrandet"]]
    falsch = [z for z in zeilen if z["mode"] != "time_window"]
    inkons = [z for z in zeilen if not z["fenster_konsistent"]]

    # CRN: gleicher Seed -> gleicher Nachfragestrom ueber alle Policies.
    je_seed = {}
    for z in zeilen:
        je_seed.setdefault(z["seed"], set()).add(z["fingerprint"])
    crn_bruch = {s: fps for s, fps in je_seed.items() if len(fps) > 1}
    # Verschiedene Seeds muessen verschiedene Stroeme liefern.
    alle_fp = {s: next(iter(fps)) for s, fps in je_seed.items()
               if len(fps) == 1}
    kollision = len(set(alle_fp.values())) != len(alle_fp)

    print(f"Kombinationen           : {len(zeilen)}")
    print(f"Exceptions              : {len(fehler)}")
    print(f"Zeilen mit Luecken      : {len(luecken)}")
    print(f"unbekannte Felder       : {len(fremd)}")
    print(f"verwaiste Roboter       : {len(strand)}")
    print(f"falscher Fenstermodus   : {len(falsch)}")
    print(f"Fenster inkonsistent    : {len(inkons)}   "
          f"(runs.csv vs. retrievals.csv)")
    print(f"CRN-Bruch (Seed->Strom) : {len(crn_bruch)}")
    print(f"Seed-Kollision          : {kollision}")

    ok = not (fehler or luecken or fremd or strand or falsch or inkons
              or crn_bruch or kollision)
    print(f"\nVERDICT: {'MATRIX DRY-CHECK PASS' if ok else 'MATRIX DRY-CHECK FAIL'}")

    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(
        {"sim_time": sim_time, "t_measure_start": t_start,
         "seeds": SEEDS,
         "policies": sorted({z["policy"] for z in zeilen}),
         "pass": ok, "runs": zeilen},
        indent=2))
    print(f"geschrieben: {ziel}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
