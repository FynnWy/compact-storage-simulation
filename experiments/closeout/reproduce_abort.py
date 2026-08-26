"""
Faehrt eine Policy/Seed-Kombination bis zum Abbruch und protokolliert die
letzten Logzeilen sowie den Zustand unmittelbar davor.

Gedacht fuer `RR+RR` Seed 1, das mit
`Event exceeded max retries (20). action_type=return` endet.
"""
import contextlib
import io
import re
import sys
from collections import Counter

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

from simulation.simulation_engine import SimulationEngine  # noqa: E402
from pilot_run import build_config  # noqa: E402

policy = sys.argv[1]
seed = int(sys.argv[2])
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40000

engine = SimulationEngine(build_config(policy, seed, limit))
buf = io.StringIO()
error = None
with contextlib.redirect_stdout(buf):
    try:
        while engine.step() is not None:
            pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

log = buf.getvalue().splitlines()
st = engine.state
print(f"### {policy} seed={seed}")
print(f"t_end={st.t}  retrievals={len(engine.metrics.retrievals)}  error={error}")
letztes = engine.metrics.retrievals[-1]["t_pickstation"] if engine.metrics.retrievals else None
print(f"letztes Retrieval t={letztes}  Stillstand={st.t - (letztes or 0)} ZE")

muster = Counter(re.sub(r"\d+", "N", l).strip() for l in log[-4000:])
print("\nHaeufigste Meldungen der letzten 4000 Zeilen:")
for norm, n in muster.most_common(14):
    print(f"  {n:6d}  {norm[:150]}")

print("\nLetzte 25 Zeilen:")
for line in log[-25:]:
    print("   ", line[:170])

print("\nRoboter beim Abbruch:")
for r in st.robots:
    t = getattr(r, "current_task", None)
    temp = getattr(t, "temp_storage", None) or []
    print(f"  robot {r.robot_id} pos={r.position} "
          f"carrying={getattr(r, 'carried_bin', None)} "
          f"phase={getattr(t, 'phase', None)} target={getattr(t, 'target_bin_id', None)} "
          f"offene_blocker={len(temp)}")

print("\nPickstations:")
for ps in st.pickstations:
    print(f"  {ps.station_id} pos={ps.position} slots={ps.available_slots}/{ps.capacity} "
          f"robot_on_port={getattr(ps, 'robot_on_port', None)} "
          f"reserved_for_robot={getattr(ps, 'reserved_for_robot', None)} "
          f"queue={len(ps.queue)}")
