# tests/test_ordered_return_stack_order.py
"""
Regression fuer die Richtung des Ordered Return (2026-08-22).

Fehlerbild
----------
`ReorderingSelector.reorder_blockers` liefert die RUECKLAGERUNGSreihenfolge:
erstes Element wird zuerst zurueckgelegt und landet damit UNTEN. Die
Rueckgabe konsumiert `temp_storage` aber vom ENDE her
(`peek_last_relocation` -> `temp_storage[-1]`).

`reorder_blockers_for_return` sortierte aufsteigend nach dieser Reihenfolge
und drehte sie damit exakt um:

    ABC        Soll  C unten, B, A oben   ->  Ist  A unten, B, C oben
    POPULARITY Soll  kalt unten, heiss oben ->  Ist  heiss unten, kalt oben
    LOFI       Soll  Originalstapel        ->  Ist  invertiert

Beide untersuchten Policies legten die haeufig nachgefragten Bins also
systematisch nach UNTEN — das Gegenteil ihrer Definition — und erhoehten bei
jedem Ordered Return die Grabtiefe fuer genau die Bins, die am haeufigsten
gebraucht werden.

Warum es niemand gemerkt hat: die vorhandenen Tests pruefen den Selektor
ISOLIERT (dort war die Reihenfolge korrekt) und nie die Stapelordnung, die
am Ende tatsaechlich entsteht. Genau die pruefen die Tests hier.

Kontrollrechnung fuer die Richtung: Ohne Reordering ist `temp_storage` in
Auslagerungsreihenfolge [oberste, ..., unterste]; die unterste muss zuerst
zurueck und steht am Ende — die Konsumreihenfolge stimmt also. LOFI liefert
genau diese Reihenfolge und MUSS deshalb ein No-Op sein. Das ist der
unabhaengige Pruefstein fuer die Sortierrichtung.
"""

import pytest

from config.simulation_config import SimulationConfig
from events.event_types import EventType
from requests_.request import Request
from simulation.robot_task import RobotTask
from state.bin import Bin
from strategies.reordering_blocking_bins_selector import ReorderingSelector


class FakeState:
    """Minimaler State: nur Bin-Lookup wird gebraucht."""

    def __init__(self, bins):
        self._bins = {b.bin_id: b for b in bins}

    def get_bin_by_id(self, bin_id):
        return self._bins.get(bin_id)


def make_bin(bin_id, abc_class=None, access_count=0):
    bin_obj = Bin(bin_id, None, None, "stored")
    if abc_class is not None:
        bin_obj.set_abc_class(abc_class)
    for _ in range(access_count):
        bin_obj.increment_access_count()
    return bin_obj


def build_task(bins):
    """
    Baut einen Task, dessen Blocker in `bins`-Reihenfolge ausgelagert wurden.

    `bins[0]` lag ganz oben und wurde zuerst ausgelagert.
    """
    task = RobotTask(Request(
        request_id=1, event_type=EventType.ARRIVAL, bin_id=999,
        t_arrival=0, t_earliest=0, t_latest=100,
    ))
    for bin_obj in bins:
        task.remember_relocation(bin_id=bin_obj.bin_id, from_stack="S_1_1",
                                 buffer_stack="S_2_2")
    return task


def resulting_stack_bottom_to_top(task):
    """
    Simuliert die Rueckgabeschleife und liefert die Stapelordnung.

    Die Schleife entspricht `TopAccessStrategy._next_restore_blockers_action`:
    solange `peek_last_relocation()` etwas liefert, wird diese Bin
    zurueckgelegt. Die Reihenfolge der Rueckgaben ist damit die Ordnung von
    unten nach oben.
    """
    reihenfolge = []
    while task.temp_storage:
        eintrag = task.peek_last_relocation()
        reihenfolge.append(eintrag["bin_id"])
        task.mark_last_relocation_restored(
            bin_id=eintrag["bin_id"],
            from_stack=eintrag["buffer_stack"],
            to_stack=eintrag["from_stack"],
        )
    return reihenfolge


def reorder(strategy, bins):
    config = SimulationConfig()
    config.reordering_strategy = strategy
    task = build_task(bins)
    task.reorder_blockers_for_return(FakeState(bins), ReorderingSelector(config))
    return resulting_stack_bottom_to_top(task)


# ====================================================================== #
# ABC
# ====================================================================== #

def test_abc_ordered_return_puts_a_class_on_top():
    """C unten, B mittig, A oben — die definierte ABC-Ordnung."""
    bins = [make_bin(10, "A"), make_bin(11, "B"), make_bin(12, "C")]
    unten_nach_oben = reorder("ABC", bins)

    klassen = {b.bin_id: b.get_abc_class() for b in bins}
    assert [klassen[b] for b in unten_nach_oben] == ["C", "B", "A"], (
        "A-Bins muessen oben liegen, nicht unten — sonst erhoeht jeder "
        "Ordered Return die Grabtiefe der haeufigsten Bins."
    )


def test_abc_ordered_return_with_several_bins_per_class():
    """Mehrere Bins je Klasse: Klassenordnung gilt, innerhalb stabil."""
    bins = [
        make_bin(20, "A"), make_bin(21, "C"), make_bin(22, "B"),
        make_bin(23, "A"), make_bin(24, "C"),
    ]
    unten_nach_oben = reorder("ABC", bins)
    klassen = {b.bin_id: b.get_abc_class() for b in bins}
    folge = [klassen[b] for b in unten_nach_oben]

    assert folge == ["C", "C", "B", "A", "A"], folge
    # Innerhalb einer Klasse bleibt die Auslagerungsreihenfolge erhalten:
    # 21 wurde vor 24 ausgelagert, liegt danach also weiter unten.
    assert unten_nach_oben.index(21) < unten_nach_oben.index(24)
    assert unten_nach_oben.index(20) < unten_nach_oben.index(23)


def test_abc_reordering_is_deterministic():
    """Zweimal derselbe Aufbau ergibt zweimal dieselbe Ordnung."""
    def lauf():
        return reorder("ABC", [make_bin(30, "B"), make_bin(31, "A"),
                               make_bin(32, "C"), make_bin(33, "B")])

    assert lauf() == lauf()


# ====================================================================== #
# POPULARITY
# ====================================================================== #

def test_popularity_ordered_return_puts_hot_bins_on_top():
    """Niedriger access_count unten, hoher oben."""
    bins = [make_bin(40, access_count=20), make_bin(41, access_count=5),
            make_bin(42, access_count=0)]
    unten_nach_oben = reorder("POPULARITY", bins)

    counts = {b.bin_id: b.get_access_count() for b in bins}
    assert [counts[b] for b in unten_nach_oben] == [0, 5, 20], (
        "Haeufig zugegriffene Bins muessen oben liegen."
    )


def test_popularity_uses_access_count_not_abc_class():
    """
    Die Popularity-Ordnung folgt dem beobachteten `access_count`, nicht der
    statischen ABC-Klasse.
    """
    bins = [
        make_bin(50, "A", access_count=0),    # A-Klasse, aber nie angefragt
        make_bin(51, "C", access_count=30),   # C-Klasse, aber sehr heiss
    ]
    unten_nach_oben = reorder("POPULARITY", bins)

    assert unten_nach_oben == [50, 51], (
        "Die kalte A-Bin gehoert unter die heisse C-Bin."
    )


def test_popularity_ties_keep_the_relocation_order():
    """Bei gleichem access_count bleibt die Auslagerungsreihenfolge erhalten."""
    bins = [make_bin(60, access_count=3), make_bin(61, access_count=3),
            make_bin(62, access_count=3)]
    unten_nach_oben = reorder("POPULARITY", bins)

    # 60 wurde zuerst ausgelagert (lag oben) und liegt danach unten.
    assert unten_nach_oben == [60, 61, 62]


# ====================================================================== #
# LOFI — der unabhaengige Pruefstein
# ====================================================================== #

def test_lofi_restores_the_original_stack_order():
    """
    LOFI muss den urspruenglichen Stapel wiederherstellen.

    `bins[0]` lag oben, `bins[-1]` unten. Nach dem Ordered Return muss genau
    diese Ordnung wieder entstehen. Das ist der von der Reordering-Strategie
    unabhaengige Nachweis, dass die Sortierrichtung stimmt.
    """
    bins = [make_bin(70), make_bin(71), make_bin(72)]
    unten_nach_oben = reorder("LOFI", bins)

    assert unten_nach_oben == [72, 71, 70], (
        "LOFI muss ein No-Op sein: die unterste Blocker-Bin zuerst zurueck."
    )


def test_lofi_leaves_temp_storage_untouched():
    """Formal: LOFI aendert die Reihenfolge in `temp_storage` nicht."""
    bins = [make_bin(80), make_bin(81), make_bin(82), make_bin(83)]
    config = SimulationConfig()
    config.reordering_strategy = "LOFI"

    task = build_task(bins)
    vorher = [r["bin_id"] for r in task.temp_storage]
    task.reorder_blockers_for_return(FakeState(bins), ReorderingSelector(config))
    nachher = [r["bin_id"] for r in task.temp_storage]

    assert nachher == vorher


# ====================================================================== #
# Ende-zu-Ende im echten Lauf
# ====================================================================== #

@pytest.mark.parametrize("strategy,check", [
    ("ABC", "abc"),
    ("POPULARITY", "pop"),
])
def test_restored_stacks_follow_the_policy_in_a_real_run(strategy, check):
    """
    Im echten Lauf muss die Ordnung ebenfalls stimmen.

    Geprueft wird ueber alle Stapel: liegt im Mittel die A-Klasse (bzw. die
    haeufiger zugegriffenen Bins) weiter oben als die C-Klasse?
    """
    import contextlib
    import io

    from simulation.simulation_engine import SimulationEngine

    config = SimulationConfig()
    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 150
    config.num_robots = 4
    config.num_pickstations = 2
    config.simulation_time = 1500
    config.random_seed = 42
    config.request_utilization = 0.5
    config.enable_visualization = False
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = 1.0
    config.reordering_strategy = strategy
    config.placement_strategy = strategy
    config.return_blocking_bins = True

    engine = SimulationEngine(config)
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            pass

    tiefen = {"A": [], "B": [], "C": []}
    counts_oben, counts_unten = [], []
    for stack in engine.state.grid.all_stacks():
        hoehe = stack.height()
        if hoehe < 2:
            continue
        for level, bin_obj in enumerate(stack.bins):
            tiefe = hoehe - 1 - level          # 0 = ganz oben
            klasse = bin_obj.get_abc_class()
            if klasse in tiefen:
                tiefen[klasse].append(tiefe)
        counts_oben.append(stack.bins[-1].get_access_count())
        counts_unten.append(stack.bins[0].get_access_count())

    assert tiefen["A"] and tiefen["C"], "Zu wenige Bins fuer die Auswertung"
    mittel_a = sum(tiefen["A"]) / len(tiefen["A"])
    mittel_c = sum(tiefen["C"]) / len(tiefen["C"])

    if check == "abc":
        assert mittel_a < mittel_c, (
            f"A-Bins liegen im Mittel tiefer als C-Bins "
            f"(A={mittel_a:.2f}, C={mittel_c:.2f}) — die ABC-Ordnung ist "
            f"invertiert."
        )
    else:
        oben = sum(counts_oben) / len(counts_oben)
        unten = sum(counts_unten) / len(counts_unten)
        assert oben >= unten, (
            f"Oben liegende Bins haben im Mittel weniger Zugriffe als unten "
            f"liegende (oben={oben:.2f}, unten={unten:.2f})."
        )
