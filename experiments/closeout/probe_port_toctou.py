"""
Randfall-Pruefung des PortExitGuard vor der Kalibration.

Zwei Fragen:

1) TOCTOU: Port besetzt, eine Ausfahrt belegt, zwei frei. Zwei fremde
   Roboter planen NACHEINANDER Wege, die je eine der beiden freien
   Ausfahrten belegen wuerden. Bleibt dem Portroboter danach noch eine
   ausfuehrbare Ausfahrt?

2) Zieleausnahme: Darf ein fremder Roboter die geschuetzte LETZTE freie
   Ausfahrt belegen, nur weil diese Zelle sein eigenes Ziel ist?
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from config.simulation_config import SimulationConfig  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402


def build(robots=5, width=7, depth=7, bins=100, height=6, seed=42):
    c = SimulationConfig()
    c.grid_width, c.grid_depth, c.max_stack_height = width, depth, height
    c.bin_num, c.num_robots, c.num_pickstations = bins, robots, 2
    c.simulation_time, c.random_seed = 400, seed
    c.request_utilization, c.enable_visualization = 0.5, False
    c.enable_highway_system = False
    return SimulationEngine(c)


def exits(engine, station):
    guard = engine.state.traffic_manager.port_exit_guard
    ports = engine.state.traffic_manager.port_positions
    return [p for p in guard.get_neighbor_positions(station.position)
            if p not in ports]


def belegt(engine):
    return {r.get_position(): r.robot_id for r in engine.state.robots}


def szenario_toctou():
    engine = build()
    tm = engine.state.traffic_manager
    st = engine.state
    station = st.pickstations[0]
    aus = exits(engine, station)
    print(f"Port {station.position}, Ausfahrten {aus}")

    # Portroboter + eine belegte Ausfahrt
    station.reserve(0)
    station.robot_enters(0)
    st.robots[0].set_position(station.position)
    st.robots[1].set_position(aus[0])

    frei = aus[1:]
    print(f"belegt: {aus[0]} | frei: {frei}")

    # Zwei fremde Roboter planen nacheinander je auf eine freie Ausfahrt
    planer = [st.robots[2], st.robots[3]]
    for robot, ziel in zip(planer, frei):
        robot.set_position((4, 4) if robot.robot_id == 2 else (5, 5))
        gesperrt = tm.get_port_exit_cells_to_keep_free(robot.robot_id)
        with contextlib.redirect_stdout(io.StringIO()):
            pfad = tm.request_path(robot=robot, target=ziel,
                                   current_time=st.t)
        erlaubt = pfad is not None and pfad != [] and pfad[-1] == ziel
        print(f"  robot {robot.robot_id} -> {ziel}: gesperrt={sorted(gesperrt)} "
              f"Pfad={'JA' if erlaubt else 'NEIN'}")
        if erlaubt:
            # Ausfuehrung simulieren: Roboter steht am Ziel
            robot.set_position(ziel)

    rest = [p for p in aus if p not in belegt(engine)]
    print(f"  -> freie Ausfahrten danach: {rest}")
    return len(rest) > 0


def szenario_ziel():
    engine = build()
    tm = engine.state.traffic_manager
    st = engine.state
    station = st.pickstations[0]
    aus = exits(engine, station)

    station.reserve(0)
    station.robot_enters(0)
    st.robots[0].set_position(station.position)
    for i, pos in enumerate(aus[:-1], start=1):
        st.robots[i].set_position(pos)

    letzte = aus[-1]
    fremder = st.robots[len(aus)]
    fremder.set_position((4, 4))
    gesperrt = tm.get_port_exit_cells_to_keep_free(fremder.robot_id)
    print(f"letzte freie Ausfahrt {letzte}, gesperrt={sorted(gesperrt)}")
    with contextlib.redirect_stdout(io.StringIO()):
        pfad = tm.request_path(robot=fremder, target=letzte, current_time=st.t)
    erlaubt = pfad is not None and pfad != [] and pfad[-1] == letzte
    print(f"  fremder robot {fremder.robot_id} mit ZIEL {letzte}: "
          f"Pfad={'JA' if erlaubt else 'NEIN'}")
    return not erlaubt


if __name__ == "__main__":
    print("=== Szenario 1: TOCTOU (zwei Planer, zwei freie Ausfahrten) ===")
    ok1 = szenario_toctou()
    print(f"  ERGEBNIS: {'PASS' if ok1 else 'FAIL - Port eingeschlossen'}\n")

    print("=== Szenario 2: letzte Ausfahrt als eigenes Ziel ===")
    ok2 = szenario_ziel()
    print(f"  ERGEBNIS: {'PASS' if ok2 else 'FAIL - Ziel-Ausnahme oeffnet die Sperre'}")
