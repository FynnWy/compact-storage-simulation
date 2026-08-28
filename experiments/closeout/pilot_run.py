#!/usr/bin/env python3
"""
Steady-State-Pilot fuer den Final Freeze Closeout.

Ein Lauf je Policy x Seed. Die Stop-Regel wird NICHT im Lauf angewandt,
sondern anschliessend offline auf der vollstaendigen Retrieval-Spur
ausgewertet. Dadurch laesst sich dieselbe Spur gegen mehrere
Kandidaten-Obergrenzen pruefen, ohne neu zu rechnen.

Der Lauf schreibt in festen Abstaenden einen Checkpoint, damit ein
abgebrochener Prozess keine Messung verliert. `wall_budget` begrenzt die
Rechenzeit; `t_end` haelt fest, wie weit der Lauf tatsaechlich kam.

Aufruf:
    pilot_run.py <policy> <seed> <sim_time> <out_dir> [wall_budget_s]
"""

import contextlib
import io
import json
import sys
import time
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from experiments.campaign_matrix import (  # noqa: E402
    FINAL_POLICIES, build_run_config)
from simulation.simulation_engine import SimulationEngine  # noqa: E402


#: Eine Quelle fuer die Policy-Definition (`experiments/campaign_matrix.py`).
#: Der Name bleibt, weil mehrere Closeout-Skripte ihn importieren.
POLICIES = FINAL_POLICIES


def build_config(policy, seed, sim_time):
    """
    Kalibrations-/Pilotkonfiguration.

    Identisch zur finalen Kampagnenkonfiguration, nur mit frei waehlbarem
    Horizont und OHNE gesetztes Auswertungsfenster: die Piloten exportieren
    die vollstaendige Spur, das Fenster wird offline gelegt.

    Seit 2026-08-24 delegiert die Funktion an
    `experiments.campaign_matrix.build_run_config`. Die erzeugte
    Konfiguration ist feldweise unveraendert — nachgewiesen in
    `tests/test_campaign_matrix.py`; die vorhandene Kalibration bleibt
    dadurch gueltig.
    """
    return build_run_config(policy, seed, sim_time=sim_time,
                            t_measure_start=None, t_final=None)


def retrieval_rows(engine):
    return [
        {
            "t": r.get("t_pickstation"),
            "bin_id": r.get("bin_id"),
            "abc_class": r.get("abc_class"),
            "level": r.get("level"),
            "stack_height": r.get("stack_height"),
            "levels_from_top": r.get("levels_from_top"),
            "blocking_bins": r.get("blocking_bins"),
            "batch_size": r.get("batch_size"),
            "dig_duration": r.get("dig_duration"),
        }
        for r in engine.metrics.retrievals
    ]


def snapshot_rows(engine):
    snaps = engine.metrics.get_distribution_timeseries() or []
    return [dict(s) for s in snaps]


def write(target, engine, policy, seed, sim_time, started, error, log,
          stopped_by):
    payload = {
        "policy": policy,
        "seed": seed,
        "sim_time_limit": sim_time,
        "t_end": engine.state.t,
        "stopped_by": stopped_by,
        "wall_seconds": round(time.time() - started, 1),
        "error": error,
        "retrievals": retrieval_rows(engine),
        "distribution": snapshot_rows(engine),
        "requests_completed": len(getattr(engine.metrics, "completed_requests", [])),
        "log_move_recovery_unresolved": log.count("MOVE_RECOVERY_UNRESOLVED"),
        "log_deadlock_detected": log.count("[DEADLOCK] Detected"),
        "log_lines": len(log.splitlines()),
    }
    tmp = Path(str(target) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    tmp.replace(target)
    return payload


def main():
    policy = sys.argv[1]
    seed = int(sys.argv[2])
    sim_time = int(sys.argv[3])
    out_dir = Path(sys.argv[4])
    wall_budget = float(sys.argv[5]) if len(sys.argv) > 5 else 520.0
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{policy.replace('+', '_')}__seed{seed}.json"

    config = build_config(policy, seed, sim_time)
    started = time.time()
    engine = SimulationEngine(config)

    error = None
    stopped_by = "sim_time"
    buf = io.StringIO()
    next_checkpoint = started + 60.0
    with contextlib.redirect_stdout(buf):
        try:
            while engine.step() is not None:
                now = time.time()
                if now >= next_checkpoint:
                    write(target, engine, policy, seed, sim_time, started,
                          error, buf.getvalue(), "checkpoint")
                    next_checkpoint = now + 60.0
                    if now - started >= wall_budget:
                        stopped_by = "wall_budget"
                        break
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            error = f"{type(exc).__name__}: {exc}"
            stopped_by = "exception"

    payload = write(target, engine, policy, seed, sim_time, started, error,
                    buf.getvalue(), stopped_by)
    print(f"done {policy} seed={seed} t_end={payload['t_end']} "
          f"retrievals={len(payload['retrievals'])} "
          f"wall={payload['wall_seconds']}s stopped_by={stopped_by} error={error}")


if __name__ == "__main__":
    main()
