# tests/test_scheduling_and_deadlines.py
"""
Scheduler- und Deadline-Semantik der finalen Experimentkampagne
(Freeze-Audit).

Zwei Eigenschaften sind hier experimentkritisch:

1. **Die Request-Auswahl darf die Storage-Policy-Effekte nicht überlagern.**
   Der frühere opportunistische Bypass bediente unter Backlog bevorzugt
   Requests, deren Target ohnehin obenauf lag. Gemessen (20x30, Seed 42,
   800 ZE, baseline_reference):

       mit Bypass:  39 von 47 Zuweisungen opportunistisch,
                    β = 0,73, Retrievals aus den obersten 20 % = 84 %
       ohne Bypass: β = 2,70, Retrievals aus den obersten 20 % = 33 %

   Der Bypass hätte Mellers 80/20-Behauptung (RQ3) scheinbar bestätigt.

2. **Deadlines sind eine exogene Messgröße, keine Policy.** Sie müssen bei
   gleichem Seed über alle Konfigurationen identisch sein und dürfen nicht von
   Lagerposition, ABC-Klasse oder Popularität abhängen.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from simulation.simulation_engine import SimulationEngine


POLICIES = {
    "baseline_reference": ("LOFI", "RANDOM", True),
    "RR+RR":              ("LOFI", "RANDOM", False),
    "LR+NR":              ("LOFI", "NEAREST", False),
    "ABC+ABC":            ("ABC", "ABC", True),
    "POP+POP":            ("POPULARITY", "POPULARITY", True),
}


def build_engine(policy="baseline_reference", seed=42, sim_time=300,
                 width=12, depth=18, bins=1150, robots=5, zipf=1.0,
                 slack=None, strategy="EDF"):
    reordering, placement, rbb = POLICIES[policy]
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = 8
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = 2
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = 0.6
    config.enable_visualization = False
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = zipf
    config.reordering_strategy = reordering
    config.placement_strategy = placement
    config.return_blocking_bins = rbb
    config.scheduler_strategy = strategy
    if slack is not None:
        config.deadline_slack = slack
    return SimulationEngine(config)


def run(engine):
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            return exc
    return None


def make_request(request_id, bin_id, arrival, deadline):
    return Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=arrival, t_earliest=arrival, t_latest=deadline,
    )


# ======================================================================
# 1. Scheduler: EDF ohne lageabhängigen Bypass
# ======================================================================

def test_edf_picks_the_earliest_deadline():
    engine = build_engine(sim_time=50)
    scheduler = engine.scheduler
    queue = engine.active_queue
    queue.pending.clear()

    spaet = make_request(1, 100, arrival=0, deadline=900)
    frueh = make_request(2, 200, arrival=5, deadline=100)
    mittel = make_request(3, 300, arrival=1, deadline=500)
    for request in (spaet, frueh, mittel):
        queue.pending.append(request)

    assert scheduler._select_next_request(engine.state) is frueh


def test_edf_tie_break_is_deadline_then_arrival_then_id():
    """
    Bei konstantem Slack haben alle Requests desselben Ankunftszeitpunkts
    dieselbe Deadline – der Gleichstand ist der Normalfall, nicht die
    Ausnahme.
    """
    engine = build_engine(sim_time=50)
    scheduler = engine.scheduler
    queue = engine.active_queue
    queue.pending.clear()

    # Absichtlich in "falscher" Reihenfolge eingefügt.
    spaeter_eingang = make_request(7, 100, arrival=10, deadline=200)
    kleinere_id = make_request(3, 200, arrival=5, deadline=200)
    groessere_id = make_request(9, 300, arrival=5, deadline=200)
    for request in (spaeter_eingang, groessere_id, kleinere_id):
        queue.pending.append(request)

    # Gleiche Deadline -> frühere Ankunft gewinnt; bei gleicher Ankunft
    # die kleinere request_id.
    assert scheduler._select_next_request(engine.state) is kleinere_id
    assert scheduler._select_next_request(engine.state) is groessere_id
    assert scheduler._select_next_request(engine.state) is spaeter_eingang


def test_waiting_tasks_are_served_before_new_requests():
    """
    Bereits begonnene physische Vorgänge und Rücklagerungen bleiben
    priorisiert – sonst blieben halbfertige Digs liegen.
    """
    engine = build_engine(sim_time=50)
    scheduler = engine.scheduler
    queue = engine.active_queue

    # Beide Tasks brauchen eine real existierende Target-Bin, damit die
    # Strategie überhaupt eine Aktion planen kann.
    stacks = [s for s in engine.state.grid.all_stacks() if s.height() > 0]
    fortsetzungs_bin = stacks[0].peek().bin_id
    neue_bin = stacks[1].peek().bin_id

    fortsetzung = RobotTask(
        make_request(1, fortsetzungs_bin, arrival=0, deadline=900))
    queue.add_waiting_task(fortsetzung)

    queue.pending.clear()
    dringend = make_request(2, neue_bin, arrival=0, deadline=1)
    queue.pending.append(dringend)

    with contextlib.redirect_stdout(io.StringIO()):
        ergebnis = scheduler.try_schedule(engine.state, current_time=0)

    assert ergebnis is not None
    assert ergebnis["task"] is fortsetzung, (
        "Ein neuer Request hat einen bereits begonnenen Task verdrängt."
    )
    assert dringend in queue.pending


def test_a_top_bin_request_cannot_bypass_edf():
    """
    Kernpunkt des Freeze-Audits: Ein Request, dessen Target zufällig obenauf
    liegt, darf NICHT vorgezogen werden.
    """
    engine = build_engine(sim_time=50)
    scheduler = engine.scheduler
    queue = engine.active_queue
    state = engine.state
    queue.pending.clear()

    # Bin, die tatsächlich obenauf liegt.
    stack = next(s for s in state.grid.all_stacks() if s.height() > 0)
    oben_liegend = stack.peek().bin_id

    # Eine Bin weiter unten in einem hohen Stack.
    tiefer_stack = max(state.grid.all_stacks(), key=lambda s: s.height())
    assert tiefer_stack.height() >= 2
    vergrabene = tiefer_stack.bins[0].bin_id

    bequem = make_request(1, oben_liegend, arrival=100, deadline=900)
    dringend = make_request(2, vergrabene, arrival=0, deadline=100)
    queue.pending.append(bequem)
    queue.pending.append(dringend)

    with contextlib.redirect_stdout(io.StringIO()):
        gewaehlt = scheduler._select_next_request(state)

    assert gewaehlt is dringend, (
        "Der bequem erreichbare Request wurde vorgezogen – der lageabhängige "
        "Bypass ist wieder aktiv."
    )


def test_scheduler_has_no_opportunistic_step_in_the_main_path():
    """
    Verhaltensnachweis statt Quelltextprüfung: Über einen vollständigen Lauf
    darf keine Zuweisung an `_try_schedule_opportunistic` vorbeigehen.

    Die Methode existiert weiterhin (Legacy, dokumentiert), wird aber im
    Hauptpfad nicht mehr aufgerufen.
    """
    engine = build_engine(sim_time=200)
    aufrufe = {"n": 0}
    original = engine.scheduler._try_schedule_opportunistic

    def spy(*args, **kwargs):
        aufrufe["n"] += 1
        return original(*args, **kwargs)

    engine.scheduler._try_schedule_opportunistic = spy
    run(engine)

    assert aufrufe["n"] == 0, (
        f"`_try_schedule_opportunistic` wurde {aufrufe['n']}x aufgerufen – "
        f"der lageabhängige Bypass ist wieder im Hauptpfad."
    )


# ======================================================================
# 2. Deadlines: exogen, konstant, policyneutral
# ======================================================================

def test_deadline_is_arrival_plus_constant_slack():
    engine = build_engine(sim_time=200, slack=240)
    requests = [r for _, r in engine.state.future_request_queue.queue]

    assert requests
    for request in requests:
        assert request.latest_time == request.arrival_time + 240


def test_same_seed_gives_identical_deadlines_across_policies():
    """CRN gilt auch für Deadlines."""
    deadlines = {}
    for policy in POLICIES:
        engine = build_engine(policy=policy, sim_time=200)
        deadlines[policy] = tuple(sorted(
            (r.request_id, r.arrival_time, r.latest_time)
            for _, r in engine.state.future_request_queue.queue
        ))

    assert len(set(deadlines.values())) == 1
    assert len(next(iter(deadlines.values()))) > 20


def test_deadline_does_not_depend_on_bin_position_or_class():
    """
    Die Deadline darf keine Information über Lagerposition, ABC-Klasse oder
    Popularität enthalten – sonst wäre sie ein verdeckter Storage-Look-ahead.
    """
    engine = build_engine(sim_time=300)
    state = engine.state
    klasse = {b.bin_id: b.get_abc_class() for b in state.bins}
    level = {}
    for stack in state.grid.all_stacks():
        for ebene, bin_obj in enumerate(stack.bins):
            level[bin_obj.bin_id] = ebene

    slack_je_klasse = {}
    slack_je_level = {}
    for _, request in state.future_request_queue.queue:
        slack = request.latest_time - request.arrival_time
        slack_je_klasse.setdefault(klasse.get(request.target_box_id), set()).add(slack)
        slack_je_level.setdefault(level.get(request.target_box_id), set()).add(slack)

    alle = set().union(*slack_je_klasse.values())
    assert len(alle) == 1, f"Slack variiert: {alle}"
    for werte in list(slack_je_klasse.values()) + list(slack_je_level.values()):
        assert werte == alle


def test_deadline_slack_does_not_change_physical_behaviour():
    """
    Deadlines sind eine Messüberlagerung. Bei konstantem Slack ist EDF
    äquivalent zur Ankunftsreihenfolge, der Slackwert darf die Dynamik
    deshalb nicht verändern.
    """
    ergebnisse = {}
    for slack in (60, 240):
        engine = build_engine(sim_time=300, slack=slack)
        run(engine)
        rows = engine.metrics.retrievals
        ergebnisse[slack] = (
            len(rows),
            tuple((r["request_id"], r["t_pickstation"], r["blocking_bins"])
                  for r in rows),
        )

    assert ergebnisse[60] == ergebnisse[240], (
        "Der Deadline-Slack verändert den physischen Ablauf – dann wäre er "
        "keine reine Messgröße mehr."
    )


def test_deadline_generation_consumes_no_extra_randomness():
    """
    Der konstante Slack darf den Request-Strom nicht verschieben: Ankünfte
    und Target-Bins müssen unabhängig vom Slackwert identisch bleiben.
    """
    strom = {}
    for slack in (60, 240):
        engine = build_engine(sim_time=300, slack=slack)
        strom[slack] = tuple(sorted(
            (r.request_id, r.arrival_time, r.target_box_id, r.service_time)
            for _, r in engine.state.future_request_queue.queue
        ))

    assert strom[60] == strom[240]


# ======================================================================
# 3. Tardiness
# ======================================================================

def test_on_time_request_has_zero_tardiness():
    engine = build_engine(sim_time=300, slack=100_000)
    run(engine)

    bewertet = [r for r in engine.metrics.completed_requests if "tardiness" in r]
    assert bewertet, "Kein Request bewertet"
    assert all(r["tardiness"] == 0 for r in bewertet)
    assert all(r["deadline_missed"] is False for r in bewertet)
    assert engine.metrics.deadline_miss_rate() == 0


def test_tardy_request_reports_the_exact_overrun():
    engine = build_engine(sim_time=300, slack=0)
    run(engine)

    bewertet = [r for r in engine.metrics.completed_requests if "tardiness" in r]
    assert bewertet

    for eintrag in bewertet:
        erwartet = max(0, eintrag["time"] - eintrag["latest_time"])
        assert eintrag["tardiness"] == erwartet
        assert eintrag["deadline_missed"] == (erwartet > 0)

    assert any(r["tardiness"] > 0 for r in bewertet), (
        "Mit Slack 0 muss mindestens ein Request verspätet sein."
    )


def test_batched_requests_are_each_judged_against_their_own_deadline():
    """
    Mehrere Requests derselben Bin werden durch EIN physisches Retrieval
    bedient, aber jeder wird gegen seine EIGENE Deadline bewertet.

    Deterministischer Nachweis: zwei Requests auf dieselbe Bin mit
    unterschiedlicher Ankunft und damit unterschiedlicher Deadline.
    """
    engine = build_engine(sim_time=50)
    metrics = engine.metrics
    state = engine.state

    frueh = make_request(1, 500, arrival=0, deadline=10)
    spaet = make_request(2, 500, arrival=40, deadline=50)

    state.t = 30
    aktion = {"type": "remove_target", "bin_id": 500}
    metrics.record_target_bin_at_pickstation(state, aktion, frueh)
    metrics.record_target_bin_at_pickstation(state, aktion, spaet)

    eintraege = {r["request_id"]: r for r in metrics.completed_requests
                 if "request_id" in r}

    assert eintraege[1]["tardiness"] == 20      # 30 - 10
    assert eintraege[1]["deadline_missed"] is True
    assert eintraege[2]["tardiness"] == 0       # 30 <= 50
    assert eintraege[2]["deadline_missed"] is False


def test_batching_counts_requests_individually_but_retrievals_once():
    """
    `bin_throughput` bleibt retrievalbasiert, `request_throughput`
    requestbasiert. Ein Batch ist EIN Retrieval und N Requests.
    """
    engine = build_engine(sim_time=400, zipf=1.5)
    run(engine)

    rows = engine.metrics.retrievals
    assert rows
    gebatcht = [r for r in rows if r["batch_size"] > 1]
    assert gebatcht, "Szenario ohne Batching taugt nicht als Nachweis"

    bediente = sum(r["batch_size"] for r in rows)
    assert bediente > len(rows)
    assert engine.metrics.summary()["physical_retrievals"] == len(rows)


# ======================================================================
# 4. Export
# ======================================================================

def test_request_export_contains_the_deadline_fields():
    from experiments.run_export import REQUEST_FIELDS, request_rows

    engine = build_engine(sim_time=300, slack=240)
    run(engine)

    zeilen = list(request_rows("r1", "baseline_reference", 42, engine))
    assert zeilen, "Keine Request-Zeilen exportiert"

    for zeile in zeilen:
        assert set(zeile.keys()) == set(REQUEST_FIELDS)
        assert zeile["deadline"] == zeile["arrival_time"] + 240
        assert zeile["flow_time"] == zeile["completion_time"] - zeile["arrival_time"]
        assert zeile["lateness"] == zeile["completion_time"] - zeile["deadline"]
        assert zeile["tardiness"] == max(0, zeile["lateness"])
        assert zeile["on_time"] == (zeile["lateness"] <= 0)


def test_run_export_contains_the_secondary_service_kpis():
    from experiments.run_export import RUN_FIELDS, summarise_run
    from metrics.steady_state import analyse_run

    engine = build_engine(sim_time=300, slack=240)
    run(engine)
    steady = analyse_run(engine.metrics.retrievals, block_size=10)

    zeile = summarise_run("r1", "baseline_reference", 42, engine, steady)

    assert set(zeile.keys()) == set(RUN_FIELDS)
    assert zeile["deadline_slack"] == 240
    assert zeile["requests_evaluated"] > 0
    assert 0.0 <= zeile["deadline_miss_rate"] <= 1.0
    assert zeile["mean_tardiness"] is not None
    assert zeile["bin_throughput"] > 0


def test_export_consumes_no_randomness():
    """Die Exportschicht darf die CRN-Eigenschaft nicht zerstören."""
    from experiments.run_export import request_rows, summarise_run
    from metrics.steady_state import analyse_run

    engine = build_engine(sim_time=300)
    run(engine)

    vorher = {
        name: engine.rng_streams.get(name).bit_generator.state
        for name in ("requests", "service", "placement")
    }

    steady = analyse_run(engine.metrics.retrievals, block_size=10)
    summarise_run("r1", "baseline_reference", 42, engine, steady)
    list(request_rows("r1", "baseline_reference", 42, engine))

    for name, zustand in vorher.items():
        assert engine.rng_streams.get(name).bit_generator.state == zustand
