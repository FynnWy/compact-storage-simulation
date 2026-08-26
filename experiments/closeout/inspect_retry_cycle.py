"""Was genau versuchen die festgefahrenen Roboter aufzunehmen?"""
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')
sys.setrecursionlimit(200000)

from pilot_state import load_engine  # noqa: E402

e = load_engine(sys.argv[1])
st = e.state

reserved = set(e.active_queue.get_all_reserved_bin_ids())


def where(bin_id):
    for s in st.grid.all_stacks():
        for lvl, b in enumerate(s.bins):
            if b.bin_id == bin_id:
                return s.stack_id, lvl, s.height()
    return None, None, None


print(f"t={st.t}  reservierte Bins: {len(reserved)}")
print("\nOffene Events:")
for ev in list(st.event_queue.queue):
    ev = ev[-1] if isinstance(ev, tuple) else ev
    data = getattr(ev, "data", None) or getattr(ev, "payload", None) or {}
    action = data.get("action", data) if isinstance(data, dict) else {}
    bin_id = (action or {}).get("bin_id")
    robot_id = (action or {}).get("robot_id", data.get("robot_id") if isinstance(data, dict) else None)
    sid, lvl, h = where(bin_id) if bin_id is not None else (None, None, None)
    print(f"  ev={ev.event_id} t={ev.time} type={ev.event_type} retry={ev.retry_count} "
          f"robot={robot_id} bin={bin_id} liegt_auf={sid} level={lvl}/{h} "
          f"obenauf={'JA' if (lvl is not None and lvl == h - 1) else 'NEIN'} "
          f"reserviert={'JA' if bin_id in reserved else 'NEIN'}")

print("\nZielstapel-Kapazitaet der wartenden Tasks:")
for r in st.robots:
    t = getattr(r, "current_task", None)
    if t is None or getattr(t, "target_stack_id", None) is None:
        continue
    sid = t.target_stack_id
    x, y = (int(sid.split("_")[1]), int(sid.split("_")[2])) if isinstance(sid, str) else sid
    stack = st.grid.get_stack(x, y)
    temp = getattr(t, "temp_storage", None) or {}
    print(f"  robot {r.robot_id} target_stack={sid} hoehe={stack.height()}/"
          f"{e.config.max_stack_height} frei={e.config.max_stack_height - stack.height()} "
          f"blocker_offen={len(temp)} blocker_ids={list(temp)[:6]}")
