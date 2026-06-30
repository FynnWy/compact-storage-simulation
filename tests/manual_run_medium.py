# manual_run_medium.py
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine

from experiments.experiment_config import ExperimentConfig


def build_medium_base_config() -> SimulationConfig:
    """
    Entspricht grob dem medium_config-Fixture:
    5x5 Grid, 60 Bins, 2 Roboter, 500 Zeiteinheiten, kein Highway.
    """
    config = SimulationConfig()
    config.grid_width = 20
    config.grid_depth = 10
    config.max_stack_height = 6

    config.bin_num = 1188
    config.num_robots = 2
    config.simulation_time = 500
    config.random_seed = 42

    config.enable_visualization = False
    config.enable_highway_system = False

    # Initialisierung & Requests wie in den Tests/Standard
    config.init_strategy = "random_distribution"
    config.bin_request_prob_strategy = "uniform"

    return config


def build_run_config(base: SimulationConfig, experiment: ExperimentConfig, seed: int) -> SimulationConfig:
    """
    Leicht vereinfachtes Pendant zu Runner._create_run_config.
    """
    import copy

    config = copy.deepcopy(base)
    config.random_seed = seed
    config.reordering_strategy = experiment.reordering_strategy
    config.placement_strategy = experiment.placement_strategy
    config.return_blocking_bins = experiment.return_blocking_bins

    if experiment.simulation_time is not None:
        config.simulation_time = experiment.simulation_time
    if experiment.bin_num is not None:
        config.bin_num = experiment.bin_num
    if experiment.num_robots is not None:
        config.num_robots = experiment.num_robots

    return config


def run_single_medium_experiment():
    # Beispiel-Experiment: LOFI + ORIGINAL, return_blocking_bins=True
    exp = ExperimentConfig(
        name="manual_medium_baseline",
        description="Medium config, LOFI/ORIGINAL, single seed",
        reordering_strategy="LOFI",
        placement_strategy="ORIGINAL",
        return_blocking_bins=True,
        random_seeds=[42],      # hier nur ein Seed
        simulation_time=500,    # überschreibt ggf. base_config
        bin_num=60,
        num_robots=2,
    )

    base_config = build_medium_base_config()
    seed = exp.random_seeds[0]
    config = build_run_config(base_config, exp, seed)

    print(f"[MANUAL] Starting run '{exp.name}' with seed={seed}")
    print(
        f"  grid={config.grid_width}x{config.grid_depth}, "
        f"bins={config.bin_num}, robots={config.num_robots}, "
        f"time={config.simulation_time}, "
        f"reordering={config.reordering_strategy}, "
        f"placement={config.placement_strategy}, "
        f"return_blocking_bins={config.return_blocking_bins}"
    )

    engine = SimulationEngine(config)

    # Manuelle Event-Schleife
    steps = 0
    while True:
        event = engine.step()
        steps += 1

        # Optional: etwas Logging
        if event is None:
            print(f"[MANUAL] Simulation ended after {steps} steps at t={engine.state.t}")
            break

        if steps % 50 == 0:
            summary = engine.metrics.summary()
            completed = summary.get("requests_completed", 0)
            print(f"[MANUAL] step={steps}, t={engine.state.t}, requests_completed={completed}")

        # Sicherheitsabbruch, falls irgendetwas schiefgeht
        if steps > 10_000:
            print("[MANUAL] Aborting after 10k steps (safety guard).")
            break

    summary = engine.metrics.summary()
    print("[MANUAL] Final metrics summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    run_single_medium_experiment()