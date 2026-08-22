#!/usr/bin/env python3
"""
Fortsetzbarer Steady-State-Pilot fuer den Final Freeze Closeout.

Die Umgebung erlaubt nur kurze Rechenscheiben. Ein Pilotlauf wird deshalb in
Scheiben gerechnet: jede Scheibe laedt den vollstaendigen Engine-Zustand aus
einem Pickle, rechnet bis zum Wall-Budget weiter und schreibt Zustand und
Zwischenergebnis zurueck.

Das ist keine Naeherung: der gesamte Simulationszustand inklusive aller
RNG-Stroeme steckt im Engine-Objekt, eine fortgesetzte Scheibe rechnet also
exakt dieselbe Trajektorie wie ein ununterbrochener Lauf. Geprueft wird das
zusaetzlich durch `verify_resume_identity.py`.

Aufruf:
    pilot_slice.py <policy> <seed> <sim_time> <out_dir> <wall_budget_s>
"""

import contextlib
import io
import json
import pickle
import sys
import time
from pathlib import Path

REPO = "/sessions/youthful-busy-noether/mnt/compact-storage-simulation"
sys.path.insert(0, REPO)
sys.setrecursionlimit(200000)

from simulation.simulation_engine import SimulationEngine  # noqa: E402
from events.event import Event  # noqa: E402
from pilot_run import build_config, retrieval_rows, snapshot_rows  # noqa: E402


def main():
    policy, seed, sim_time = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out_dir = Path(sys.argv[4])
    wall_budget = float(sys.argv[5])
    # Genug Retrievals fuer Konvergenz (3 Bloecke = 150) plus Measurement
    # Window (100) plus Reserve. Danach ist die Frage beantwortet, wie viele
    # ZE die Stop-Regel kostet; weiterrechnen bringt keine Erkenntnis.
    target_retrievals = int(sys.argv[6]) if len(sys.argv) > 6 else 320
    # Vergleichsmodus: mit dem ALTEN Initialzustand (Pufferzone initial
    # belegt) rechnen, um zu belegen, ob ein Befund vorbestehend ist.
    if len(sys.argv) > 7 and sys.argv[7] == "old":
        import simulation.simulation_engine as se
        se.calculate_buffer_zone = lambda **kw: set()
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{policy.replace('+', '_')}__seed{seed}"
    state_file = out_dir / f"{stem}.pkl"
    json_file = out_dir / f"{stem}.json"
    log_file = out_dir / f"{stem}.logcount.json"

    counters = {"move_recovery_unresolved": 0, "deadlock_detected": 0,
                "log_lines": 0, "slices": 0, "wall_seconds": 0.0}
    if log_file.exists():
        counters.update(json.loads(log_file.read_text()))

    if state_file.exists():
        with open(state_file, "rb") as fh:
            blob = pickle.load(fh)
        # `Event._next_event_id` ist eine KLASSENvariable und wird nicht mit
        # den Instanzen gepickelt. Ohne Wiederherstellung beginnt der neue
        # Prozess wieder bei 0; neue Events sortieren dann VOR den bereits
        # wartenden (Event.__lt__ nutzt event_id als Tie-Break) und die
        # Trajektorie weicht ab. Innerhalb eines Prozesses faellt das nicht
        # auf - genau deshalb war es zunaechst unsichtbar.
        engine = blob["engine"]
        Event._next_event_id = blob["next_event_id"]
        if engine.config.simulation_time != sim_time:
            engine.config.simulation_time = sim_time
    else:
        engine = SimulationEngine(build_config(policy, seed, sim_time))

    if getattr(engine, "_pilot_finished", False):
        print(f"skip {policy} seed={seed} already finished t_end={engine.state.t}")
        return

    started = time.time()
    error = None
    finished = False
    reason = "wall_budget"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            while True:
                if engine.step() is None:
                    finished, reason = True, "sim_time_or_events"
                    break
                if len(engine.metrics.retrievals) >= target_retrievals:
                    finished, reason = True, "target_retrievals"
                    break
                if time.time() - started >= wall_budget:
                    break
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            error = f"{type(exc).__name__}: {exc}"
            finished, reason = True, "exception"

    log = buf.getvalue()
    counters["move_recovery_unresolved"] += log.count("MOVE_RECOVERY_UNRESOLVED")
    counters["unbury"] = counters.get("unbury", 0) + log.count("[UNBURY]")
    counters["task_deadlock"] = counters.get("task_deadlock", 0) + log.count("[TASK_DEADLOCK]")
    counters["stale_pickup_no_task"] = counters.get("stale_pickup_no_task", 0) + log.count("[STALE][PICKUP_NO_TASK]")
    counters["drop_bury_redirect"] = counters.get("drop_bury_redirect", 0) + log.count("[REPLAN][DROP_BURY]")
    counters["deadlock_detected"] += log.count("[DEADLOCK] Detected")
    counters["log_lines"] += len(log.splitlines())
    counters["slices"] += 1
    counters["wall_seconds"] += round(time.time() - started, 1)
    if error:
        counters["error"] = error

    engine._pilot_finished = finished

    payload = {
        "policy": policy,
        "seed": seed,
        "sim_time_limit": sim_time,
        "t_end": engine.state.t,
        "finished": finished,
        "stop_reason": reason,
        "target_retrievals": target_retrievals,
        "error": counters.get("error"),
        "retrievals": retrieval_rows(engine),
        "distribution": snapshot_rows(engine),
        "requests_completed": len(getattr(engine.metrics, "completed_requests", [])),
        "counters": counters,
    }
    tmp = Path(str(json_file) + ".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(json_file)
    log_file.write_text(json.dumps(counters))

    # Bei einer Exception bleibt der Zustand erhalten: er ist das
    # Diagnosematerial fuer die Ursache des Abbruchs.
    if finished and reason != "exception":
        state_file.unlink(missing_ok=True)
    else:
        tmp_pkl = Path(str(state_file) + ".tmp")
        with open(tmp_pkl, "wb") as fh:
            pickle.dump({"engine": engine,
                         "next_event_id": Event._next_event_id},
                        fh, pickle.HIGHEST_PROTOCOL)
        tmp_pkl.replace(state_file)

    print(f"slice {policy} seed={seed} t_end={engine.state.t} "
          f"retr={len(payload['retrievals'])} finished={finished} err={error}")


if __name__ == "__main__":
    main()
