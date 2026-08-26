from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ExperimentConfig:
    """Konfiguration für ein einzelnes Experiment."""

    # Identifikation
    name: str  # z.B. "baseline", "abc_policy", "popularity_policy"
    description: str = ""

    # Strategie-Einstellungen
    #
    # reordering_strategy: Reihenfolge, in der ausgelagerte Blocking-Bins in
    #   ihren Originalstack zurückgelegt werden.
    #     "LOFI"        umgekehrte Auslagerungsreihenfolge (Baseline)
    #     "ABC"         C zuerst, dann B, dann A -> A liegt oben
    #     "POPULARITY"  access_count aufsteigend -> häufige Bins liegen oben
    #   Ohne Wirkung, wenn return_blocking_bins = False.
    reordering_strategy: str = "LOFI"

    # placement_strategy: Zielstack für die Rücklagerung der TARGET-Bin nach
    #   der Pickstation.
    #     "ORIGINAL"    zurück auf den Originalstack
    #     "RANDOM"      zufälliger Stack mit Kapazität (ohne Pufferzonenfilter)
    #     "NEAREST"     nächster zulässiger Stack RELATIV ZUM ORIGINALSTACK,
    #                   Tie-Break y dann x; der Originalstack gewinnt mit
    #                   Distanz 0 (verbindlich seit Phase 3B, Befund P3-04)
    #     "ABC"         Greedy-Score je ABC-Klasse
    #     "POPULARITY"  Score aus Distanz und erwarteter Grabtiefe, Hot/Cold
    placement_strategy: str = "RANDOM"

    # return_blocking_bins: Ob ausgelagerte Blocking-Bins nach dem Retrieval
    #   in ihren Originalstack zurückgelegt werden (Ordered Return).
    #     True   Blocker werden zurückgelegt (ABC+ABC, POPULARITY+POPULARITY)
    #     False  Blocker bleiben liegen, wo sie abgelegt wurden (RR+RR, LR+NR).
    #            reordering_strategy ist dann wirkungslos.
    return_blocking_bins: bool = True

    # Reproduzierbarkeit
    random_seeds: List[int] = field(
        default_factory=lambda: [42, 123, 456, 789, 1011]
    )

    # Simulationsparameter (optional, überschreibt base_config)
    simulation_time: Optional[int] = None
    bin_num: Optional[int] = None
    num_robots: Optional[int] = None

    def to_dict(self) -> dict:
        """Für JSON-Export."""
        return {
            "name": self.name,
            "description": self.description,
            "reordering_strategy": self.reordering_strategy,
            "placement_strategy": self.placement_strategy,
            "return_blocking_bins": self.return_blocking_bins,
            "random_seeds": list(self.random_seeds),
        }