"""
Vollstaendige Zustandsaufnahme eines Klasse-C-Stillstands (Portstau).

Erfasst genau die Groessen, die fuer die Bewertung „Traffic-/Admission-
Liveness-Problem" gebraucht werden: wer steht wo, wer wartet auf wen, wie
voll ist die Engstelle um jede Pickstation, und welche Zellen waeren frei.
"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, str(__file__).rsplit("/", 1)[0])
sys.setrecursionlimit(200000)

from utils.port_buffer_zone import calculate_buffer_zone  # noqa: E402
from pilot_state import load_engine  # noqa: E402


def nachbarn(pos, breite, tiefe):
    x, y = pos
    return [(nx, ny) for nx, ny in
            ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if 0 <= nx < breite and 0 <= ny < tiefe]


def analyse(path):
    engine = load_engine(path)
    st = engine.state
    cfg = engine.config
    breite, tiefe = cfg.grid_width, cfg.grid_depth

    letztes = (engine.metrics.retrievals[-1]["t_pickstation"]
               if engine.metrics.retrievals else None)
    print(f"### {path}")
    print(f"Policy: {cfg.reordering_strategy}/{cfg.placement_strategy}/"
          f"rbb={cfg.return_blocking_bins}  Seed={cfg.random_seed}")
    print(f"t={st.t}  Retrievals={len(engine.metrics.retrievals)}  "
          f"letztes Retrieval t={letztes}  Stillstand={st.t - (letztes or 0)} ZE")

    belegt = {r.position: r.robot_id for r in st.robots}

    print("\n--- Roboter ---")
    for r in st.robots:
        t = getattr(r, "current_task", None)
        pfad = getattr(r, "planned_path", []) or []
        idx = getattr(r, "path_index", 0)
        rest = pfad[idx:idx + 4]
        naechster = pfad[idx] if idx < len(pfad) else None
        blocker = belegt.get(naechster) if naechster else None
        frei = [n for n in nachbarn(r.position, breite, tiefe) if n not in belegt]
        print(f"  robot {r.robot_id} pos={r.position} traegt={r.get_carried_bin()} "
              f"phase={getattr(t, 'phase', None)} "
              f"station={getattr(t, 'assigned_pickstation', None)} "
              f"next={naechster} blockiert_von={blocker} "
              f"pfadrest={rest} freie_nachbarn={len(frei)}{frei if len(frei) <= 2 else ''}")

    print("\n--- Pickstations ---")
    ports = [ps.position for ps in st.pickstations]
    for ps in st.pickstations:
        zone = calculate_buffer_zone([ps.position], breite, tiefe)
        drin = [r.robot_id for r in st.robots if r.position in zone]
        print(f"  {ps.station_id} pos={ps.position} "
              f"reserved_for={ps.reserved_for_robot} robot_on_port={ps.robot_on_port} "
              f"slots={ps.available_slots}/{ps.capacity} queue={len(ps.queue)} "
              f"current_tasks={len(ps.current_tasks)}")
        print(f"      Zone {sorted(zone)}")
        print(f"      Roboter IN der Zone: {drin}  ({len(drin)} von {len(zone)} Zellen)")
        print(f"      bins_processed={ps.total_bins_processed} "
              f"tasks={ps.total_tasks_processed} "
              f"service_time={ps.total_service_time} wait_time={ps.total_wait_time}")

    print("\n--- Zuordnung der laufenden Tasks ---")
    zuordnung = Counter()
    for r in st.robots:
        t = getattr(r, "current_task", None)
        if t is not None:
            zuordnung[getattr(t, "assigned_pickstation", None)] += 1
    print(f"  {dict(zuordnung)}")

    print("\n--- Wait-Graph (Bewegung) ---")
    detector = getattr(st.traffic_manager, "deadlock_detector", None)
    if detector is None:
        detector = getattr(engine.event_handler, "deadlock_detector", None)
    graph = getattr(detector, "_wait_graph", None) if detector else None
    if graph:
        for rid, info in graph.items():
            print(f"  robot {rid} -> {info}")
    else:
        print("  leer")

    print("\n--- Wer blockiert wen (aus naechstem Wegpunkt) ---")
    kanten = []
    for r in st.robots:
        pfad = getattr(r, "planned_path", []) or []
        idx = getattr(r, "path_index", 0)
        if idx < len(pfad):
            ziel = pfad[idx]
            if ziel in belegt and belegt[ziel] != r.robot_id:
                kanten.append((r.robot_id, belegt[ziel], ziel))
    for a, b, zelle in kanten:
        print(f"  robot {a} -> robot {b}  (Zelle {zelle})")
    adj = defaultdict(set)
    for a, b, _ in kanten:
        adj[a].add(b)
    zyklen = set()

    def dfs(start, node, gesehen):
        for nxt in adj[node]:
            if nxt == start and len(gesehen) >= 2:
                zyklen.add(tuple(sorted(gesehen)))
            elif nxt not in gesehen:
                dfs(start, nxt, gesehen | {nxt})

    for node in list(adj):
        dfs(node, node, {node})
    print(f"  Zyklen: {sorted(zyklen) if zyklen else 'keine'}")

    print("\n--- Engstelle ---")
    alle_zonen = calculate_buffer_zone(ports, breite, tiefe)
    in_zonen = [r.robot_id for r in st.robots if r.position in alle_zonen]
    print(f"  Roboter in einer Portzone: {in_zonen} ({len(in_zonen)} von "
          f"{len(st.robots)})")
    print(f"  Zellen in Portzonen gesamt: {len(alle_zonen)}")
    print()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        analyse(p)
