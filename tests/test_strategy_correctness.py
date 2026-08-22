# tests/test_strategy_correctness.py
"""
Fachliche Correctness der vier vorgesehenen Relocation-/Return-Policies.

    A  RR+RR   LOFI       / RANDOM      / return_blocking_bins = False
    B  LR+NR   LOFI       / NEAREST     / return_blocking_bins = False
    C  ABC     ABC        / ABC         / return_blocking_bins = True
    D  POP     POPULARITY / POPULARITY  / return_blocking_bins = True

Dies ist ein AUDIT, kein Strategievergleich. Die Tests prüfen ausschließlich
den fachlichen Contract, nie Durchsatz oder Rangfolge.

Entstehung:
* Phase 3 (Baseline `bfe2a99`) legte die Befunde P3-01 bis P3-04 als
  `xfail(strict=True)` an, statt sie zu verschweigen oder die Erwartung
  abzuschwächen.
* Phase 3B hat diese Befunde behoben. Die Markierungen sind entfernt, die
  Tests laufen regulär grün und wirken ab jetzt als Regressionsschutz.
  Wo sinnvoll, nennt der Docstring den gemessenen Vorher-Zustand.
"""

import contextlib
import io

import pytest

from config.simulation_config import SimulationConfig
from config.init_strategy import assign_abc_classes
from simulation.simulation_engine import SimulationEngine
from simulation.robot_task import RobotTask
from state.bin import Bin
from strategies.reordering_blocking_bins_selector import ReorderingSelector
from strategies.target_bin_placement_selector import PlacementSelector
from utils import distance_helpers


# ======================================================================
# Gemeinsamer Harness
# ======================================================================

POLICIES = {
    "A_RR+RR":   ("LOFI", "RANDOM", False),
    "B_LR+NR":   ("LOFI", "NEAREST", False),
    "C_ABC+ABC": ("ABC", "ABC", True),
    "D_POP+POP": ("POPULARITY", "POPULARITY", True),
}


def build_engine(reordering, placement, return_blocking_bins,
                 seed=42, robots=3, width=7, depth=7, bins=180,
                 height=6, util=0.5, sim_time=400, pickstations=2):
    """
    FINAL FREEZE CLOSEOUT: `bins` von 240 auf 180 gesenkt.

    Seit die Initialverteilung dieselbe Storage-Eligibility nutzt wie das
    Laufzeit-Placement, ist die Port-Pufferzone auch initial gesperrt. Auf
    7x7 sind das 6 der 47 Storage-Stacks, also 13 % der Kapazität; zulässig
    bleiben 41 Stacks x 6 = 246 Slots statt 282.

    Vorher war die Pufferzone initial belegt und lief über die Laufzeit leer
    – das Lager verschob sich also von 240/282 = 85 % auf 240/246 = 98 % der
    NUTZBAREN Kapazität. Mit unveränderten 240 Bins beginnt der Lauf jetzt
    sofort bei 98 %, es bleiben 6 freie Top-Positionen und Relocations
    scheitern (`No relocation stack with free capacity available`).

    180 Bins (73 % der zulässigen Kapazität, 66 freie Slots) halten die
    Fixture über den gesamten Lauf in dem Regime, für das die Tests gedacht
    sind: genug Stapelhöhe für echtes Digging, genug Headroom für
    Relocations. Die geprüften Policy-Eigenschaften hängen nicht am
    Füllgrad. Kein Fallback in der Produktionslogik – die Vorbedingung ist
    explizit gültig.
    """
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.max_stack_height = height
    config.bin_num = bins
    config.num_robots = robots
    config.num_pickstations = pickstations
    config.simulation_time = sim_time
    config.random_seed = seed
    config.request_utilization = util
    config.enable_visualization = False
    config.reordering_strategy = reordering
    config.placement_strategy = placement
    config.return_blocking_bins = return_blocking_bins
    return SimulationEngine(config)


def run_engine(engine):
    """Lässt die Simulation vollständig laufen und gibt einen Fehler zurück."""
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            while engine.step() is not None:
                pass
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            return exc
    return None


def collect_actions(engine):
    """Sammelt alle geplanten Actions eines Laufs."""
    actions = []
    strategy = engine.scheduler.strategy
    original = strategy.next_action

    def spy(state, task):
        action = original(state, task)
        if isinstance(action, dict):
            actions.append(action)
        return action

    strategy.next_action = spy
    error = run_engine(engine)
    return actions, error


def max_height(state):
    """
    `State` traegt selbst kein `max_stack_height`; die Selektoren lesen es
    defensiv ueber `state.config`. Der Test macht dasselbe.
    """
    if hasattr(state, "max_stack_height"):
        return state.max_stack_height
    return state.config.max_stack_height


def stack_position(stack_id):
    if isinstance(stack_id, tuple):
        return stack_id
    if isinstance(stack_id, str) and stack_id.startswith("S_"):
        parts = stack_id.split("_")
        return int(parts[1]), int(parts[2])
    raise AssertionError(f"Unlesbare stack_id: {stack_id}")


def make_bin(bin_id, abc_class=None, access_count=0):
    bin_obj = Bin(bin_id=bin_id, stack_id=None, level=None, status="stored")
    bin_obj.set_abc_class(abc_class)
    for _ in range(access_count):
        bin_obj.increment_access_count()
    return bin_obj


# ======================================================================
# 1. Gemeinsamer Correctness-Contract – parametrisiert über alle Policies
# ======================================================================

@pytest.mark.parametrize("policy", list(POLICIES))
def test_relocation_targets_are_always_admissible(policy):
    """
    Jede Relocation einer Blocking-Bin muss auf einen zulässigen Stack gehen:
    existent, nicht gesperrt, freie Kapazität, keine Portzelle, nicht in der
    Port-Pufferzone und nie der Quellstack selbst.
    """
    reordering, placement, rbb = POLICIES[policy]
    engine = build_engine(reordering, placement, rbb)
    state = engine.state
    grenze = max_height(state)

    seen = []
    strategy = engine.scheduler.strategy
    original = strategy.next_action

    def spy(st, task):
        action = original(st, task)
        if isinstance(action, dict) and action.get("type") == "relocate":
            pos = stack_position(action["to_stack"])
            stack = st.grid.get_stack(*pos)
            seen.append({
                "pos": pos,
                "existiert": stack is not None,
                "gesperrt": stack.is_locked() if stack else None,
                "hoehe": stack.height() if stack else None,
                "ist_port": st.find_pickstation_at(pos) is not None,
                "gueltig": st.is_valid_storage_position(*pos),
                "quelle": action["from_stack"],
                "ziel": action["to_stack"],
            })
        return action

    strategy.next_action = spy
    run_engine(engine)

    for entry in seen:
        assert entry["existiert"], f"Relocation-Ziel {entry['pos']} existiert nicht"
        assert not entry["gesperrt"], f"Relocation-Ziel {entry['pos']} ist gesperrt"
        assert entry["hoehe"] < grenze, (
            f"Relocation-Ziel {entry['pos']} war bereits voll "
            f"({entry['hoehe']}/{grenze})"
        )
        assert not entry["ist_port"], f"Relocation-Ziel {entry['pos']} ist eine Portzelle"
        assert entry["gueltig"], (
            f"Relocation-Ziel {entry['pos']} liegt in der Port-Pufferzone"
        )
        assert entry["ziel"] != entry["quelle"], "Relocation auf den Quellstack"


@pytest.mark.parametrize("policy", ["A_RR+RR", "B_LR+NR"])
def test_no_blocker_restores_when_return_blocking_bins_is_false(policy):
    """
    Bei `return_blocking_bins=False` darf keine einzige Blocker-Rücklagerung
    geplant werden – die Bins bleiben, wo sie abgelegt wurden.
    """
    reordering, placement, rbb = POLICIES[policy]
    assert rbb is False
    engine = build_engine(reordering, placement, rbb)
    actions, _ = collect_actions(engine)

    blocker_returns = [
        a for a in actions
        if a.get("type") == "return" and a.get("return_kind") == "blocker"
    ]
    assert blocker_returns == [], (
        f"{len(blocker_returns)} Blocker-Rücklagerungen trotz "
        f"return_blocking_bins=False"
    )


@pytest.mark.parametrize("policy", ["C_ABC+ABC", "D_POP+POP"])
def test_every_blocker_is_restored_at_most_once_per_task(policy):
    """
    Bei `return_blocking_bins=True` muss jeder ausgelagerte Blocker genau
    einmal je Task zurückgelegt werden – nie doppelt.
    """
    reordering, placement, rbb = POLICIES[policy]
    assert rbb is True
    engine = build_engine(reordering, placement, rbb)

    restored = []
    original = RobotTask.mark_last_relocation_restored

    def spy(self, bin_id, from_stack, to_stack):
        before = len(self.temp_storage)
        result = original(self, bin_id, from_stack, to_stack)
        if len(self.temp_storage) < before:
            restored.append((self.request_id, bin_id))
        return result

    RobotTask.mark_last_relocation_restored = spy
    try:
        run_engine(engine)
    finally:
        RobotTask.mark_last_relocation_restored = original

    assert len(restored) == len(set(restored)), (
        f"Mindestens ein Blocker wurde je Task mehrfach zurückgelegt: "
        f"{[k for k in set(restored) if restored.count(k) > 1]}"
    )


@pytest.mark.parametrize("policy", list(POLICIES))
def test_no_bin_is_lost_or_duplicated(policy):
    """
    Bin-Erhaltung über alle Policies: jede Bin existiert am Ende genau einmal
    – im Stack, getragen oder an der Pickstation.
    """
    reordering, placement, rbb = POLICIES[policy]
    engine = build_engine(reordering, placement, rbb)
    run_engine(engine)

    in_stacks = []
    for stack in engine.state.grid.all_stacks():
        in_stacks.extend(b.bin_id for b in stack.bins)
    carried = {r.get_carried_bin() for r in engine.state.robots}
    carried.discard(None)
    at_pickstation = {
        b.bin_id for b in engine.state.bins
        if b.get_status() == "at_pickstation"
    }

    assert len(in_stacks) == len(set(in_stacks)), "Bin doppelt in Stacks"
    assert not (set(in_stacks) & carried), "Getragene Bin liegt auch im Stack"

    bekannt = set(in_stacks) | carried | at_pickstation
    verloren = [b.bin_id for b in engine.state.bins if b.bin_id not in bekannt]
    assert verloren == [], f"Verlorene Bins: {verloren[:10]}"


# ======================================================================
# 2. A – RR+RR
# ======================================================================

def test_random_relocation_uses_only_admissible_candidates():
    """
    Die Zufallsauswahl im RR+RR-Zweig darf nur aus zulässigen Kandidaten
    ziehen. Geprüft wird das Ergebnis, nicht die Ziehung selbst.
    """
    engine = build_engine("LOFI", "RANDOM", False)
    selector = engine.scheduler.strategy._relocation_selector
    state = engine.state

    source = state.grid.get_stack(3, 3)
    for _ in range(30):
        with contextlib.redirect_stdout(io.StringIO()):
            chosen = selector.select_temporary_stack(state, source)
        pos = stack_position(chosen.stack_id)
        assert chosen is not source
        assert not chosen.is_locked()
        assert chosen.height() < max_height(state)
        assert state.is_valid_storage_position(*pos)


def test_random_return_uses_only_admissible_candidates():
    """RANDOM-Placement darf nur nicht gesperrte Stacks mit Kapazität wählen."""
    engine = build_engine("LOFI", "RANDOM", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state
    bin_obj = make_bin(1)

    for _ in range(30):
        stack = selector.select_return_stack(state, bin_obj, original_stack_id=None)
        assert not stack.is_locked()
        assert stack.height() < max_height(state)
        assert state.find_pickstation_at(stack_position(stack.stack_id)) is None


def test_relocation_selection_uses_a_seed_derived_rng():
    """
    Die Zufallsauswahl der Blocker-Ablage muss an `config.random_seed`
    gebunden sein, sonst ist RR+RR weder reproduzierbar noch für
    Common Random Numbers in Phase 4 brauchbar.

    Bewusst NICHT `engine.rng`: dieser Strom versorgt bereits
    `ActionCostModel` und `PlacementSelector`. Die Relocation bekommt einen
    eigenen, aus demselben Seed abgeleiteten Strom (Phase 3B, P3-03).
    """
    engine = build_engine("LOFI", "RANDOM", False, seed=42)
    selector = engine.scheduler.strategy._relocation_selector

    assert selector.rng is engine.relocation_rng, (
        "RelocationSelection benutzt nicht den vorgesehenen Relocation-Strom"
    )
    assert selector.rng is not engine.rng, (
        "Relocation und Kostenmodell/Placement teilen sich einen Strom – "
        "das ist die Kopplung, die Phase 4 auflösen soll."
    )


def test_relocation_rng_is_deterministic_and_seed_dependent():
    """
    Gleicher Seed → gleiche Ziehungen. Anderer Seed → andere Ziehungen.
    """
    def draws(seed):
        engine = build_engine("LOFI", "RANDOM", False, seed=seed)
        rng = engine.scheduler.strategy._relocation_selector.rng
        return [int(rng.integers(10_000)) for _ in range(8)]

    assert draws(42) == draws(42), "Relocation-RNG ist nicht reproduzierbar"
    assert draws(42) != draws(43), "Relocation-RNG ignoriert den Seed"


def test_rr_rr_is_reproducible_for_a_fixed_seed():
    """
    Gleicher Seed muss zu identischem Endlayout führen.

    Vor dem Fix (Phase 3): drei Läufe mit Seed 42 lieferten 21/23/23
    abgeschlossene Requests und drei verschiedene Endlayouts.
    """
    layouts = []
    completions = []
    for _ in range(3):
        engine = build_engine("LOFI", "RANDOM", False, seed=42)
        run_engine(engine)
        completions.append(
            engine.metrics.summary().get("requests_completed", 0) or 0
        )
        layouts.append(tuple(sorted(
            (s.stack_id, tuple(b.bin_id for b in s.bins))
            for s in engine.state.grid.all_stacks()
        )))

    assert len(set(completions)) == 1, (
        f"Abgeschlossene Requests streuen über Wiederholungen: {completions}"
    )
    assert len(set(layouts)) == 1, "Endlayout ist nicht reproduzierbar"


# ======================================================================
# 3. B – LR+NR
# ======================================================================

def test_nearest_placement_is_deterministic_and_admissible():
    """
    NEAREST muss deterministisch sein und einen zulässigen Stack liefern.
    Diese Eigenschaft gilt unabhängig davon, worauf sich „nearest" bezieht.
    """
    engine = build_engine("LOFI", "NEAREST", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state
    bin_obj = make_bin(1)

    chosen = {
        selector.select_return_stack(state, bin_obj, original_stack_id="S_5_5").stack_id
        for _ in range(10)
    }
    assert len(chosen) == 1, f"NEAREST ist nicht deterministisch: {chosen}"

    stack = state.grid.get_stack(*stack_position(chosen.pop()))
    assert not stack.is_locked()
    assert stack.height() < max_height(state)
    assert state.is_valid_storage_position(*stack_position(stack.stack_id))


def _eligible_stacks(state):
    """Zulässige Rücklagerungsziele nach `_get_eligible_stacks`."""
    return [
        s for s in state.grid.all_stacks()
        if not s.is_locked()
        and s.height() < max_height(state)
        and state.is_valid_storage_position(*stack_position(s.stack_id))
    ]


def test_nearest_minimises_manhattan_distance_to_the_original_stack():
    """
    Verbindlicher NR-Contract (Phase 3B):
        1. minimale Manhattan-Distanz zum Originalstack
        2. Tie-Break kleinere y-Koordinate
        3. danach kleinere x-Koordinate

    Ausdrücklich NICHT die Distanz zur Pickstation.
    """
    engine = build_engine("LOFI", "NEAREST", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    for original_id in ("S_6_6", "S_0_0", "S_3_1"):
        origin = stack_position(original_id)
        stack = selector.select_return_stack(
            state, make_bin(1), original_stack_id=original_id
        )
        pos = stack_position(stack.stack_id)

        def key(p):
            return (abs(p[0] - origin[0]) + abs(p[1] - origin[1]), p[1], p[0])

        best = min(key(stack_position(s.stack_id))
                   for s in _eligible_stacks(state))
        assert key(pos) == best, (
            f"Originalstack {original_id}: gewählt {pos} mit Schlüssel "
            f"{key(pos)}, bester zulässiger Schlüssel wäre {best}"
        )


def test_nearest_prefers_the_original_stack_when_admissible():
    """
    Ist der Originalstack selbst zulässig, gewinnt er mit Distanz 0.
    """
    engine = build_engine("LOFI", "NEAREST", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    original = None
    for stack in state.grid.all_stacks():
        pos = stack_position(stack.stack_id)
        if (not stack.is_locked()
                and stack.height() < max_height(state) - 1
                and state.is_valid_storage_position(*pos)):
            original = stack
            break
    assert original is not None

    chosen = selector.select_return_stack(
        state, make_bin(1), original_stack_id=original.stack_id
    )
    assert chosen.stack_id == original.stack_id


def test_nearest_falls_back_deterministically_without_an_original_stack():
    """
    Ist der Originalstack nicht auflösbar, muss die Auswahl trotzdem
    deterministisch und zulässig bleiben (dokumentierter Fallback auf die
    Distanz zur nächsten Pickstation).
    """
    engine = build_engine("LOFI", "NEAREST", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    with contextlib.redirect_stdout(io.StringIO()) as buf:
        gewaehlt = {
            selector.select_return_stack(
                state, make_bin(1), original_stack_id=None).stack_id
            for _ in range(5)
        }

    assert len(gewaehlt) == 1, f"Fallback ist nicht deterministisch: {gewaehlt}"
    assert "[NEAREST][FALLBACK]" in buf.getvalue()

    pos = stack_position(gewaehlt.pop())
    assert state.is_valid_storage_position(*pos)
    assert state.grid.get_stack(*pos).height() < max_height(state)


def test_nearest_spreads_returns_instead_of_clustering_at_the_port():
    """
    Wirkungsnachweis für P3-04.

    Die alte Semantik (Distanz zur Pickstation) lieferte für JEDE Bin
    denselben Stack, solange dieser Kapazität hatte. Die neue Semantik muss
    für unterschiedliche Originalstacks unterschiedliche Ziele liefern.
    """
    engine = build_engine("LOFI", "NEAREST", False)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    ziele = {
        selector.select_return_stack(
            state, make_bin(1), original_stack_id=s.stack_id).stack_id
        for s in _eligible_stacks(state)
    }
    assert len(ziele) > 1, (
        "NEAREST liefert für alle Originalstacks dasselbe Ziel – das wäre "
        "weiterhin Port-Konzentration statt Strukturerhalt."
    )


# ======================================================================
# 4. C – ABC
# ======================================================================

def test_abc_reordering_puts_c_at_the_bottom_and_a_on_top():
    """`[A, C, B]` muss als `[C, B, A]` zurückgelegt werden."""
    config = SimulationConfig()
    config.reordering_strategy = "ABC"
    selector = ReorderingSelector(config)

    a, c, b = make_bin(1, "A"), make_bin(2, "C"), make_bin(3, "B")
    order = selector.reorder_blockers([a, c, b])

    assert [x.get_abc_class() for x in order] == ["C", "B", "A"]
    # Erste Bin wird zuerst zurückgelegt -> liegt am weitesten unten.
    assert order[0] is c and order[-1] is a


def test_abc_reordering_is_stable_within_a_class():
    """Gleiche Klasse behält die ursprüngliche Reihenfolge."""
    config = SimulationConfig()
    config.reordering_strategy = "ABC"
    selector = ReorderingSelector(config)

    bins = [make_bin(i, "B") for i in range(5)]
    assert selector.reorder_blockers(bins) == bins


def test_abc_class_assignment_matches_demand_direction():
    """
    A muss die häufiger nachgefragten Bins bezeichnen.

    Belegt am tatsächlichen Nachfragestrom: `assign_abc_classes` vergibt A an
    niedrige bin_ids, und `zipf_bin_sampling` zieht niedrige Indizes mit
    höherer Wahrscheinlichkeit. Beide Annahmen müssen zusammenpassen.
    """
    config = SimulationConfig()
    config.grid_width = 12
    config.grid_depth = 18
    config.max_stack_height = 8
    config.bin_num = 1150
    config.num_robots = 2
    config.num_pickstations = 2
    config.simulation_time = 600
    config.random_seed = 42
    config.request_utilization = 0.6
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = 1.5
    config.enable_visualization = False
    config.reordering_strategy = "ABC"
    config.placement_strategy = "ABC"

    engine = SimulationEngine(config)
    klasse = {b.bin_id: b.get_abc_class() for b in engine.state.bins}

    nachfrage = {"A": 0, "B": 0, "C": 0}
    for _, request in engine.state.future_request_queue.queue:
        cls = klasse.get(request.target_box_id)
        if cls in nachfrage:
            nachfrage[cls] += 1

    assert sum(nachfrage.values()) > 0, "Kein Nachfragestrom erzeugt"
    assert nachfrage["A"] > nachfrage["B"] > nachfrage["C"], (
        f"ABC-Klassensemantik verdreht: {nachfrage}"
    )


def test_abc_thresholds_split_bins_as_configured():
    """20 % A, 30 % B, 50 % C bei den Standardschwellen."""
    bins = [make_bin(i) for i in range(1000)]
    assign_abc_classes(bins, abc_threshold_a=0.2, abc_threshold_b=0.5)
    verteilung = {"A": 0, "B": 0, "C": 0}
    for b in bins:
        verteilung[b.get_abc_class()] += 1
    assert verteilung == {"A": 200, "B": 300, "C": 500}


def test_abc_placement_is_score_based_not_zone_based():
    """
    Hält die tatsächlich implementierte ABC-Placement-Variante fest:
    KEINE Zonen/Terzile, sondern ein Greedy-Score über alle zulässigen Stacks.

        A: minimiert (Distanz + Stackhöhe)
        C: maximiert  Distanz
    """
    engine = build_engine("ABC", "ABC", True)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    def kandidaten():
        result = []
        for stack in state.grid.all_stacks():
            pos = stack_position(stack.stack_id)
            if (not stack.is_locked()
                    and stack.height() < max_height(state)
                    and state.is_valid_storage_position(*pos)):
                result.append(
                    (stack,
                     distance_helpers.get_min_distance_to_pickstation(state, pos),
                     stack.height())
                )
        return result

    alle = kandidaten()

    a_stack = selector.select_return_stack(state, make_bin(1, "A"), None)
    a_pos = stack_position(a_stack.stack_id)
    a_score = (distance_helpers.get_min_distance_to_pickstation(state, a_pos)
               + a_stack.height())
    assert a_score == min(dist + hoehe for _, dist, hoehe in alle)

    c_stack = selector.select_return_stack(state, make_bin(2, "C"), None)
    c_dist = distance_helpers.get_min_distance_to_pickstation(
        state, stack_position(c_stack.stack_id))
    assert c_dist == max(dist for _, dist, _ in alle)


def test_abc_placement_measures_distance_to_the_nearest_of_two_pickstations():
    """Bei zwei Pickstations zählt immer die nähere."""
    engine = build_engine("ABC", "ABC", True, pickstations=2)
    state = engine.state
    assert len(state.pickstations) == 2

    for pos in [(0, 0), (6, 6), (3, 3)]:
        erwartet = min(
            abs(pos[0] - ps.position[0]) + abs(pos[1] - ps.position[1])
            for ps in state.pickstations
        )
        assert distance_helpers.get_min_distance_to_pickstation(state, pos) == erwartet


# ======================================================================
# 5. D – POPULARITY
# ======================================================================

def test_popularity_reordering_sorts_by_access_count_ascending():
    """Counts `[5, 1, 10]` müssen als `[1, 5, 10]` zurückgelegt werden."""
    config = SimulationConfig()
    config.reordering_strategy = "POPULARITY"
    selector = ReorderingSelector(config)

    bins = [make_bin(1, access_count=5),
            make_bin(2, access_count=1),
            make_bin(3, access_count=10)]
    order = selector.reorder_blockers(bins)
    assert [b.get_access_count() for b in order] == [1, 5, 10]


def test_popularity_reordering_is_stable_for_equal_counts():
    """Gleiche Counts behalten ihre Reihenfolge."""
    config = SimulationConfig()
    config.reordering_strategy = "POPULARITY"
    selector = ReorderingSelector(config)

    bins = [make_bin(i, access_count=3) for i in range(5)]
    assert selector.reorder_blockers(bins) == bins


def test_strategies_never_read_the_future_request_queue():
    """
    Kein Look-ahead: Popularity darf ausschließlich beobachtete Zugriffe
    nutzen, niemals die bereits erzeugte FutureRequestQueue.
    """
    import inspect
    import strategies.target_bin_placement_selector as placement_mod
    import strategies.reordering_blocking_bins_selector as reorder_mod
    import strategies.relocation_selection as reloc_mod
    import strategies.top_access_strategy as top_mod

    for modul in (placement_mod, reorder_mod, reloc_mod, top_mod):
        quelle = inspect.getsource(modul)
        assert "future_request_queue" not in quelle, (
            f"{modul.__name__} greift auf die FutureRequestQueue zu – "
            f"das wäre Wissen über die Zukunft."
        )


def test_popularity_placement_falls_back_to_random_during_cold_start():
    """
    Solange keine Zugriffe beobachtet wurden, ist keine Popularität definiert.
    Dokumentiert den implementierten Cold-Start: zufällige Wahl.
    """
    engine = build_engine("POPULARITY", "POPULARITY", True)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    assert max(b.get_access_count() for b in state.bins) == 0

    ziele = {
        selector.select_return_stack(state, make_bin(1), None).stack_id
        for _ in range(40)
    }
    # Zufall streut; die deterministischen Zweige liefern genau ein Ziel.
    assert len(ziele) > 1, (
        "Cold-Start liefert ein einziges Ziel – das wäre kein Zufalls-Fallback."
    )


def test_popularity_warmup_uses_the_same_eligibility_as_the_active_phase():
    """
    P3-05: Warmup und aktive Popularity-Phase müssen dieselbe Kandidatenmenge
    verwenden. Insbesondere darf der Warmup nicht in die Port-Pufferzone
    platzieren, die die aktive Phase ausschließt.

    Vor dem Fix rief der Warmup `_select_random_stack`, das den
    Pufferzonen-Filter bewusst nicht anwendet (eigenständige RANDOM-Semantik
    von RR+RR) – gemessen 596 Platzierungen in der Pufferzone.
    """
    engine = build_engine("POPULARITY", "POPULARITY", True)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    assert max(b.get_access_count() for b in state.bins) == 0, "Vorbedingung: Warmup"

    zulaessig = {stack_position(s.stack_id) for s in _eligible_stacks(state)}
    for _ in range(200):
        pos = stack_position(
            selector.select_return_stack(state, make_bin(1), None).stack_id)
        assert state.is_valid_storage_position(*pos), (
            f"Warmup platziert auf {pos} in der Port-Pufferzone"
        )
        assert pos in zulaessig


@pytest.mark.parametrize("policy", list(POLICIES))
def test_all_placement_strategies_share_one_eligibility_set(policy):
    """
    MODELLKORREKTUR (Phase 5, Experiment Readiness):

    Bis Phase 3B durfte AUSSCHLIESSLICH `RANDOM` in die Port-Pufferzone
    platzieren; NEAREST/ABC/POPULARITY schlossen sie aus. Der zur Laufzeit
    erreichbare Zustandsraum war dadurch policyabhängig – im finalen Setup
    598 gegenüber 592 Stacks. Räumliche Metriken wären auf unterschiedlichen
    Trägermengen gemessen worden, und die Pufferzonen-Stacks liegen ausgerechnet
    dort, wo NEAREST/ABC/POPULARITY am liebsten platzieren würden.

    Für den wissenschaftlichen Vergleich gilt jetzt EINE gemeinsame Definition
    zulässiger Lagerplätze für alle Placement-Strategien.

    Der frühere Test hieß `test_random_placement_keeps_its_own_semantics` und
    sicherte die alte Sonderrolle von RANDOM ab. Sie war als Schutz gegen eine
    VERSEHENTLICHE Änderung gedacht; hier liegt eine bewusste, begründete
    Änderung vor. Der Test wurde daher nicht abgeschwächt, sondern auf den
    heute gültigen gemeinsamen Contract umgestellt.
    """
    reordering, placement, rbb = POLICIES[policy]
    engine = build_engine(reordering, placement, rbb)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    alle = [
        s for s in state.grid.all_stacks()
        if not s.is_locked() and s.height() < max_height(state)
    ]
    zulaessig = {stack_position(s.stack_id) for s in _eligible_stacks(state)}

    assert len(alle) > len(zulaessig), (
        "Testszenario hat keine Pufferzonen-Stacks – die Unterscheidung wäre "
        "nicht prüfbar."
    )

    for _ in range(120):
        pos = stack_position(
            selector.select_return_stack(state, make_bin(1), "S_5_5").stack_id)
        assert pos in zulaessig, (
            f"{policy} platziert auf {pos} außerhalb der gemeinsamen "
            f"Kandidatenmenge (Port-Pufferzone)."
        )


def test_popularity_placement_reacts_to_changed_access_counts():
    """
    Nach Verlassen des Warmups muss sich die Platzierung nachweislich
    unterscheiden, je nachdem ob eine Bin heiß oder kalt ist.
    """
    engine = build_engine("POPULARITY", "POPULARITY", True)
    selector = engine.scheduler.strategy._placement_selector
    state = engine.state

    # Warmup künstlich beenden: Zugriffe auf beliebige Bins verteilen.
    for bin_obj in state.bins[:60]:
        for _ in range(2):
            bin_obj.increment_access_count()
    referenz = max(b.get_access_count() for b in state.bins)
    assert referenz > 0

    heiss = make_bin(9001, access_count=referenz)
    kalt = make_bin(9002, access_count=0)

    heiss_pos = stack_position(
        selector.select_return_stack(state, heiss, None).stack_id)
    kalt_pos = stack_position(
        selector.select_return_stack(state, kalt, None).stack_id)

    d_heiss = distance_helpers.get_min_distance_to_pickstation(state, heiss_pos)
    d_kalt = distance_helpers.get_min_distance_to_pickstation(state, kalt_pos)

    assert heiss_pos != kalt_pos, "Heiß und kalt landen auf demselben Stack"
    assert d_heiss < d_kalt, (
        f"Heiße Bin liegt nicht näher an der Pickstation "
        f"(heiß={d_heiss}, kalt={d_kalt})"
    )


def test_access_count_increases_on_real_retrievals():
    """
    Popularity braucht beobachtete Zugriffe. Nach einem Lauf mit Dutzenden
    abgeschlossenen Requests darf `access_count` nicht überall 0 sein.

    Vor dem Fix (Phase 3): 109 abgeschlossene Requests, Summe aller
    `access_count` = 0.
    """
    # Starke Nachfragekonzentration, damit einzelne Bins mehrfach abgerufen
    # werden. Seit dem Wegfall des opportunistischen Bypass (Freeze-Audit)
    # leistet das System je Zeiteinheit weniger Retrievals; das Szenario
    # braucht deshalb mehr Zeit und mehr Konzentration.
    engine = build_engine("POPULARITY", "POPULARITY", True, sim_time=1500)
    engine.config.zipf_parameter = 1.5
    run_engine(engine)

    abgeschlossen = engine.metrics.summary().get("requests_completed", 0) or 0
    assert abgeschlossen > 0, "Testszenario hat keinen Request abgeschlossen"

    counts = [b.get_access_count() for b in engine.state.bins]
    assert sum(counts) > 0, (
        f"{abgeschlossen} Requests abgeschlossen, aber Summe aller "
        f"access_counts ist {sum(counts)}"
    )
    assert max(counts) > 1, (
        "Kein einziger Bin wurde mehrfach abgerufen – die Counts "
        "differenzieren nicht und taugen nicht als Popularitätsmaß."
    )


def test_access_count_ignores_blocker_movements():
    """
    Nur Target-Retrievals zählen. Relocations und Rücklagerungen sind keine
    Nachfrage und dürfen den Zähler nicht erhöhen.

    Belegt über die Bilanz: die Summe aller `access_count` darf die Zahl der
    tatsächlich an der Pickstation angekommenen Target-Bins nicht übersteigen,
    obwohl es im selben Lauf deutlich mehr Bin-Bewegungen gab.
    """
    engine = build_engine("POPULARITY", "POPULARITY", True, sim_time=600)

    bewegungen = {"relocate": 0, "return": 0, "remove_target": 0}
    strategy = engine.scheduler.strategy
    original = strategy.next_action

    def spy(state, task):
        action = original(state, task)
        if isinstance(action, dict) and action.get("type") in bewegungen:
            bewegungen[action["type"]] += 1
        return action

    strategy.next_action = spy
    run_engine(engine)

    gesamt = sum(b.get_access_count() for b in engine.state.bins)
    assert bewegungen["relocate"] + bewegungen["return"] > 0, (
        "Szenario enthält keine Blocker-/Rücklagerungsbewegungen"
    )
    assert gesamt <= bewegungen["remove_target"], (
        f"access_count ({gesamt}) übersteigt die Zahl geplanter "
        f"Target-Retrievals ({bewegungen['remove_target']}) – es werden "
        f"Bewegungen mitgezählt, die keine Nachfrage sind."
    )


def test_popularity_placement_leaves_warmup_in_a_realistic_run():
    """
    Nach hinreichend vielen Retrievals muss die eigene Logik greifen.

    Vor dem Fix (Phase 3): 113 von 113 Placement-Aufrufen liefen im
    RANDOM-Warmup-Fallback, weil `access_count` nie stieg.

    Hinweis zur Größe: `access_count` zählt physische Retrievals, nicht
    Requests. Durch Batching entfallen im Mittel 2,4–2,7 Requests auf einen
    Retrieval; die Warmup-Schwelle wird daher erst in hinreichend langen
    Läufen erreicht (siehe Risiko R-12).
    """
    engine = build_engine(
        "POPULARITY", "POPULARITY", True, robots=4, sim_time=3000
    )
    run_engine(engine)

    warmup = engine.config.popularity_warmup_retrievals
    gesamt = sum(b.get_access_count() for b in engine.state.bins)
    assert gesamt >= warmup, (
        f"total_accesses={gesamt} < warmup={warmup}: Placement lief "
        f"ausschließlich im RANDOM-Fallback."
    )


def test_popularity_placement_actually_runs_its_own_logic():
    """
    Der Nachweis, dass die Hot/Cold-Logik im realen Lauf erreicht wird –
    nicht nur, dass die Schwelle rechnerisch überschritten ist.
    """
    engine = build_engine(
        "POPULARITY", "POPULARITY", True, robots=4, sim_time=1200
    )
    selector = engine.scheduler.strategy._placement_selector
    original = selector._select_random_stack

    aufrufe = {"gesamt": 0, "random_fallback": 0}
    place_original = selector._select_popularity_stack

    def zaehle_fallback(state):
        aufrufe["random_fallback"] += 1
        return original(state)

    def zaehle_placement(state, bin_obj):
        aufrufe["gesamt"] += 1
        return place_original(state, bin_obj)

    selector._select_random_stack = zaehle_fallback
    selector._select_popularity_stack = zaehle_placement
    run_engine(engine)

    assert aufrufe["gesamt"] > 0, "Kein POPULARITY-Placement ausgeführt"
    echte = aufrufe["gesamt"] - aufrufe["random_fallback"]
    assert echte > 0, (
        f"Alle {aufrufe['gesamt']} Placement-Aufrufe liefen im "
        f"RANDOM-Fallback – die Policy ist weiterhin wirkungslos."
    )


# ======================================================================
# 6. Blocker-Ownership bei return_blocking_bins = False
# ======================================================================

def test_clear_all_relocations_empties_the_task_temp_storage():
    """Die Restore-Verpflichtung des Tasks selbst wird korrekt verworfen."""
    engine = build_engine("LOFI", "RANDOM", False)
    request = next(iter(engine.state.future_request_queue.queue))[1]
    task = RobotTask(request)
    task.remember_relocation(bin_id=7, from_stack="S_1_1", buffer_stack="S_2_2")

    assert task.has_blockers_to_restore()
    task.clear_all_relocations()
    assert not task.has_blockers_to_restore()
    assert task.temp_storage == []


def test_discarding_restores_also_releases_global_blocker_ownership():
    """
    Wird die Restore-Verpflichtung verworfen, darf keine globale
    Blocker-Reservierung zurückbleiben – sonst bleibt die Bin für andere
    Tasks gesperrt und ihr Stack als Relocation-Ziel ausgeschlossen.

    Geprüft wird der ECHTE Pfad: `TopAccessStrategy` entscheidet anhand von
    `return_blocking_bins` und reicht die Queue durch. Der frühere Test rief
    `clear_all_relocations()` direkt auf und prüfte damit ein
    Implementierungsdetail statt des Verhaltens.
    """
    engine = build_engine("LOFI", "RANDOM", False)
    queue = engine.active_queue
    strategy = engine.scheduler.strategy
    request = next(iter(engine.state.future_request_queue.queue))[1]

    task = RobotTask(request)
    task.phase = RobotTask.PHASE_RESTORE_BLOCKERS
    task.target_at_pickstation = True
    task.remember_relocation(bin_id=7, from_stack="S_1_1", buffer_stack="S_2_2")
    queue.register_blocker_ownership(7, task)

    assert queue.is_bin_blocker_owned(7)

    with contextlib.redirect_stdout(io.StringIO()):
        strategy._next_restore_blockers_action(engine.state, task)

    assert task.temp_storage == [], "Task-lokale Verpflichtung nicht verworfen"
    assert task.blockers_reordered is True, "blockers_reordered inkonsistent"
    assert not queue.is_bin_blocker_owned(7), (
        "Bin 7 ist weiterhin global als Blocker reserviert, obwohl der Task "
        "sie nicht mehr zurücklegen wird."
    )


def test_clear_all_relocations_releases_only_its_own_ownership():
    """
    Wurde eine Bin zwischenzeitlich an einen anderen Task übertragen, darf das
    Verwerfen der eigenen Verpflichtung dessen Ownership NICHT anfassen.
    """
    engine = build_engine("LOFI", "RANDOM", False)
    queue = engine.active_queue
    requests = [r for _, r in list(engine.state.future_request_queue.queue)[:2]]

    eigner = RobotTask(requests[0])
    fremder = RobotTask(requests[1])

    eigner.remember_relocation(bin_id=7, from_stack="S_1_1", buffer_stack="S_2_2")
    eigner.remember_relocation(bin_id=8, from_stack="S_1_1", buffer_stack="S_3_3")
    queue.register_blocker_ownership(7, eigner)
    queue.register_blocker_ownership(8, fremder)  # 8 gehört inzwischen fremd

    verworfen = eigner.clear_all_relocations(active_queue=queue)

    assert {r["bin_id"] for r in verworfen} == {7, 8}
    assert not queue.is_bin_blocker_owned(7), "Eigene Ownership nicht gelöst"
    assert queue.get_blocker_owner(8) is fremder, (
        "Fremde Ownership wurde mit freigegeben"
    )


def test_ownership_transfer_survives_an_already_released_obligation():
    """
    Regression gegen die Folgewirkung von P3-02.

    Der opportunistische Ownership-Transfer im Scheduler rief früher
    `RobotTask.release_blocker_ownership()` ungeprüft und wertete den
    Rückgabewert aus. Die Methode liefert aber nie None, sondern wirft –
    die Simulation brach mit
        RuntimeError: Cannot release ownership of bin 125 from task 0
    ab (10 von 134 Systemläufen der Policies A und B).

    Der Transferpfad muss eine bereits erledigte Verpflichtung aushalten.
    """
    engine = build_engine("LOFI", "RANDOM", False)
    queue = engine.active_queue
    request = next(iter(engine.state.future_request_queue.queue))[1]

    task = RobotTask(request)
    queue.register_blocker_ownership(7, task)  # Ownership ohne temp_storage

    still_open = any(r["bin_id"] == 7 for r in task.temp_storage)
    assert still_open is False, "Vorbedingung: Verpflichtung ist bereits weg"

    with contextlib.redirect_stdout(io.StringIO()):
        if still_open:  # genau die Prüfung aus dem Scheduler
            task.release_blocker_ownership(7)
        queue.release_blocker_ownership(7)

    assert not queue.is_bin_blocker_owned(7)
