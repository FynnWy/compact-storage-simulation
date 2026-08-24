#!/usr/bin/env python3
"""
Treiber fuer die symmetrische RQ4-Kalibrationsmatrix.

    5 Policies x Seeds 1, 7, 42 = 15 Laeufe, Zielhorizont 30.000 ZE

Waehlt je Aufruf die N Laeufe mit dem geringsten Fortschritt und rechnet sie
parallel eine Scheibe weiter. Wiederholtes Aufrufen bringt die Matrix
gleichmaessig voran.

Aufruf: calib_batch.py <out_dir> <wall_budget_s> [parallel] [sim_time]
"""
import json
import subprocess
import sys
from pathlib import Path

POLICIES = ["baseline_reference", "RR+RR", "LR+NR", "ABC+ABC",
            "POPULARITY+POPULARITY"]
SEEDS = [1, 7, 42]
TARGET = 10 ** 9  # nur die Zeitgrenze soll stoppen

# Kalibration braucht 30.000 ZE. Der Hauptregressionsfall der
# Lifecycle-Behebung laeuft bis zum vollen finalen Horizont, damit auch das
# gemeinsame Messfenster [30.000, 42.000] nachweislich erreicht wird.
SONDERHORIZONT = {("ABC+ABC", 7): "42000"}

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
                             len(d["retrievals"])))
            else:
                rows.append((policy, seed, False, 0, 0))
    return rows


def main():
    out_dir = Path(sys.argv[1])
    wall = sys.argv[2]
    parallel = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    sim_time = sys.argv[4] if len(sys.argv) > 4 else "30000"
    # Optional: nur eine Teilmenge der Policies rechnen. Gebraucht, wenn eine
    # Aenderung nachweislich nur bestimmte Policies betrifft — RR+RR und LR+NR
    # laufen ohne Ordered Return und sind von Reordering-Aenderungen
    # bit-identisch unberuehrt (nachgewiesen durch Spurvergleich).
    if len(sys.argv) > 5:
        global POLICIES
        POLICIES = [p for p in sys.argv[5].split(",") if p]
    out_dir.mkdir(parents=True, exist_ok=True)

    offen = [r for r in status(out_dir) if not r[2]]
    if not offen:
        print("ALLE LAEUFE FERTIG")
    else:
        offen.sort(key=lambda r: r[3])
        batch = offen[:parallel]
        procs = []
        for policy, seed, *_ in batch:
            horizont = SONDERHORIZONT.get((policy, seed), sim_time)
            procs.append(subprocess.Popen(
                [sys.executable, str(HERE / "pilot_slice.py"), policy,
                 str(seed), horizont, str(out_dir), wall, str(TARGET)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        for p in procs:
            out, _ = p.communicate()
            print(out.strip())

    zeilen = status(out_dir)
    fertig = sum(1 for r in zeilen if r[2])
    gesamt_ze = sum(r[3] for r in zeilen)
    print(f"\nFortschritt: {fertig}/{len(zeilen)} fertig, "
          f"{gesamt_ze} ZE gesamt")
    for policy, seed, fin, t_end, retr in zeilen:
        print(f"  {policy:24s} seed={seed:<3d} t_end={t_end:<6d} "
              f"retr={retr:<4d} {'FERTIG' if fin else ''}")


if __name__ == "__main__":
    main()
