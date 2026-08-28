# tests/test_reproducibility_crn.py
"""
Reproduzierbarkeit und Common Random Numbers (Phase 4).

Ziel: Die vier Policies sollen später unter fairen Zufallsbedingungen
verglichen werden. Dafür müssen zwei Dinge gelten.

1. **Policyintern reproduzierbar** – gleicher Master-Seed, gleicher Lauf.
2. **Policyübergreifend gekoppelt** – die *exogenen* Zufallsgrößen sind bei
   gleichem Master-Seed für alle Policies identisch, auch wenn die Policies
   unterschiedlich viele eigene Zufallsentscheidungen treffen.

Exogen (darf nicht von der Policy abhängen):
    Initialverteilung, Roboter-Startpositionen, ABC-Klassen,
    Request-Strom (Ankunft, Target-Bin, Zeitfenster),
    Pickstation-Bearbeitungszeit je Request.

Endogen (gehört zur Policy):
    RR+RR-Relocation, RANDOM-Placement, ABC-/Popularity-Tie-Breaks,
    Popularity-Warmup.

Gemessener Ausgangszustand vor Phase 4 (12x18, Seed 42, 800 ZE):
Von rund 50 Servicezeiten stimmten je nach Policy nur 15 bis 24 mit der
Referenz überein; die erste Abweichung lag bereits an Position 3 bis 5.
"""

import contextlib
import io

import pytest

from config.rng_streams import (
    ENDOGENOUS_STREAMS,
    EXOGENOUS_STREAMS,
    STREAM_NAMES,
    RngStreams,
)
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from requests_.request import Request
from events.event_types import EventType


POLICIES = {
    "A_RR+RR":   ("LOFI", "RANDOM", False),
    "B_LR+NR":   ("LOFI", "NEAREST", False),
    "C_ABC+ABC": ("ABC", "ABC", True),
    "D_POP+POP": ("POPULARITY", "POPULARITY", True),
}


def build_engine(policy, seed=42, width=12, depth=18, bins=1150,
                 robots=5, sim_time=400, pickstations=2, util=0.6):
    reordering, placement, return_blocking_bins = POLICIES[policy]
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 8
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = 1.5
    config.reordering_strategy = reordering
    config.placement_strategy = placement
    config.return_blocking_bins = return_blocking_bins
    return SimulationEngine(config)


def run_engine(engine):
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            return exc
    return None


# ---------------------------------------------------------------- #
# Fingerabdrücke der exogenen Größen
# ---------------------------------------------------------------- #

def initial_layout(engine):
    return tuple(sorted(
        (s.stack_id, tuple(b.bin_id for b in s.bins))
        for s in engine.state.grid.all_stacks()
    ))


def robot_start_positions(engine):
    return tuple(r.get_position() for r in engine.state.robots)


def abc_classes(engine):
    return tuple(sorted((b.bin_id, b.get_abc_class()) for b in engine.state.bins))


def request_stream(engine):
    return tuple(sorted(
        (r.arrival_time, r.request_id, r.target_box_id,
         r.earliest_time, r.latest_time)
        for _, r in engine.state.future_request_queue.queue
    ))


def service_times(engine):
    """Die exogene Bearbeitungszeit je Request, geschlüsselt nach request_id."""
    return tuple(sorted(
        (r.request_id, r.service_time)
        for _, r in engine.state.future_request_queue.queue
    ))


def exogenous_fingerprint(engine):
    return (
        initial_layout(engine),
        robot_start_positions(engine),
        abc_classes(engine),
        request_stream(engine),
        service_times(engine),
    )


def full_fingerprint(engine):
    """Kompletter Endzustand nach einem Lauf."""
    return (
        engine.metrics.summary().get("requests_completed"),
        initial_layout(engine),
        tuple(sorted(
            (s.stack_id, tuple(b.bin_id for b in s.bins))
            for s in engine.state.grid.all_stacks())),
        tuple(sorted((b.bin_id, b.get_access_count())
                     for b in engine.state.bins)),
    )


# ======================================================================
# 1. Die Stream-Struktur selbst
# ======================================================================

def test_streams_are_independent_and_seed_derived():
    """Jeder Strom ist eigenständig und hängt am Master-Seed."""
    a = RngStreams(42)
    b = RngStreams(42)
    c = RngStreams(43)

    for name in STREAM_NAMES:
        assert a.get(name) is not a.get("initialization") or name == "initialization"
        assert list(a.get(name).integers(0, 10_000, size=5)) == \
            list(b.get(name).integers(0, 10_000, size=5)), (
                f"Strom {name} ist bei gleichem Seed nicht reproduzierbar"
            )

    for name in STREAM_NAMES:
        assert list(RngStreams(42).get(name).integers(0, 10_000, size=5)) != \
            list(c.get(name).integers(0, 10_000, size=5)), (
                f"Strom {name} ignoriert den Seed"
            )


def test_streams_do_not_overlap():
    """Zwei verschiedene Ströme liefern nicht dieselbe Folge."""
    streams = RngStreams(42)
    folgen = {
        name: tuple(streams.get(name).integers(0, 10 ** 9, size=20))
        for name in STREAM_NAMES
    }
    assert len(set(folgen.values())) == len(STREAM_NAMES), (
        "Mindestens zwei Ströme liefern identische Folgen – dann wären sie "
        "nicht unabhängig."
    )


def test_unknown_stream_name_is_rejected():
    """Ein Tippfehler darf nicht still einen unkoordinierten Strom erzeugen."""
    with pytest.raises(KeyError):
        RngStreams(42).get("placment")


def test_exogenous_and_endogenous_streams_are_disjoint():
    """Die Klassifikation ist vollständig und überschneidungsfrei."""
    assert set(EXOGENOUS_STREAMS) | set(ENDOGENOUS_STREAMS) == set(STREAM_NAMES)
    assert not set(EXOGENOUS_STREAMS) & set(ENDOGENOUS_STREAMS)


def test_engine_wires_each_consumer_to_its_own_stream():
    """
    Kein Verbraucher teilt sich einen Generator mit einer fachlich
    unabhängigen Größe.
    """
    engine = build_engine("A_RR+RR")
    strategy = engine.scheduler.strategy

    assert engine.cost_model.rng is engine.service_rng
    assert strategy._placement_selector.rng is engine.placement_rng
    assert strategy._relocation_selector.rng is engine.relocation_rng

    verbraucher = [
        engine.cost_model.rng,
        strategy._placement_selector.rng,
        strategy._relocation_selector.rng,
        engine.rng,  # Initialisierung
    ]
    assert len({id(r) for r in verbraucher}) == 4, (
        "Zwei Verbraucher teilen sich denselben Generator."
    )


# ======================================================================
# 2. Gleiche Seeds -> gleiche exogene Inputs
# ======================================================================

@pytest.mark.parametrize("policy", list(POLICIES))
def test_same_seed_gives_identical_exogenous_inputs(policy):
    fingerprints = [
        exogenous_fingerprint(build_engine(policy, seed=42)) for _ in range(3)
    ]
    assert len(set(fingerprints)) == 1


def test_different_seeds_give_different_exogenous_inputs():
    a = build_engine("A_RR+RR", seed=42)
    b = build_engine("A_RR+RR", seed=43)

    assert exogenous_fingerprint(a) != exogenous_fingerprint(b)

    # Und zwar in jeder zufallsabhängigen Komponente einzeln.
    for links, rechts, name in (
            (initial_layout(a), initial_layout(b), "Initiallayout"),
            (robot_start_positions(a), robot_start_positions(b), "Roboterpositionen"),
            (request_stream(a), request_stream(b), "Request-Strom"),
            (service_times(a), service_times(b), "Servicezeiten")):
        assert links != rechts, f"{name} hängt nicht vom Seed ab"


def test_abc_classes_are_deterministic_and_seed_independent():
    """
    ABC-Klassen sind KEINE Zufallsgröße.

    `assign_abc_classes` leitet sie allein aus `bin_id` und den Schwellen ab.
    Sie sind deshalb für jeden Seed und jede Policy identisch – das ist
    beabsichtigt und gehört zur Vergleichbarkeit, nicht zum Zufall.
    """
    klassen = {
        (policy, seed): abc_classes(build_engine(policy, seed=seed))
        for policy in ("A_RR+RR", "C_ABC+ABC")
        for seed in (42, 43)
    }
    assert len(set(klassen.values())) == 1


# ======================================================================
# 3. Der Kern: exogene Größen sind policyübergreifend identisch
# ======================================================================

def test_initial_state_is_identical_across_policies():
    layouts = {p: initial_layout(build_engine(p)) for p in POLICIES}
    robots = {p: robot_start_positions(build_engine(p)) for p in POLICIES}
    klassen = {p: abc_classes(build_engine(p)) for p in POLICIES}

    assert len(set(layouts.values())) == 1
    assert len(set(robots.values())) == 1
    assert len(set(klassen.values())) == 1


def test_request_stream_is_identical_across_policies():
    ströme = {p: request_stream(build_engine(p)) for p in POLICIES}
    assert len(set(ströme.values())) == 1
    assert len(next(iter(ströme.values()))) > 50, "Zu wenig Requests zum Prüfen"


def test_service_time_realisations_are_identical_across_policies():
    """
    Der zentrale Common-Random-Numbers-Nachweis.

    Jeder Request bekommt in jeder Policy dieselbe Bearbeitungszeit – obwohl
    die Policies unterschiedlich viele Relocations und Placements ausführen
    und die Servicejobs in anderer Reihenfolge starten.
    """
    zeiten = {p: service_times(build_engine(p)) for p in POLICIES}
    assert len(set(zeiten.values())) == 1, (
        "Die Servicezeit-Realisierungen unterscheiden sich zwischen den "
        "Policies – Common Random Numbers greift nicht."
    )
    werte = [v for _, v in next(iter(zeiten.values()))]
    assert all(v is not None for v in werte), "Nicht alle Requests vorbelegt"
    assert len(set(werte)) > 1, "Servicezeiten sind konstant – kein Zufall"


def test_service_times_survive_a_full_run_across_policies():
    """
    Auch NACH vollständigen Läufen mit unterschiedlichem Verlauf bleibt die
    Zuordnung Request -> Servicezeit identisch.
    """
    ergebnisse = {}
    for policy in POLICIES:
        engine = build_engine(policy, sim_time=400)
        vorher = dict(service_times(engine))
        run_engine(engine)
        ergebnisse[policy] = tuple(sorted(vorher.items()))

    assert len(set(ergebnisse.values())) == 1


# ======================================================================
# 4. Endogene Ziehungen verschieben keine exogene Größe
# ======================================================================

def test_extra_relocation_draws_do_not_shift_service_times():
    """
    RR+RR zieht zusätzlich aus dem Relocation-Strom. Das darf die
    Servicezeiten nicht verändern.
    """
    referenz = service_times(build_engine("C_ABC+ABC"))

    engine = build_engine("A_RR+RR")
    for _ in range(1000):  # kräftig aus dem Relocation-Strom ziehen
        engine.relocation_rng.integers(0, 1000)

    assert service_times(engine) == referenz


def test_extra_placement_draws_do_not_shift_the_request_stream():
    referenz = request_stream(build_engine("C_ABC+ABC"))

    engine = build_engine("D_POP+POP")
    for _ in range(1000):
        engine.placement_rng.integers(0, 1000)

    assert request_stream(engine) == referenz
    assert service_times(engine) == service_times(build_engine("C_ABC+ABC"))


def test_tiebreak_draws_do_not_touch_exogenous_streams():
    """
    ABC- und Popularity-Tie-Breaks ziehen aus dem Placement-Strom. Ein
    Fingerabdruck der exogenen Größen muss davon unberührt bleiben.
    """
    engine = build_engine("C_ABC+ABC")
    vorher = exogenous_fingerprint(engine)

    selector = engine.scheduler.strategy._placement_selector
    for _ in range(200):
        selector.rng.integers(0, 100)

    assert exogenous_fingerprint(engine) == vorher


def test_endogenous_streams_differ_between_policies_by_design():
    """
    Gegenprobe: Die Strategie-Entscheidungen SOLLEN sich unterscheiden. Wäre
    auch der Endzustand über alle Policies gleich, würde der Test oben nichts
    beweisen.
    """
    ergebnisse = {}
    for policy in POLICIES:
        engine = build_engine(policy, sim_time=400)
        run_engine(engine)
        ergebnisse[policy] = full_fingerprint(engine)

    assert len(set(ergebnisse.values())) > 1, (
        "Alle Policies liefern denselben Endzustand – dann ist der "
        "CRN-Nachweis wertlos."
    )


# ======================================================================
# 5. Policyinterne Reproduzierbarkeit über den ganzen Lauf
# ======================================================================

@pytest.mark.parametrize("policy", list(POLICIES))
def test_full_run_is_reproducible_for_a_fixed_seed(policy):
    fingerprints = []
    for _ in range(3):
        engine = build_engine(policy, sim_time=400)
        run_engine(engine)
        fingerprints.append(full_fingerprint(engine))

    assert len(set(fingerprints)) == 1, (
        f"{policy} ist bei festem Seed nicht reproduzierbar"
    )


# ======================================================================
# 6. Batching zerstört die Kopplung nicht
# ======================================================================

def _request(request_id, bin_id, service_time):
    request = Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=100,
    )
    request.service_time = service_time
    return request


def test_batched_service_duration_is_the_sum_of_the_request_times():
    """
    Deterministisches Beispiel für die gewählte Batching-Semantik.

    Drei Requests auf dieselbe Bin mit den Bearbeitungszeiten 4, 6 und 5.

        Policy A batcht alle drei gemeinsam    -> ein Job  mit 15
        Policy B bedient 1 allein, dann 2+3    -> Jobs mit 4 und 11
        Policy C bedient jeden einzeln         -> Jobs mit 4, 6 und 5

    In allen drei Fällen ist die Summe über alle Jobs 15. Der Beitrag jedes
    einzelnen Requests bleibt unverändert – unabhängig davon, wie gebatcht
    wird. Genau das macht die Realisierung policyunabhängig.
    """
    engine = build_engine("A_RR+RR", sim_time=50)
    builder = engine.event_builder

    r1, r2, r3 = _request(1, 7, 4), _request(2, 7, 6), _request(3, 7, 5)

    zusammen = builder.calculate_pickstation_service_duration(
        batch_count=3, requests=[r1, r2, r3])
    einzeln = builder.calculate_pickstation_service_duration(
        batch_count=1, requests=[r1])
    rest = builder.calculate_pickstation_service_duration(
        batch_count=2, requests=[r2, r3])

    assert zusammen == 15
    assert einzeln == 4
    assert rest == 11
    assert einzeln + rest == zusammen

    # Reihenfolge innerhalb des Batches ist ohne Bedeutung.
    assert builder.calculate_pickstation_service_duration(
        batch_count=3, requests=[r3, r1, r2]) == 15


def test_service_duration_falls_back_when_a_request_has_no_pre_drawn_time():
    """
    Handgebaute Requests ohne vorgezogene Zeit (z.B. in Tests) laufen weiter
    über den alten Laufzeitpfad, statt zu scheitern.
    """
    engine = build_engine("A_RR+RR", sim_time=50)
    builder = engine.event_builder

    ohne = Request(
        request_id=99, event_type=EventType.ARRIVAL, bin_id=1,
        t_arrival=0, t_earliest=0, t_latest=10,
    )
    assert ohne.service_time is None

    dauer = builder.calculate_pickstation_service_duration(
        batch_count=1, requests=[ohne])
    minimum = engine.config.pickstation_service_time_min
    maximum = engine.config.pickstation_service_time_max
    assert minimum <= dauer <= maximum


def test_every_generated_request_carries_a_service_time():
    """Im echten Lauf ist der Fallback nie nötig."""
    engine = build_engine("D_POP+POP")
    requests = [r for _, r in engine.state.future_request_queue.queue]

    assert requests, "Kein Request erzeugt"
    minimum = engine.config.pickstation_service_time_min
    maximum = engine.config.pickstation_service_time_max
    for request in requests:
        assert request.service_time is not None
        assert minimum <= request.service_time <= maximum


# ======================================================================
# 7. Kein globaler Zufallszustand mehr im Request-Strom
# ======================================================================

def test_request_stream_is_independent_of_the_global_random_state():
    """
    Vor Phase 4 setzte `RequestGenerator` `np.random.seed()` und
    `random.seed()` global. Ein anderer Verbraucher im selben Prozess konnte
    den Request-Strom dadurch verschieben.
    """
    import random as py_random

    import numpy as np

    referenz = request_stream(build_engine("A_RR+RR"))

    np.random.seed(12345)
    py_random.seed(999)
    for _ in range(500):
        np.random.random()
        py_random.random()

    assert request_stream(build_engine("A_RR+RR")) == referenz
