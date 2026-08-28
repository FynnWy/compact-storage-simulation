#!/usr/bin/env python3
"""
Treiber fuer die Pilot-Scheiben.

Waehlt die N unfertigen Laeufe mit dem geringsten Fortschritt und rechnet sie
parallel eine Scheibe weiter. Wiederholtes Aufrufen bringt die gesamte
Pilotmatrix Stueck fuer Stueck ans Ziel.

Aufruf: pilot_batch.py <out_dir> <wall_budget_s> [parallel]
"""
import json
import subprocess
import sys
from pathlib import Path

POLICIES = ["baseline_reference", "RR+RR", "LR+NR", "ABC+ABC",
            "POPULARITY+POPULARITY"]
SEEDS = [42, 1, 7]
SIM_TIME = 40000
TARGET = 320

HERE = Path(__file__).resolve().parent


def status(out_dir):
    rows = []
    for policy in POLICIES:
        for seed in SEEDS:
            stem = f"{policy.replace('+', '_')}__seed{seed}"
            f = out_dir / f"{stem}.json"
            if f.exists():
                d = json.loads(f.read_text())
                rows.append((policy, seed, d["finished"], d["t_end"],
                             len(d["retrievals"]), d.get("stop_reason")))
            else:
                rows.append((policy, seed, False, 0, 0, None))
    return rows


def main():
    out_dir = Path(sys.argv[1])
    wall = sys.argv[2]
    parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    out_dir.mkdir(parents=True, exist_ok=True)

    pending = [r for r in status(out_dir) if not r[2]]
    if not pending:
        print("ALL DONE")
        for r in status(out_dir):
            print(f"  {r[0]:24s} seed={r[1]:<3d} t_end={r[3]:<6d} retr={r[4]:<4d} {r[5]}")
        return

    pending.sort(key=lambda r: r[4])
    batch = pending[:parallel]

    procs = []
    for policy, seed, *_ in batch:
        procs.append(subprocess.Popen(
            [sys.executable, str(HERE / "pilot_slice.py"), policy, str(seed),
             str(SIM_TIME), str(out_dir), wall, str(TARGET)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
    for p in procs:
        out, _ = p.communicate()
        print(out.strip())

    done = sum(1 for r in status(out_dir) if r[2])
    print(f"progress: {done}/{len(POLICIES) * len(SEEDS)} runs finished")


if __name__ == "__main__":
    main()
