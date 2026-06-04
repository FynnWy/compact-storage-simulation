from dataclasses import dataclass, field
from typing import List


@dataclass
class ExperimentConfig:
    """Konfiguration für ein einzelnes Experiment."""

    # Identifikation
    name: str  # z.B. "baseline", "abc_policy", "popularity_policy"
    description: str = ""

    # Strategie-Einstellungen
    reordering_strategy: str = "LOFI"      # "LOFI", "ABC", "POPULARITY"
    placement_strategy: str = "RANDOM"    # "ORIGINAL", "RANDOM", "ABC", "POPULARITY"

    # Reproduzierbarkeit
    random_seeds: List[int] = field(
        default_factory=lambda: [42, 123, 456, 789, 1011]
    )

    # Simulationsparameter (optional, überschreibt base_config)
    simulation_time: int | None = None
    bin_num: int | None = None
    num_robots: int | None = None

    def to_dict(self) -> dict:
        """Für JSON-Export."""
        return {
            "name": self.name,
            "description": self.description,
            "reordering_strategy": self.reordering_strategy,
            "placement_strategy": self.placement_strategy,
            "random_seeds": list(self.random_seeds),
        }