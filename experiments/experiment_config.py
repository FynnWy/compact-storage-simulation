from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ExperimentConfig:
    """Konfiguration für ein einzelnes Experiment."""

    # Identifikation
    name: str  # z.B. "baseline", "abc_policy", "popularity_policy"
    description: str = ""

    # Strategie-Einstellungen
    reordering_strategy: str = "LOFI"      # "LOFI", "ABC", "POPULARITY"
    placement_strategy: str = "RANDOM"    # "ORIGINAL", "RANDOM", "ABC", "POPULARITY"

    # NEU: Ob Blocking-Bins zurückgelegt werden
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