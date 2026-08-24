# tests/test_port_exit_admission.py
"""
Regression fuer Klasse C: Stau im Portbereich (2026-08-22).

Fehlerbild
----------
Ein Roboter steht auf der Portzelle einer Pickstation. Deren drei Nachbarn
sind seine einzigen Ausfahrten. Werden alle drei belegt, ist er
eingeschlossen: er kann die Station nicht raeumen, alle nachfolgenden
Roboter warten auf genau diese Zelle, und der Lauf macht keinen Fortschritt
mehr — ohne dass eine Invariante verletzt waere.

Gemessen auf der finalen Geometrie:
    ABC+ABC/Seed 42        letztes Retrieval t=2973, Roboter 1 auf (0,15)
                           mit 0 freien Nachbarn, PS_1 gleichzeitig leer
    POPULARITY/Seed 1      letztes Retrieval t=1992, Roboter 3 auf (19,15)
                           mit 0 freien Nachbarn

Ursache
-------
`PortExitGuard` existierte und war in `TrafficManager.request_path`
verdrahtet, wertete aber ausschliesslich die RESERVIERUNGSTABELLE aus. Ein
stehender Roboter (leerer Pfad, keine kuenftigen Reservierungen) taucht dort
nicht auf; `get_robot_on_port` lieferte False und die Pruefung brach sofort
ab. Zusaetzlich umging der Manhattan-Fallback in `ActionCostModel.build_path`
jede Verkehrspruefung — und griff genau dann, wenn der TrafficManager wegen
Staus scheiterte.

Loesung
-------
`TrafficManager.get_port_exit_cells_to_keep_free(robot_id)` fragt den
tatsaechlichen Zustand ab (`Pickstation.robot_on_port`, aktuelle
Roboterpositionen). Bleibt einem besetzten Port genau eine Ausfahrt, wird
diese Zelle fuer alle anderen Roboter gesperrt — in der Pfadplanung UND im
Fallback.

Die Regel folgt aus der Geometrie, nicht aus einer gewaehlten Zahl: ein Port
am Rand hat drei Nachbarn, und ein besetzter Port braucht mindestens eine
Ausfahrt.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from traffic.traffic_manager import TrafficManager


def build_engine(width=7, depth=7, robots=4, bins=120, height=6,
                 seed=42, sim_time=300, pickstations=2):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = height
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.enable_highway_system = False
    return SimulationEngine(config)


def exits_of(engine, station):
    guard = engine.state.traffic_manager.port_exit_guard
    ports = engine.state.traffic_manager.port_positions
    return [p for p in guard.get_neighbor_positions(station.position)
            if p not in ports]


def occupy(engine, robot_index, position):
    engine.state.robots[robot_index].set_position(position)


# ====================================================================== #
# 1. Engstelle wird nicht ueberfuellt
# ====================================================================== #

def test_last_exit_of_an_occupied_port_is_kept_free():
    """Die letzte freie Ausfahrt eines besetzten Ports wird gesperrt."""
    engine = build_engine(robots=4)
    tm = engine.state.traffic_manager
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)
    assert len(ausfahrten) >= 2

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    for i, pos in enumerate(ausfahrten[:-1], start=1):
        occupy(engine, i, pos)

    gesperrt = tm.get_port_exit_cells_to_keep_free(robot_id=3)
    assert ausfahrten[-1] in gesperrt, (
        "Die letzte Ausfahrt eines besetzten Ports muss fuer fremde Roboter "
        "gesperrt sein."
    )


def test_free_port_imposes_no_restriction():
    """Ohne Roboter auf dem Port wird nichts gesperrt."""
    engine = build_engine()
    tm = engine.state.traffic_manager
    for station in engine.state.pickstations:
        assert station.robot_on_port is None
    assert tm.get_port_exit_cells_to_keep_free(robot_id=0) == set()


def test_two_free_exits_impose_no_restriction():
    """Solange mehr als eine Ausfahrt frei ist, wird nicht eingeschraenkt."""
    engine = build_engine()
    tm = engine.state.traffic_manager
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    occupy(engine, 1, ausfahrten[0])

    assert tm.get_port_exit_cells_to_keep_free(robot_id=2) == set()


# ====================================================================== #
# 2./3. Portroboter bleibt erreichbar und kann wieder heraus
# ====================================================================== #

def test_port_robot_itself_is_never_locked_out_of_its_own_exit():
    """
    Der eingeschlossene Roboter darf durch die Regel nicht selbst behindert
    werden — sonst wuerde die Sperre den Stau zementieren, statt ihn zu
    verhindern.
    """
    engine = build_engine()
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    for i, pos in enumerate(ausfahrten[:-1], start=1):
        occupy(engine, i, pos)

    gesperrt = engine.state.traffic_manager.get_port_exit_cells_to_keep_free(
        robot_id=0
    )
    assert gesperrt == set(), (
        "Fuer den Roboter auf dem Port selbst darf keine Ausfahrt gesperrt sein."
    )


def test_last_exit_is_protected_even_when_it_is_the_own_target():
    """
    Die letzte Ausfahrt darf ein fremder Roboter auch dann NICHT belegen,
    wenn sie sein eigenes Ziel ist.

    Die erste Fassung nahm `target` aus der Sperre heraus, damit ein Roboter
    mit genau diesem Ziel planen kann. Damit war die Garantie wirkungslos —
    nachgewiesen im Randfalltest: der fremde Roboter bekam den Pfad und der
    Port war eingeschlossen.

    Die Ausnahme wird auch nicht gebraucht: Zellen der Port-Pufferzone sind
    keine gueltigen Storage-Positionen, also nie Ziel eines Pickups oder
    einer Ablage; Idle-Parking meidet die Zone ohnehin. Das einzige legitime
    Ziel in der Zone ist die Portzelle selbst, und die ist keine Ausfahrt.
    """
    engine = build_engine()
    tm = engine.state.traffic_manager
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    for i, pos in enumerate(ausfahrten[:-1], start=1):
        occupy(engine, i, pos)

    ziel = ausfahrten[-1]
    robot = engine.state.robots[3]
    robot.set_position((4, 4))
    with contextlib.redirect_stdout(io.StringIO()):
        pfad = tm.request_path(robot=robot, target=ziel, current_time=engine.state.t)

    assert pfad is None, (
        "Ein fremder Roboter hat die letzte Ausfahrt als eigenes Ziel belegt."
    )


def test_planned_paths_of_other_robots_count_as_claimed_exits():
    """
    Ein bereits GEPLANTER Weg auf eine Ausfahrt zaehlt wie ein Roboter, der
    dort schon steht.

    Ohne das entsteht ein Time-of-check/Time-of-use-Loch: Sind noch zwei
    Ausfahrten frei, sperrt die Regel nichts. Planen daraufhin zwei fremde
    Roboter nacheinander je eine davon an, ist der Port nach Ausfuehrung
    beider Wege eingeschlossen — obwohl jede Einzelpruefung fuer sich korrekt
    war.
    """
    engine = build_engine(robots=5)
    tm = engine.state.traffic_manager
    st = engine.state
    station = st.pickstations[0]
    ausfahrten = exits_of(engine, station)
    assert len(ausfahrten) >= 3

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    occupy(engine, 1, ausfahrten[0])          # eine Ausfahrt physisch belegt

    frei = ausfahrten[1:]
    assert len(frei) == 2

    # Erster fremder Roboter plant auf die erste freie Ausfahrt.
    planer = st.robots[2]
    planer.set_position((4, 4))
    with contextlib.redirect_stdout(io.StringIO()):
        pfad = tm.request_path(robot=planer, target=frei[0],
                               current_time=st.t)
    assert pfad, "Bei zwei freien Ausfahrten muss die erste Planung gelingen."

    # Zweiter fremder Roboter darf die verbleibende Ausfahrt nicht mehr
    # bekommen — der Weg des ersten zaehlt bereits als Anspruch.
    zweiter = st.robots[3]
    zweiter.set_position((5, 5))
    gesperrt = tm.get_port_exit_cells_to_keep_free(zweiter.robot_id)
    assert frei[1] in gesperrt, (
        "Die verbleibende Ausfahrt muss gesperrt sein, sobald die andere "
        "bereits eingeplant ist."
    )
    with contextlib.redirect_stdout(io.StringIO()):
        pfad2 = tm.request_path(robot=zweiter, target=frei[1],
                                current_time=st.t)
    assert pfad2 is None, "Der Port waere nach beiden Wegen eingeschlossen."


# ====================================================================== #
# 4./5./6. Reservation: deterministisch, freigegeben, nicht stale
# ====================================================================== #

def test_reservation_is_single_holder_and_deterministic():
    """Reservierung ist eindeutig und ohne Zufall vergeben."""
    engine = build_engine()
    station = engine.state.pickstations[0]

    assert station.reserve(3) is True
    assert station.reserve(3) is True, "Reservieren muss idempotent sein."
    assert station.reserve(5) is False, "Zweiter Roboter darf nicht reservieren."
    assert station.reserved_for_robot == 3


def test_reservation_is_released_when_the_robot_leaves():
    """`robot_leaves` gibt Anwesenheit UND Reservierung frei."""
    engine = build_engine()
    station = engine.state.pickstations[0]

    station.reserve(2)
    station.robot_enters(2)
    assert station.robot_on_port == 2

    station.robot_leaves()
    assert station.robot_on_port is None
    assert station.reserved_for_robot is None
    assert station.is_available()


def test_a_released_port_no_longer_restricts_anyone():
    """
    Nach dem Verlassen darf keine Sperre zurueckbleiben — sonst koennte eine
    stale Reservierung Roboter dauerhaft ausschliessen.
    """
    engine = build_engine()
    tm = engine.state.traffic_manager
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)

    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)
    for i, pos in enumerate(ausfahrten[:-1], start=1):
        occupy(engine, i, pos)
    assert tm.get_port_exit_cells_to_keep_free(robot_id=3)

    station.robot_leaves()
    occupy(engine, 0, (3, 3))
    assert tm.get_port_exit_cells_to_keep_free(robot_id=3) == set()


# ====================================================================== #
# 7./8. Beide Stationen bleiben nutzbar, keine Cross-Station-Semantik
# ====================================================================== #

def test_both_pickstations_stay_usable():
    """Die Regel wirkt je Station und sperrt die andere nicht mit."""
    engine = build_engine()
    tm = engine.state.traffic_manager
    ps0, ps1 = engine.state.pickstations[0], engine.state.pickstations[1]

    ausfahrten0 = exits_of(engine, ps0)
    ps0.reserve(0)
    ps0.robot_enters(0)
    occupy(engine, 0, ps0.position)
    for i, pos in enumerate(ausfahrten0[:-1], start=1):
        occupy(engine, i, pos)

    gesperrt = tm.get_port_exit_cells_to_keep_free(robot_id=3)
    for pos in exits_of(engine, ps1):
        assert pos not in gesperrt, (
            "Ein Stau an PS_0 darf PS_1 nicht mit sperren."
        )
    assert ps1.is_available()


def test_rule_does_not_reassign_stations():
    """
    Die Regel fasst die Pickstation-Zuordnung nicht an.

    Sie ist reine Verkehrsregel; welche Station ein Task benutzt, entscheidet
    weiterhin allein die bestehende Zuordnung.
    """
    engine = build_engine(sim_time=400)
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            pass

    stationen = {z["pickstation"] for z in engine.metrics.retrievals}
    assert stationen, "Kein Retrieval im Testlauf"
    assert all(s is not None for s in stationen), (
        "Jedes Retrieval muss einer Station zugeordnet bleiben."
    )


# ====================================================================== #
# 9. Kein Zufall
# ====================================================================== #

def test_rule_consumes_no_randomness():
    """
    Zwei identische Laeufe bleiben identisch, und die Regel selbst zieht
    keine Zufallszahl.
    """
    zustaende = []
    for _ in range(2):
        engine = build_engine(sim_time=300)
        with contextlib.redirect_stdout(io.StringIO()):
            while engine.step() is not None:
                pass
        zustaende.append([
            (z["t_pickstation"], z["bin_id"], z["blocking_bins"])
            for z in engine.metrics.retrievals
        ])
    assert zustaende[0] == zustaende[1]

    engine = build_engine()
    tm = engine.state.traffic_manager
    station = engine.state.pickstations[0]
    station.reserve(0)
    station.robot_enters(0)
    occupy(engine, 0, station.position)

    vorher = [rng.bit_generator.state for rng in (
        engine.rng, engine.robot_rng, engine.service_rng,
        engine.relocation_rng, engine.placement_rng)]
    for _ in range(5):
        tm.get_port_exit_cells_to_keep_free(robot_id=1)
    nachher = [rng.bit_generator.state for rng in (
        engine.rng, engine.robot_rng, engine.service_rng,
        engine.relocation_rng, engine.placement_rng)]
    assert vorher == nachher, "Die Regel hat Zufall verbraucht."


# ====================================================================== #
# 12. Synthetischer Portstau loest sich auf
# ====================================================================== #

def test_synthetic_port_jam_with_more_than_two_robots_resolves():
    """
    Mehr als zwei Roboter draengen zur selben Station — der Lauf muss
    weiterhin Fortschritt machen.

    Genau diese Konstellation blieb vorher dauerhaft stehen: der Wait-Graph
    erkennt Zweierzyklen, die beobachtete Tasche hatte aber vier bis acht
    Beteiligte.
    """
    engine = build_engine(width=9, depth=9, robots=6, bins=200, sim_time=1500)
    station = engine.state.pickstations[0]
    ausfahrten = exits_of(engine, station)

    # Roboter dicht um die Station herum aufstellen
    for i, pos in enumerate(ausfahrten):
        if i < len(engine.state.robots):
            engine.state.robots[i].set_position(pos)

    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            pass

    zeiten = [z["t_pickstation"] for z in engine.metrics.retrievals]
    assert zeiten, "Kein einziges Retrieval trotz freier Station"
    assert zeiten[-1] > 700, (
        f"Der Lauf kommt zum Erliegen: letztes Retrieval bei t={zeiten[-1]}"
    )

    for ps in engine.state.pickstations:
        frei = [p for p in exits_of(engine, ps)
                if p not in {r.get_position() for r in engine.state.robots}]
        if ps.robot_on_port is not None:
            assert frei, (
                f"{ps.station_id} ist am Ende vollstaendig eingeschlossen."
            )
