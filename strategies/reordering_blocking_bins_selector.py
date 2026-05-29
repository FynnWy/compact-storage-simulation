# strategies/reordering_blocking_bins_selector.py

from typing import List

from state.bin import Bin


class ReorderingSelector:
    """
    Bestimmt die Reihenfolge, in der Blocking-Bins in den Original-Stack
    zurückgelegt werden (BBO: immer zurück in den Ursprungs-Stack).

    Die Strategie wird über config.reordering_strategy gesteuert:
    - "LOFI": Last-Out-First-In (Baseline, entspricht aktuellem Verhalten)
    - "ABC":  C-Bins zuerst, dann B, dann A (A landet oben)
    """

    def __init__(self, config):
        """
        Args:
            config:
                SimulationConfig mit Attribut reordering_strategy.
        """
        self.config = config

    def reorder_blockers(self, blockers: List[Bin]) -> List[Bin]:
        """
        Sortiert die Blocking-Bins für die Rücklagerung.

        Args:
            blockers:
                Liste der Blocking-Bins in der Reihenfolge, wie sie ausgelagert wurden
                (erste Bin in Liste = wurde zuerst ausgelagert = lag am weitesten oben).

        Returns:
            Liste der Blocking-Bins in der Reihenfolge, wie sie zurückgelegt werden sollen
            (erste Bin in Rückgabe = wird zuerst zurückgelegt = landet am weitesten unten).
        """
        strategy = getattr(self.config, "reordering_strategy", "LOFI")

        if strategy == "LOFI":
            return self._reorder_lofi(blockers)
        elif strategy == "ABC":
            return self._reorder_abc(blockers)
        else:
            raise ValueError(f"Unknown reordering strategy: {strategy}")

    def _reorder_lofi(self, blockers: List[Bin]) -> List[Bin]:
        """
        LOFI (Last-Out First-In): Umgekehrte Auslagerungsreihenfolge.

        Die zuletzt ausgelagerte Bin wird zuerst zurückgelegt.
        """
        return list(reversed(blockers))

    def _reorder_abc(self, blockers: List[Bin]) -> List[Bin]:
        """
        ABC-Reordering: Sortiert nach ABC-Klasse.
        C-Bins zuerst (landen unten), dann B, dann A (landet oben).

        Bei gleicher Klasse bleibt die ursprüngliche Reihenfolge durch
        die Stabilität von sorted() erhalten.
        """
        # Sortierpriorität: C=0, B=1, A=2 (niedrigste Priorität wird zuerst zurückgelegt)
        class_priority = {"C": 0, "B": 1, "A": 2, None: 0}

        def priority(bin_obj: Bin):
            abc_class = bin_obj.get_abc_class()
            return class_priority.get(abc_class, 0)

        return sorted(blockers, key=priority)