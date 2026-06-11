#!/usr/bin/env python3
"""
Hauptskript für die Durchführung aller Experimente.

Führt die drei Strategien aus:

1. AutoStore Baseline (LOFI + Random-Placement)
2. ABC Policy (ABC-Reordering + ABC-Placement)
3. Popularity Policy (Popularity-Reordering + Popularity-Placement)

Ergebnisse werden im results/ Ordner gespeichert.
"""

from typing import List

from config.simulation_config import SimulationConfig
from experiments.experiment_config import ExperimentConfig
from experiments.runner import ExperimentRunner
from experiments.exporter import ResultExporter


def create_base_config() -> SimulationConfig:
    """Erstellt Basis-Konfiguration für alle Experimente."""
    config = SimulationConfig()

    # Grid und Kapazität (literatur-inspiriertes Medium-Setup)
    # 20 x 30 Stacks, Höhe 8 → 4800 Slots, ca. 90% Füllgrad ≈ 4320 Bins
    config.grid_width = 20
    config.grid_depth = 30
    config.max_stack_height = 8
    config.bin_num = 4320

    # Roboter und Pickstations
    # 2 Pickstations, insgesamt 8 Roboter
    config.num_robots = 8
    config.num_pickstations = 2
    config.pickstation_capacity = 1

    # Simulation (ZE normiert, aber einheitlich über alle Strategien)
    config.simulation_time = 2000
    config.request_arrival_strategy = "Poisson"
    config.request_utilization = 0.6

    # Nachfrageverteilung: Zipf, um Hot/Cold-Bins zu erzeugen
    config.bin_request_prob_strategy = "zipf"
    config.zipf_parameter = 1.5

    # Metriken
    config.distribution_snapshot_interval = 100

    # Konvergenz-Detection (optional aktivieren, z.B. für RQ4)
    # config.stop_on_convergence = True
    # config.convergence_patience = 200

    return config


def create_experiments() -> List[ExperimentConfig]:
    """Erstellt alle Experiment-Konfigurationen."""
    return [
        ExperimentConfig(
            name="baseline",
            description="AutoStore Baseline: LOFI Reordering + Random Placement (CIRS)",
            reordering_strategy="LOFI",
            placement_strategy="RANDOM",
        ),
        ExperimentConfig(
            name="abc_policy",
            description="ABC Policy: ABC Reordering + ABC Zone Placement",
            reordering_strategy="ABC",
            placement_strategy="ABC",
        ),
        ExperimentConfig(
            name="popularity_policy",
            description="Popularity Policy: Popularity Reordering + Popularity Placement",
            reordering_strategy="POPULARITY",
            placement_strategy="POPULARITY",
        ),
        ExperimentConfig(
            name="RR+RR",
            description=(
                "Random Relocation + Random Return "
                "(CIRS/AutoStore Baseline ohne Ordered Return)"
            ),
            reordering_strategy="LOFI",  # Keine spezielle Reordering-Logik
            placement_strategy="RANDOM",  # Target-Bin zufällig zurücklagern
            return_blocking_bins=False,  # Blocking-Bins NICHT zurücklegen
            random_seeds=[42, 123, 456, 789, 1011],
        ),
        ExperimentConfig(
            name="LR+NR",
            description="Local Relocation + Nearest Return (structure-preserving)",
            reordering_strategy="LOFI",  # Keine spezielle Reordering-Logik
            placement_strategy="NEAREST",  # Target-Bin auf nächsten Stack
            return_blocking_bins=False,  # Blocking-Bins NICHT zurücklegen
            random_seeds=[42, 123, 456, 789, 1011],
        ),
    ]


def main():
    print("=" * 60)
    print("AutoStore Strategy Comparison Experiment")
    print("=" * 60)

    base_config = create_base_config()
    experiments = create_experiments()

    runner = ExperimentRunner(base_config)
    runner.run_all(experiments)

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    comparison = runner.compare_results()
    for strategy, metrics in comparison.items():
        avg_dig = metrics.get("average_digging_depth", {})
        thr = metrics.get("throughput", {})
        conv = metrics.get("convergence_time", {})

        print(f"\n{strategy}:")
        print(
            f"  Average Digging Depth: {avg_dig.get('mean', 0.0):.2f} "
            f"(±{avg_dig.get('std', 0.0):.2f})"
        )
        print(f"  Throughput: {thr.get('mean', 0.0):.2f}")
        ct = conv.get("mean", None)
        if ct is None:
            print("  Convergence Time: n/a")
        else:
            print(f"  Convergence Time: {ct:.0f}")

    print("\n" + "=" * 60)
    print("Exporting Results...")
    print("=" * 60)

    exporter = ResultExporter()
    exporter.export_all(runner, "strategy_comparison")

    print(f"Results exported to: {exporter.output_dir}")


if __name__ == "__main__":
    main()