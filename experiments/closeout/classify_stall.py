"""
Klassifiziert einen festgefahrenen Lauf: WER wartet auf WAS, und WER hat es
unzugaenglich gemacht?

Arbeitet auf einem Pickle aus `pilot_slice.py`. Gibt je wartendem Task aus:
Taskphase, gewuenschte Bin, deren Stack/Level, welche Bins darueber liegen,
zu welchem fremden Task diese gehoeren, Ownership, temp_storage,
Retry-Zaehler und die daraus abgeleitete Wait-Kante.
"""
import sys
from collections import defaultdict

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')
sys.setrecursionlimit(200000)

from pilot_state import load_engine  # noqa: E402


def stack_of(state, bin_id):
    for s in state.grid.all_stacks():
        for lvl, b in enumerate(s.bins):
            if b.bin_id == bin_id:
                return s, lvl
    return None, None


def task_of_robot(robot):
    return getattr(robot, "current_task", None)


def open_blockers(task):
    """Offene Relocation-Verpflichtungen des Tasks: bin_id -> Pufferstack."""
    temp = getattr(task, "temp_storage", None) or []
    out = {}
    for entry in temp:
        if isinstance(entry, dict):
            out[entry.get("bin_id")] = entry.get("buffer_stack")
    return out


def analyse(path):
    engine = load_engine(path)
    state = engine.state
    aq = engine.active_queue

    ownership = dict(getattr(aq, "_blocker_ownership", {}))
    reserved = set(aq.get_all_reserved_bin_ids())

    # bin_id -> (robot_id, task) des Eigentuemers
    owner_robot = {}
    for r in state.robots:
        t = task_of_robot(r)
        if t is None:
            continue
        for bin_id in open_blockers(t):
            owner_robot[bin_id] = (r.robot_id, t)

    print(f"### {path}")
    print(f"t={state.t}  retrievals={len(engine.metrics.retrievals)}  "
          f"letztes Retrieval t="
          f"{engine.metrics.retrievals[-1]['t_pickstation'] if engine.metrics.retrievals else None}")
    cfg = engine.config
    print(f"Policy: reordering={cfg.reordering_strategy} "
          f"placement={cfg.placement_strategy} "
          f"return_blocking_bins={cfg.return_blocking_bins}")
    print(f"reservierte Bins={len(reserved)}  blocker_ownership={len(ownership)}")

    print("\nEvent-Queue (mit Aktion und Zielzustand):")
    for item in sorted(list(state.event_queue.queue),
                       key=lambda i: -getattr(i[-1] if isinstance(i, tuple) else i,
                                              "retry_count", 0)):
        ev = item[-1] if isinstance(item, tuple) else item
        p = ev.payload if isinstance(ev.payload, dict) else {}
        action = p.get("action", p) or {}
        robot = p.get("robot")
        robot_id = getattr(robot, "robot_id", p.get("robot_id"))
        info = []
        for key in ("type", "return_kind", "bin_id", "from_stack", "to_stack",
                    "target", "position"):
            if key in action:
                info.append(f"{key}={action[key]}")
        ziel = action.get("to_stack") or action.get("from_stack")
        if isinstance(ziel, str) and ziel.startswith("S_"):
            x, y = int(ziel.split("_")[1]), int(ziel.split("_")[2])
            s = state.grid.get_stack(x, y)
            if s is not None:
                info.append(f"[{ziel} hoehe={s.height()}/{cfg.max_stack_height}]")
        print(f"  ev={ev.event_id} t={ev.time} {str(ev.event_type).split('.')[-1]} "
              f"retry={ev.retry_count} robot={robot_id} " + " ".join(info))

    wait_edges = []
    print("\nWartende Tasks:")
    for r in state.robots:
        t = task_of_robot(r)
        if t is None:
            print(f"  robot {r.robot_id}: kein Task")
            continue
        blockers = open_blockers(t)
        print(f"  robot {r.robot_id}: phase={t.phase} "
              f"target_bin={t.target_bin_id} target_stack={t.target_stack_id} "
              f"target_at_pickstation={getattr(t, 'target_at_pickstation', None)} "
              f"pickstation_completed={getattr(t, 'pickstation_completed', None)} "
              f"offene_blocker={len(blockers)}")
        for bin_id, buffer_stack in blockers.items():
            s, lvl = stack_of(state, bin_id)
            if s is None:
                print(f"      blocker {bin_id}: nicht im Grid (in transit?) "
                      f"soll nach {buffer_stack}")
                continue
            oben = s.height() - 1 - lvl
            darueber = [b.bin_id for b in s.bins[lvl + 1:]]
            fremde = []
            for other in darueber:
                if other in owner_robot and owner_robot[other][0] != r.robot_id:
                    fremde.append((other, owner_robot[other][0]))
                elif other in reserved:
                    fremde.append((other, "reserviert/anderer Task"))
                else:
                    fremde.append((other, "frei"))
            zugaenglich = "JA" if oben == 0 else "NEIN"
            print(f"      blocker {bin_id} liegt {s.stack_id} L{lvl}/{s.height()} "
                  f"obenauf={zugaenglich} darueber={fremde} "
                  f"owner={'self' if ownership.get(bin_id) is t else ownership.get(bin_id) is not None}")
            for other, who in fremde:
                if isinstance(who, int):
                    wait_edges.append((r.robot_id, who, bin_id, other, s.stack_id))

    print("\nWait-Kanten (Roboter A wartet auf Roboter B):")
    for a, b, mine, theirs, stack in wait_edges:
        print(f"  robot {a} -> robot {b}   (eigene Bin {mine} unter fremder Bin "
              f"{theirs} auf {stack})")

    # Zyklen suchen
    adj = defaultdict(set)
    for a, b, *_ in wait_edges:
        adj[a].add(b)
    zyklen = []

    def dfs(start, node, pfad, gesehen):
        for nxt in adj[node]:
            if nxt == start and len(pfad) >= 2:
                zyklen.append(list(pfad))
            elif nxt not in gesehen:
                dfs(start, nxt, pfad + [nxt], gesehen | {nxt})

    for node in list(adj):
        dfs(node, node, [node], {node})
    kurz = {tuple(sorted(z)) for z in zyklen}
    print(f"\nZyklen gefunden: {len(kurz)}")
    for z in sorted(kurz):
        print("  Zyklus zwischen Robotern", z)

    print("\nStackhoehen:")
    heights = [s.height() for s in state.grid.all_stacks()]
    print(f"  stacks={len(heights)} voll={sum(1 for h in heights if h >= cfg.max_stack_height)} "
          f"freie_slots={sum(cfg.max_stack_height - h for h in heights)}")
    print()


if __name__ == "__main__":
    for path in sys.argv[1:]:
        analyse(path)
