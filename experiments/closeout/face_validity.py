"""
High-Level-Sinnhaftigkeitspruefung (Face Validity) aller fuenf Policies.

Motivation: Der invertierte Ordered Return blieb lange unentdeckt, weil jede
Einzelfunktion lokal korrekt aussah. Erst die Frage nach dem RESULTIERENDEN
Lagerzustand deckte ihn auf. Dieses Skript stellt genau diese Frage — fuer
einen vollstaendigen, menschenlesbaren Retrieval-Zyklus je Policy und
zusaetzlich aggregiert ueber einen kurzen Lauf.

Es prueft KEINE Performance. Es prueft, ob das Zusammenspiel qualitativ das
tut, was die Policy definiert.

Aufruf:
    face_validity.py trace <policy>      ein Zyklus, menschenlesbar
    face_validity.py aggregate           Aggregatpruefungen aller Policies
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from config.simulation_config import SimulationConfig  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402
from state.storage_stack import StorageStack  # noqa: E402

POLICIES = {
    "baseline_reference": ("LOFI", "RANDOM", True),
    "RR+RR": ("LOFI", "RANDOM", False),
    "LR+NR": ("LOFI", "NEAREST", False),
    "ABC+ABC": ("ABC", "ABC", True),
    "POPULARITY+POPULARITY": ("POPULARITY", "POPULARITY", True),
}


def build(policy, seed=42, sim_time=1500, width=7, depth=7, bins=150,
          height=6, robots=3):
    reordering, placement, rbb = POLICIES[policy]
    c = SimulationConfig()
    c.grid_width, c.grid_depth, c.max_stack_height = width, depth, height
    c.bin_num, c.num_robots, c.num_pickstations = bins, robots, 2
    c.simulation_time, c.random_seed = sim_time, seed
    c.request_utilization, c.enable_visualization = 0.5, False
    c.bin_request_prob_strategy, c.zipf_parameter = "zipf", 1.0
    c.reordering_strategy, c.placement_strategy = reordering, placement
    c.return_blocking_bins = rbb
    return SimulationEngine(c)


def beschrifte(engine, bin_obj):
    return (f"{bin_obj.bin_id}[{bin_obj.get_abc_class()}"
            f",n={bin_obj.get_access_count()}]")


def stapel(engine, stack_id):
    x, y = (int(v) for v in stack_id.split("_")[1:])
    stack = engine.state.grid.get_stack(x, y)
    return [beschrifte(engine, b) for b in stack.bins]


# ====================================================================== #
# Einzelzyklus mitschreiben
# ====================================================================== #

def trace_one_cycle(policy, seed=42, max_t=1500):
    """Protokolliert den ERSTEN vollstaendigen Retrieval-Zyklus."""
    engine = build(policy, seed=seed, sim_time=max_t)
    ereignisse = []
    zustand = {"task": None, "vorher": None, "stack_id": None}

    orig_push, orig_pop = StorageStack.push, StorageStack.pop

    def push(self, b):
        ereignisse.append(("PUSH", engine.state.t, self.stack_id, b.bin_id))
        return orig_push(self, b)

    def pop(self):
        b = orig_pop(self)
        ereignisse.append(("POP", engine.state.t, self.stack_id,
                           getattr(b, "bin_id", None)))
        return b

    StorageStack.push, StorageStack.pop = push, pop

    zyklus = None
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            for r in engine.state.robots:
                t = getattr(r, "current_task", None)
                if t is None or t.target_stack_id is None:
                    continue
                if zustand["task"] is None:
                    zustand["task"] = t
                    zustand["stack_id"] = t.target_stack_id
                    zustand["vorher"] = stapel(engine, t.target_stack_id)
                    zustand["ziel"] = t.target_bin_id
                    zustand["start"] = len(ereignisse)
            t = zustand["task"]
            if t is not None and t.target_returned:
                zyklus = len(ereignisse)
                break

    StorageStack.push, StorageStack.pop = orig_push, orig_pop
    if zustand["task"] is None or zyklus is None:
        return None

    task = zustand["task"]
    relevante = ereignisse[zustand["start"]:zyklus]
    return {
        "policy": policy,
        "reordering": POLICIES[policy][0],
        "placement": POLICIES[policy][1],
        "ordered_return": POLICIES[policy][2],
        "target": zustand["ziel"],
        "target_bin": engine.state.get_bin_by_id(zustand["ziel"]),
        "original_stack": zustand["stack_id"],
        "vorher": zustand["vorher"],
        "nachher": stapel(engine, zustand["stack_id"]),
        "ereignisse": relevante,
        "actual_return_stack": task.actual_return_stack_id,
        "engine": engine,
    }


def zeige_trace(t):
    if t is None:
        print("  kein vollstaendiger Zyklus im Zeitfenster")
        return
    bin_obj = t["target_bin"]
    print(f"### {t['policy']}   "
          f"({t['reordering']} / {t['placement']} / "
          f"ordered_return={t['ordered_return']})")
    print(f"  Target-Bin        : {bin_obj.bin_id} "
          f"Klasse={bin_obj.get_abc_class()} "
          f"access_count={bin_obj.get_access_count()}")
    print(f"  Originalstack     : {t['original_stack']}")
    print(f"  Stack vorher      : unten -> oben  {t['vorher']}")
    aus = [(zeit, s, b) for art, zeit, s, b in t["ereignisse"] if art == "POP"
           and s == t["original_stack"]]
    ein = [(zeit, s, b) for art, zeit, s, b in t["ereignisse"] if art == "PUSH"]
    print(f"  entnommen aus {t['original_stack']}: "
          f"{[f'{b}@t{zeit}' for zeit, s, b in aus]}")
    print(f"  abgelegt          : "
          f"{[f'{b}->{s}@t{zeit}' for zeit, s, b in ein][:10]}")
    print(f"  Target-Return auf : {t['actual_return_stack']}")
    print(f"  Stack nachher     : unten -> oben  {t['nachher']}")
    print()


# ====================================================================== #
# Aggregatpruefungen
# ====================================================================== #

def aggregate(policy, seed=42, sim_time=2500):
    engine = build(policy, seed=seed, sim_time=sim_time)
    log = io.StringIO()
    fehler = None
    with contextlib.redirect_stdout(log):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:
            fehler = f"{type(exc).__name__}: {exc}"

    tiefen = {"A": [], "B": [], "C": []}
    heiss, kalt = [], []
    for stack in engine.state.grid.all_stacks():
        hoehe = stack.height()
        for level, b in enumerate(stack.bins):
            tiefe = hoehe - 1 - level            # 0 = ganz oben
            klasse = b.get_abc_class()
            if klasse in tiefen:
                tiefen[klasse].append(tiefe)
            if b.get_access_count() >= 3:
                heiss.append(tiefe)
            elif b.get_access_count() == 0:
                kalt.append(tiefe)

    text = log.getvalue()
    gestrandet = sum(
        1 for r in engine.state.robots
        if r.current_task is not None
        and not any(
            getattr((it[-1] if isinstance(it, tuple) else it).payload
                    .get("robot"), "robot_id", None) == r.robot_id
            for it in engine.state.event_queue.queue))

    return {
        "policy": policy,
        "fehler": fehler,
        "retrievals": len(engine.metrics.retrievals),
        "letztes_retrieval": (engine.metrics.retrievals[-1]["t_pickstation"]
                              if engine.metrics.retrievals else None),
        "t_end": engine.state.t,
        "mean_depth_A": (sum(tiefen["A"]) / len(tiefen["A"])) if tiefen["A"] else None,
        "mean_depth_C": (sum(tiefen["C"]) / len(tiefen["C"])) if tiefen["C"] else None,
        "mean_depth_hot": (sum(heiss) / len(heiss)) if heiss else None,
        "mean_depth_cold": (sum(kalt) / len(kalt)) if kalt else None,
        "blockers_returned": all(z["blockers_returned"]
                                 for z in engine.metrics.retrievals) if engine.metrics.retrievals else None,
        "any_blocker_return": any(z["blockers_returned"]
                                  for z in engine.metrics.retrievals) if engine.metrics.retrievals else None,
        "gestrandete_roboter": gestrandet,
        "invalid_lifecycle": "Invalid task lifecycle" in text,
    }


def main():
    modus = sys.argv[1] if len(sys.argv) > 1 else "aggregate"
    if modus == "trace":
        policies = [sys.argv[2]] if len(sys.argv) > 2 else list(POLICIES)
        for p in policies:
            zeige_trace(trace_one_cycle(p))
        return

    print(f"{'Policy':24s} {'retr':>5s} {'stall':>6s} {'A':>6s} {'C':>6s} "
          f"{'hot':>6s} {'cold':>6s} {'OR':>5s} {'strand':>6s}")
    for p in POLICIES:
        a = aggregate(p)
        stall = (a["t_end"] - (a["letztes_retrieval"] or 0))
        def f(x):
            return f"{x:.2f}" if x is not None else "  -  "
        print(f"{p:24s} {a['retrievals']:5d} {stall:6d} {f(a['mean_depth_A']):>6s} "
              f"{f(a['mean_depth_C']):>6s} {f(a['mean_depth_hot']):>6s} "
              f"{f(a['mean_depth_cold']):>6s} "
              f"{str(a['any_blocker_return']):>5s} {a['gestrandete_roboter']:6d}"
              + (f"  FEHLER: {a['fehler']}" if a["fehler"] else "")
              + ("  LIFECYCLE!" if a["invalid_lifecycle"] else ""))


if __name__ == "__main__":
    main()
