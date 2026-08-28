"""
Welche Aktion verschuettet die Blocker-Bins?

Protokolliert jede Ablage (relocate / return blocker / return target) mit
Zielstack und ordnet am Ende jeder verschuetteten Blocker-Bin zu, WELCHE
Aktion die daraufliegenden Bins dorthin gebracht hat.
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, str(__file__).rsplit("/", 1)[0])

from simulation.event_handler import EventHandler  # noqa: E402
from state.storage_stack import StorageStack  # noqa: E402
from diagnose_small_stall import build, run  # noqa: E402

ablagen = {}       # bin_id -> (t, art, stack)
_aktuell = {"action": None, "robot": None, "t": None}


def install(engine):
    """Jede Ablage auf einem Stack der ausloesenden Drop-Aktion zuordnen."""
    orig_drop = EventHandler._handle_robot_drop
    orig_push = StorageStack.push

    def drop(self, event):
        p = event.payload if isinstance(event.payload, dict) else {}
        action = p.get("action") or {}
        robot = p.get("robot")
        _aktuell.update(action=action, robot=getattr(robot, "robot_id", None),
                        t=self.state.t)
        try:
            return orig_drop(self, event)
        finally:
            _aktuell.update(action=None, robot=None, t=None)

    def push(self, bin_obj):
        action = _aktuell["action"] or {}
        art = action.get("type")
        if art == "return":
            art = f"return/{action.get('return_kind')}"
        ablagen[getattr(bin_obj, "bin_id", None)] = (
            _aktuell["t"], art or "unbekannt", self.stack_id, _aktuell["robot"])
        return orig_push(self, bin_obj)

    EventHandler._handle_robot_drop = drop
    StorageStack.push = push
    return orig_drop, orig_push


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
    orig_drop, orig_push = install(engine)
    log, err = run(engine)
    from simulation.event_handler import EventHandler as _EH; _EH._handle_robot_drop = orig_drop
    from state.storage_stack import StorageStack as _SS; _SS.push = orig_push

    st = engine.state
    ts = [r["t_pickstation"] for r in engine.metrics.retrievals]
    print(f"t_end={st.t} retrievals={len(ts)} letztes={ts[-1] if ts else None} err={err}")

    def stack_of(bin_id):
        for s in st.grid.all_stacks():
            for lvl, b in enumerate(s.bins):
                if b.bin_id == bin_id:
                    return s, lvl
        return None, None

    print("\nVerschuettete Blocker je Task:")
    for r in st.robots:
        t = getattr(r, "current_task", None)
        if t is None:
            continue
        for eintrag in (getattr(t, "temp_storage", None) or []):
            if not isinstance(eintrag, dict):
                continue
            bin_id = eintrag.get("bin_id")
            s, lvl = stack_of(bin_id)
            if s is None or lvl == s.height() - 1:
                continue
            print(f"  robot {r.robot_id} braucht Blocker {bin_id} auf {s.stack_id} "
                  f"L{lvl}/{s.height()}  (abgelegt: {ablagen.get(bin_id)})")
            for b in s.bins[lvl + 1:]:
                print(f"      darueber liegt {b.bin_id:5d}  abgelegt durch "
                      f"{ablagen.get(b.bin_id)}")
