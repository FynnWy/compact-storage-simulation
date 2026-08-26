# main.py

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from utils.visualization_2D import show_storage_side_view
from utils.web_visualizer import show_web_visualizer


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


def print_metrics_summary(summary):
    print("\n--- METRICS SUMMARY ---")
    for key, value in summary.items():
        if key in {"target_bin_removals", "time_series"}:
            print(f"{key}: {len(value)} entries")
        else:
            print(f"{key}: {value}")


def print_final_state(engine):
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


def run_without_visualization(engine):
    print("\n--- RUN SIMULATION ---")

    # Simulation Schritt für Schritt ausführen
    max_events = 30000
    event_count = 0

    while event_count < max_events:
        event = engine.step()
        if event is None:
            break
        event_count += 1

    # Metriken am Ende abrufen
    summary = engine.metrics.summary()

    print_metrics_summary(summary)
    print_final_state(engine)


def run_with_visualization(engine):
    print("\n--- RUN INTERACTIVE VISUALIZATION ---")
    
    if engine.config.visualization_type == "web":
        print("Web visualizer starting...")
        show_web_visualizer(engine, port=5050)
    else:
        print("Use the 'Next visible event' button to step through the simulation.")
        print("Use the 'Previous' button to jump back one visible event.")
        print("ARRIVAL events are skipped in the visualization because they do not directly change the warehouse layout.")

        visualizer = show_storage_side_view(engine)
        engine = visualizer.get_engine()

    print("\n--- VISUALIZATION CLOSED ---")
    # Bei Web-Visualisierung kommen wir hier erst hin, wenn der Server beendet wird
    # (was momentan durch Strg+C passiert).
    print_metrics_summary(engine.metrics.summary())
    print_final_state(engine)


def main():
    config = SimulationConfig()

    # Erweiterter, aber noch übersichtlicher Smoke-Test
    config.random_seed = 42

    config.grid_width = 7
    config.grid_depth = 7
    config.max_stack_height = 6
    config.bin_num = 200
    config.num_robots = 4
    config.simulation_time = 200

    config.init_strategy = "random_distribution"

    config.scheduler_strategy = "FIFO"
    config.request_arrival_strategy = "Poisson"
    config.request_utilization = 2
    config.bin_request_prob_strategy = "Uniform"

    # Umschalten:
    # False = normale Simulation ohne Visualisierung
    # True = interaktive 2D-Visualisierung
    config.enable_visualization = True

    engine = SimulationEngine(config)
    print_state_summary(engine, "EXTENDED SMOKE TEST")

    if config.enable_visualization:
        run_with_visualization(engine)
    else:
        run_without_visualization(engine)


if __name__ == "__main__":
    main()
