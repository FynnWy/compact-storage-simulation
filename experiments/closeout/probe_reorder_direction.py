"""
Prueft die TATSAECHLICHE vertikale Ordnung nach dem Ordered Return.

Warum das nicht offensichtlich ist:

    `ReorderingSelector.reorder_blockers` dokumentiert
        "erste Bin in Rueckgabe = wird zuerst zurueckgelegt = landet unten"

    `RobotTask.reorder_blockers_for_return` sortiert `temp_storage` nach genau
    dieser Reihenfolge.

    `RobotTask.peek_last_relocation` liefert aber `temp_storage[-1]` — die
    Rueckgabe konsumiert also vom ENDE der Liste.

Ob daraus die dokumentierte Ordnung entsteht oder ihre Umkehrung, entscheidet
sich erst im Zusammenspiel. Dieses Skript simuliert die Rueckgabe-Schleife
und gibt die resultierende Stapelordnung von unten nach oben aus.
"""
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from config.simulation_config import SimulationConfig  # noqa: E402
from events.event_types import EventType  # noqa: E402
from requests_.request import Request  # noqa: E402
from simulation.robot_task import RobotTask  # noqa: E402
from strategies.reordering_blocking_bins_selector import ReorderingSelector  # noqa: E402
from state.bin import Bin  # noqa: E402


class FakeState:
    def __init__(self, bins):
        self._bins = {b.bin_id: b for b in bins}

    def get_bin_by_id(self, bin_id):
        return self._bins.get(bin_id)


def build_task(bins):
    task = RobotTask(Request(
        request_id=1, event_type=EventType.ARRIVAL, bin_id=999,
        t_arrival=0, t_earliest=0, t_latest=100,
    ))
    # Auslagerungsreihenfolge: bins[0] lag ganz oben und wurde zuerst
    # ausgelagert.
    for b in bins:
        task.remember_relocation(bin_id=b.bin_id, from_stack="S_1_1",
                                 buffer_stack="S_2_2")
    return task


def restore_order(task):
    """Simuliert die Rueckgabe-Schleife: peek_last_relocation + entfernen."""
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


def zeige(strategie, bins, beschriftung):
    config = SimulationConfig()
    config.reordering_strategy = strategie
    selector = ReorderingSelector(config)

    task = build_task(bins)
    state = FakeState(bins)
    task.reorder_blockers_for_return(state, selector)

    reihenfolge = restore_order(task)
    label = {b.bin_id: beschriftung(b) for b in bins}
    unten_nach_oben = [label[b] for b in reihenfolge]

    print(f"  {strategie:12s} Auslagerung(oben->unten): "
          f"{[label[b.bin_id] for b in bins]}")
    print(f"  {'':12s} Stapel danach (unten->oben): {unten_nach_oben}")
    return unten_nach_oben


if __name__ == "__main__":
    print("=== ABC: erwartet C unten, B mittig, A oben ===")
    abc_bins = []
    for i, klasse in enumerate(["A", "B", "C"]):
        b = Bin(10 + i, None, None, "stored")
        b.set_abc_class(klasse)
        abc_bins.append(b)
    ergebnis = zeige("ABC", abc_bins, lambda b: b.get_abc_class())
    print(f"  -> {'KORREKT' if ergebnis == ['C', 'B', 'A'] else 'FALSCH (erwartet [C, B, A])'}")

    print("\n=== POPULARITY: erwartet niedriger Count unten, hoher oben ===")
    pop_bins = []
    for i, count in enumerate([20, 5, 0]):
        b = Bin(20 + i, None, None, "stored")
        for _ in range(count):
            b.increment_access_count()
        pop_bins.append(b)
    ergebnis = zeige("POPULARITY", pop_bins, lambda b: b.get_access_count())
    print(f"  -> {'KORREKT' if ergebnis == [0, 5, 20] else 'FALSCH (erwartet [0, 5, 20])'}")

    print("\n=== LOFI: erwartet Originalordnung wiederhergestellt ===")
    lofi_bins = [Bin(30 + i, None, None, "stored") for i in range(3)]
    ergebnis = zeige("LOFI", lofi_bins, lambda b: b.bin_id)
    print(f"  Original war (unten->oben): [32, 31, 30]")
    print(f"  -> {'KORREKT' if ergebnis == [32, 31, 30] else 'FALSCH'}")
