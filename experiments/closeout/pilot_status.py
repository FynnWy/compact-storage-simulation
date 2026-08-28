"""Fortschritts- und Stall-Uebersicht ueber alle Pilot-Laeufe."""
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
bucket = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

for f in sorted(out_dir.glob("*.json")):
    if f.name.endswith(".logcount.json"):
        continue
    d = json.loads(f.read_text())
    ts = [r["t"] for r in d["retrievals"] if r["t"] is not None]
    t_end = d["t_end"]
    curve = []
    for b in range(0, t_end + 1, bucket):
        curve.append(sum(1 for t in ts if t <= b + bucket))
    last_t = ts[-1] if ts else 0
    stall = t_end - last_t
    print(f"{d['policy']:24s} seed={d['seed']:<3d} t_end={t_end:<6d} "
          f"retr={len(ts):<4d} last_retr_t={last_t:<6d} stall={stall:<6d} "
          f"fin={d['finished']} {d.get('stop_reason') or ''} {d.get('error') or ''}")
    print(f"    per {bucket} ZE: {curve}")
