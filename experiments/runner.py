import copy
from typing import List, Dict, Any

import numpy as np

from config.simulation_config import SimulationConfig
from experiments.experiment_config import ExperimentConfig
from simulation.simulation_engine import SimulationEngine


class ExperimentRunner:
    """
    Führt mehrere Experimente aus und sammelt Ergebnisse.
    """

    def __init__(self, base_config: SimulationConfig):
        """
        Args:
            base_config: Basis-Konfiguration, die für alle Experimente gilt
                         (Grid-Größe, Anzahl Pickstations, etc.)
        """
        self.base_config = base_config
        self.results: List[dict] = []

    # ------------------------------------------------------------------ #
    # Öffentliche API
    # ------------------------------------------------------------------ #

    def run_experiment(self, experiment: ExperimentConfig) -> dict:
        """
        Führt ein Experiment mit allen konfigurierten Seeds aus.

        Args:
            experiment: ExperimentConfig mit Strategie-Einstellungen

        Returns:
            Dictionary mit aggregierten Ergebnissen über alle Seeds
        """
        seed_results: List[Dict[str, Any]] = []

        for seed in experiment.random_seeds:
            config = self._create_run_config(experiment, seed)
            engine = SimulationEngine(config)

            # Simulation ausführen
            while True:
                event = engine.step()
                if event is None:
                    break

            # Ergebnisse sammeln
            metrics_summary = engine.metrics.summary()
            distribution_ts = engine.metrics.get_distribution_timeseries()
            convergence_analysis = engine.metrics.get_convergence_analysis()
            final_distribution = engine.distribution_metrics.snapshot()

            result = {
                "seed": seed,
                "metrics_summary": metrics_summary,
                "distribution_snapshots": distribution_ts,
                "convergence_analysis": convergence_analysis,
                "final_distribution": final_distribution,
            }
            seed_results.append(result)

        # Aggregieren über Seeds
        aggregated = self._aggregate_results(experiment, seed_results)
        self.results.append(aggregated)
        return aggregated

    def run_all(self, experiments: List[ExperimentConfig]):
        """Führt alle Experimente sequentiell aus."""
        for experiment in experiments:
            print(f"Running experiment: {experiment.name}")
            self.run_experiment(experiment)
            print(f"Completed: {experiment.name}")

    def compare_results(self) -> dict:
        """
        Erstellt Vergleichstabelle aller Experimente.

        Returns:
            Dictionary mit Vergleichsmetriken für alle Strategien
        """
        comparison: Dict[str, Any] = {}
        for result in self.results:
            name = result["experiment"]["name"]
            comparison[name] = result["aggregated_metrics"]
        return comparison

    # ------------------------------------------------------------------ #
    # Interne Helfer
    # ------------------------------------------------------------------ #

    def _create_run_config(
        self,
        experiment: ExperimentConfig,
        seed: int,
    ) -> SimulationConfig:
        """Erstellt SimulationConfig für einen spezifischen Run."""
        config = copy.deepcopy(self.base_config)

        # Seed und Strategien setzen
        config.random_seed = seed
        config.reordering_strategy = experiment.reordering_strategy
        config.placement_strategy = experiment.placement_strategy

        # NEU: Blocking-Bin Rücklagerung
        config.return_blocking_bins = experiment.return_blocking_bins

        # Optionale Overrides
        if experiment.simulation_time is not None:
            config.simulation_time = experiment.simulation_time
        if experiment.bin_num is not None:
            config.bin_num = experiment.bin_num
        if experiment.num_robots is not None:
            config.num_robots = experiment.num_robots

        return config

    def _aggregate_results(
        self,
        experiment: ExperimentConfig,
        seed_results: List[Dict[str, Any]],
    ) -> dict:
        """
        Aggregiert Ergebnisse über mehrere Seeds.

        Berechnet Mean und Std für numerische Kernmetriken.
        """
        if not seed_results:
            return {
                "experiment": experiment.to_dict(),
                "num_runs": 0,
                "aggregated_metrics": {},
                "individual_runs": [],
            }

        # Sammle Metriken von allen Seeds
        all_digging_depths = [
            r["metrics_summary"].get("average_request_digging_depth", 0.0)
            for r in seed_results
        ]
        all_throughputs = [
            r["metrics_summary"].get("throughput", 0.0)
            for r in seed_results
        ]
        all_convergence_times = [
            r["convergence_analysis"].get("convergence_time")
            for r in seed_results
        ]

        # Filtere None für Statistik
        finite_conv_times = [t for t in all_convergence_times if t is not None]

        aggregated_metrics = {
            "average_digging_depth": {
                "mean": float(np.mean(all_digging_depths))
                if all_digging_depths
                else 0.0,
                "std": float(np.std(all_digging_depths))
                if all_digging_depths
                else 0.0,
            },
            "throughput": {
                "mean": float(np.mean(all_throughputs))
                if all_throughputs
                else 0.0,
                "std": float(np.std(all_throughputs))
                if all_throughputs
                else 0.0,
            },
            "convergence_time": {
                "mean": float(np.mean(finite_conv_times))
                if finite_conv_times
                else None,
                "values": all_convergence_times,
            },
        }

        return {
            "experiment": experiment.to_dict(),
            "num_runs": len(seed_results),
            "aggregated_metrics": aggregated_metrics,
            "individual_runs": seed_results,
        }