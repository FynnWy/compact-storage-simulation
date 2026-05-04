# main.py

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine


def print_state_summary(engine, label):
    print(f"\n--- {label} ---")
    print(f"Engine ready: {engine.is_ready()}")
    print(f"State initialized: {engine.state.is_initialized()}")
    print(f"Grid: {engine.state.grid.width} x {engine.state.grid.depth}")
    print(f"Max stack height: {engine.config.max_stack_height}")
    print(f"Bins: {len(engine.state.bins)}")
    print(f"Robots: {len(engine.state.robots)}")
    print(f"Future requests: {len(engine.state.future_request_queue)}")

    sample_bin = engine.state.bins[0]
    print(f"Sample bin: {sample_bin}")


def main():
    config = SimulationConfig()

    # Erweiterter, aber noch übersichtlicher Smoke-Test
    config.random_seed = 42

    config.grid_width = 4
    config.grid_depth = 4
    config.max_stack_height = 5
    config.bin_num = 35
    config.num_robots = 2
    config.simulation_time = 70

    config.init_strategy = "random_distribution"

    config.scheduler_strategy = "FIFO"
    config.request_arrival_strategy = "Poisson"
    config.request_utilization = 0.6
    config.bin_request_prob_strategy = "Uniform"

    engine = SimulationEngine(config)
    print_state_summary(engine, "EXTENDED SMOKE TEST")

    print("\n--- RUN SIMULATION ---")
    summary = engine.run(debug=True, max_events=3000)

    print("\n--- METRICS SUMMARY ---")
    for key, value in summary.items():
        if key in {"target_bin_removals", "time_series"}:
            print(f"{key}: {len(value)} entries")
        else:
            print(f"{key}: {value}")

    print("\n--- FINAL ROBOTS ---")
    for robot in engine.state.robots:
        print(robot)

    print("\n--- FINAL STACK HEIGHTS ---")
    total_bins_in_stacks = 0

    for stack in engine.state.grid.all_stacks():
        total_bins_in_stacks += stack.height()
        print(stack)

    bins_at_pickstation = [
        bin_obj
        for bin_obj in engine.state.bins
        if bin_obj.get_status() == "at_pickstation"
    ]

    print(f"\nTotal bins in stacks: {total_bins_in_stacks}")
    print(f"Bins at pickstation: {len(bins_at_pickstation)}")
    print(f"Total visible bins: {total_bins_in_stacks + len(bins_at_pickstation)}")


if __name__ == "__main__":
    main()
