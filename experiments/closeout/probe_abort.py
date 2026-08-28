"""
Ist der Abbruch `Event exceeded max retries (20)` neu oder vorbestehend?

Faehrt dieselbe Policy/Seed-Kombination mit dem ALTEN Initialzustand
(Pufferzone initial belegt) und meldet, ob und wann sie abbricht.
"""
import contextlib, io, sys, time

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

import simulation.simulation_engine as se
from utils.port_buffer_zone import calculate_buffer_zone as cbz
from simulation.simulation_engine import SimulationEngine
from pilot_run import build_config


def run(policy, seed, limit, old, wall=150.0):
    se.calculate_buffer_zone = (lambda **kw: set()) if old else cbz
    e = SimulationEngine(build_config(policy, seed, limit))
    started = time.time()
    err = None
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while e.step() is not None:
                if time.time() - started >= wall:
                    break
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
    return dict(policy=policy, seed=seed, old=old, t_end=e.state.t,
                retr=len(e.metrics.retrievals), err=err)


if __name__ == "__main__":
    policy = sys.argv[1]
    seed = int(sys.argv[2])
    old = sys.argv[3] == "old"
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 40000
    wall = float(sys.argv[5]) if len(sys.argv) > 5 else 150.0
    print(run(policy, seed, limit, old, wall))
