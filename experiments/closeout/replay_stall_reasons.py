"""
Setzt einen festgefahrenen Lauf einige Schritte fort und protokolliert, WARUM
die Events scheitern. Die Simulation loggt ihre Retry-/Replan-Gruende auf
stdout; hier werden sie eingesammelt und verdichtet.
"""
import contextlib
import io
import re
import sys
from collections import Counter

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')
sys.setrecursionlimit(200000)

from pilot_state import load_engine  # noqa: E402

path = sys.argv[1]
steps = int(sys.argv[2]) if len(sys.argv) > 2 else 400

e = load_engine(path)

t0 = e.state.t
r0 = len(e.metrics.retrievals)

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    for _ in range(steps):
        if e.step() is None:
            break

log = buf.getvalue().splitlines()
print(f"### {path}")
print(f"t {t0} -> {e.state.t}   Retrievals {r0} -> {len(e.metrics.retrievals)}   "
      f"Logzeilen={len(log)}")

# Zeilen normalisieren: Zahlen raus, damit sich Muster zaehlen lassen
muster = Counter()
for line in log:
    norm = re.sub(r"\d+", "N", line).strip()
    muster[norm] += 1
print("\nHaeufigste Meldungen:")
for norm, n in muster.most_common(18):
    print(f"  {n:6d}  {norm[:150]}")

print("\nErste 25 Originalzeilen:")
for line in log[:25]:
    print("   ", line[:160])
