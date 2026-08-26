"""
Schnelle Reproduktion eines Fortschritts-Stillstands auf einem kleinen Grid.

Das 7x7-Szenario aus `tests/test_strategy_correctness.build_engine` faehrt
sich in unter zwei Minuten fest und eignet sich deshalb als Arbeitsfall,
bevor die teuren Laeufe auf der finalen Geometrie angefasst werden.
"""
import contextlib
import io
import re
import sys
from collections import Counter

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from config.simulation_config import SimulationConfig  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402


def build(reordering="POPULARITY", placement="POPULARITY", rbb=True,
          seed=42, robots=4, bins=180, sim_time=4000,
          width=7, depth=7, height=6, util=0.5):
    c = SimulationConfig()
    c.grid_width, c.grid_depth, c.max_stack_height = width, depth, height
    c.bin_num, c.num_robots, c.num_pickstations = bins, robots, 2
    c.simulation_time, c.random_seed = sim_time, seed
    c.request_utilization, c.enable_visualization = util, False
    c.reordering_strategy, c.placement_strategy = reordering, placement
    c.return_blocking_bins = rbb
    return SimulationEngine(c)


def run(engine, bis_t=None):
    buf = io.StringIO()
    err = None
    with contextlib.redirect_stdout(buf):
        try:
            while engine.step() is not None:
                if bis_t is not None and engine.state.t >= bis_t:
                    break
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
    return buf.getvalue(), err


if __name__ == "__main__":
    kwargs = {}
    for arg in sys.argv[1:]:
        key, _, val = arg.partition("=")
        if val in ("True", "False"):
            kwargs[key] = val == "True"
        elif val.isdigit():
            kwargs[key] = int(val)
        else:
            kwargs[key] = val

    engine = build(**kwargs)
    log, err = run(engine)
    ts = [r["t_pickstation"] for r in engine.metrics.retrievals]
    st = engine.state
    print(f"t_end={st.t} retrievals={len(ts)} letztes={ts[-1] if ts else None} "
          f"stillstand={st.t - (ts[-1] if ts else 0)} err={err}")

    zeilen = log.splitlines()
    schwanz = zeilen[-3000:]
    muster = Counter(re.sub(r"\d+", "N", z).strip() for z in schwanz)
    print("\nHaeufigste Meldungen am Ende:")
    for norm, n in muster.most_common(12):
        print(f"  {n:6d}  {norm[:140]}")

    print("\nRoboter:")
    for r in st.robots:
        t = getattr(r, "current_task", None)
        temp = getattr(t, "temp_storage", None) or []
        print(f"  robot {r.robot_id} pos={r.position} carrying={r.get_carried_bin()} "
              f"phase={getattr(t, 'phase', None)} ziel={getattr(t, 'target_bin_id', None)} "
              f"offene_blocker={len(temp)}")

    print("\nPickstations:")
    for ps in st.pickstations:
        print(f"  {ps.station_id} pos={ps.position} frei={ps.available_slots}/{ps.capacity} "
              f"robot_on_port={getattr(ps, 'robot_on_port', None)} "
              f"reserved_for={getattr(ps, 'reserved_for_robot', None)} queue={len(ps.queue)}")

    print("\nOffene Events:")
    for item in list(st.event_queue.queue)[:14]:
        ev = item[-1] if isinstance(item, tuple) else item
        p = ev.payload if isinstance(ev.payload, dict) else {}
        a = p.get("action", p) or {}
        rob = p.get("robot")
        print(f"  ev={ev.event_id} t={ev.time} {str(ev.event_type).split('.')[-1]} "
              f"retry={ev.retry_count} robot={getattr(rob, 'robot_id', None)} "
              f"type={a.get('type')} bin={a.get('bin_id')} to={a.get('to_stack')}")
