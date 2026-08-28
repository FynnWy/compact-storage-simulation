"""
Zweite Stall-Klasse: Roboter kommen nicht mehr an ihre Target-Bin an der
Pickstation. Dieses Skript zeigt Roboterposition, getragene Bin,
Pickstation-Belegung und den Zustand der gesuchten Bins.
"""
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')
sys.setrecursionlimit(200000)

from pilot_state import load_engine  # noqa: E402

e = load_engine(sys.argv[1])
st = e.state

print(f"### {sys.argv[1]}   t={st.t}")

print("\nRoboter:")
for r in st.robots:
    t = getattr(r, "current_task", None)
    print(f"  robot {r.robot_id} pos={r.position} "
          f"carrying={getattr(r, 'carried_bin', getattr(r, 'carried_bin_id', None))} "
          f"phase={getattr(t, 'phase', None)} "
          f"target_bin={getattr(t, 'target_bin_id', None)} "
          f"station={getattr(t, 'assigned_pickstation', None)}")

print("\nPickstations:")
for ps in st.pickstations:
    fields = {}
    for name in dir(ps):
        if name.startswith("_"):
            continue
        try:
            val = getattr(ps, name)
        except Exception:
            continue
        if callable(val):
            continue
        fields[name] = val
    print(f"  {fields}")

print("\nZustand der gesuchten Target-Bins:")
for r in st.robots:
    t = getattr(r, "current_task", None)
    if t is None or getattr(t, "target_bin_id", None) is None:
        continue
    b = st.get_bin_by_id(t.target_bin_id)
    if b is None:
        continue
    print(f"  bin {b.bin_id}: status={b.get_status()} stack={b.get_stack()} "
          f"level={b.get_level()} in_transit={getattr(b, 'in_transit', None)} "
          f"(robot {r.robot_id}, phase={t.phase})")

print("\nDoppelte Events je (robot, bin, typ):")
zaehler = {}
for item in list(st.event_queue.queue):
    ev = item[-1] if isinstance(item, tuple) else item
    p = ev.payload if isinstance(ev.payload, dict) else {}
    action = p.get("action", p) or {}
    robot = p.get("robot")
    key = (getattr(robot, "robot_id", None), action.get("bin_id"),
           str(ev.event_type).split(".")[-1], action.get("type"))
    zaehler.setdefault(key, []).append((ev.event_id, ev.retry_count))
for key, evs in sorted(zaehler.items(), key=lambda kv: -len(kv[1])):
    if len(evs) > 1:
        print(f"  {key}: {len(evs)} Events {evs}")
