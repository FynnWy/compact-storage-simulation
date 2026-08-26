"""
Verfolgt, wie ein Roboter zu einer getragenen Bin kommt, die nicht zu seinem
aktuellen Task gehoert (Stall-Klasse B).

Loggt jede Aenderung von `Robot.carried_bin_id` samt Task-Kontext und gibt am
Ende die letzten Uebergaenge sowie den Endzustand aus.
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

from simulation.simulation_engine import SimulationEngine  # noqa: E402
from state.robot import Robot  # noqa: E402
from pilot_run import build_config  # noqa: E402

policy, seed = sys.argv[1], int(sys.argv[2])
bis_t = int(sys.argv[3])
beobachtet = int(sys.argv[4]) if len(sys.argv) > 4 else -1  # Roboter-ID oder -1

engine = SimulationEngine(build_config(policy, seed, 40000))

log = []
orig_set = Robot.set_carried_bin
orig_clear = Robot.clear_carried_bin


def set_carried(self, bin_id):
    t = getattr(self, "current_task", None)
    log.append((engine.state.t, self.robot_id, "PICKUP", bin_id,
                getattr(t, "target_bin_id", None), getattr(t, "phase", None),
                getattr(t, "request_id", None), self.position))
    return orig_set(self, bin_id)


def clear_carried(self):
    t = getattr(self, "current_task", None)
    log.append((engine.state.t, self.robot_id, "DROP", self.carried_bin_id,
                getattr(t, "target_bin_id", None), getattr(t, "phase", None),
                getattr(t, "request_id", None), self.position))
    return orig_clear(self)


Robot.set_carried_bin = set_carried
Robot.clear_carried_bin = clear_carried

with contextlib.redirect_stdout(io.StringIO()):
    while engine.state.t < bis_t:
        if engine.step() is None:
            break

Robot.set_carried_bin = orig_set
Robot.clear_carried_bin = orig_clear

print(f"### {policy} seed={seed}  t={engine.state.t}  "
      f"retrievals={len(engine.metrics.retrievals)}")

print("\nRoboter mit Bin, die NICHT zum aktuellen Task gehoert:")
verdaechtig = []
for r in engine.state.robots:
    t = getattr(r, "current_task", None)
    carried = r.get_carried_bin()
    ziel = getattr(t, "target_bin_id", None)
    if carried is not None and t is not None and carried != ziel:
        eigene_blocker = {e.get("bin_id") for e in (getattr(t, "temp_storage", None) or [])
                          if isinstance(e, dict)}
        art = "eigener Blocker" if carried in eigene_blocker else "FREMD"
        verdaechtig.append(r.robot_id)
        print(f"  robot {r.robot_id} traegt {carried}, Task-Ziel {ziel}, "
              f"phase={t.phase}, request={t.request_id}, pos={r.position} -> {art}")
if not verdaechtig:
    print("  keine")

zeigen = verdaechtig if beobachtet < 0 else [beobachtet]
for rid in zeigen:
    print(f"\nLetzte Carry-Uebergaenge von robot {rid}:")
    eintraege = [z for z in log if z[1] == rid][-14:]
    for t, r, art, bin_id, ziel, phase, req, pos in eintraege:
        print(f"  t={t:6d} {art:6s} bin={bin_id} task_ziel={ziel} "
              f"phase={phase} request={req} pos={pos}")
