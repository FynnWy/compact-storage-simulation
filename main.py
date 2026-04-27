# main.py

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from utils.visualization import plot_3d_storage_grid, plot_hot_item_heatmap


def print_state_summary(engine, label):
    print(f"\n--- {label} ---")
    print(f"Engine ready: {engine.is_ready()}")
    print(f"State initialized: {engine.state.is_initialized()}")
    print(f"Grid: {engine.state.grid.width} x {engine.state.grid.depth}")
    print(f"Bins: {len(engine.state.bins)}")
    print(f"Future requests: {len(engine.state.future_request_queue)}")

    sample_bin = engine.state.bins[0]
    print(f"Sample bin: {sample_bin}")


def main():
    config = SimulationConfig()

    # Beispiel: gleiche Ausgangslage für spätere Strategie-Vergleiche
    config.random_seed = 42
    config.init_strategy = "hot_items_top"   # oder "uniform"
    config.bin_request_prob_strategy = "Zipf"

    engine_top = SimulationEngine(config)
    print_state_summary(engine_top, "TOP ACCESS")

    # Zweite Strategie mit exakt denselben Parametern / Seed
    # Nur die Strategie selbst wird später unterschiedlich sein
    engine_side = SimulationEngine(config)
    print_state_summary(engine_side, "SIDE ACCESS")

    # einfacher Konsistenzcheck
    same_bin_count = len(engine_top.state.bins) == len(engine_side.state.bins)
    same_grid = (
        engine_top.state.grid.width == engine_side.state.grid.width and
        engine_top.state.grid.depth == engine_side.state.grid.depth
    )

    print("\n--- CONSISTENCY CHECK ---")
    print(f"Same bin count: {same_bin_count}")
    print(f"Same grid size: {same_grid}")

    # Visualizations
    print("\nStarting visualizer...")
    # 3D Ansicht Storage Grid
    plot_3d_storage_grid(engine_top, title="3D View: Hot Items Top Strategy")
    # Heatmaps
    plot_hot_item_heatmap(engine_top, title="Heatmap: Hot Items Top Strategy")
    plot_hot_item_heatmap(engine_side, title="Heatmap: Uniform Strategy")


if __name__ == "__main__":
    main()
