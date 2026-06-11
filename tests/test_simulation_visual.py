# tests/test_simulation_visual.py
"""
Visueller Debugger - nicht für pytest, sondern manuelles Debugging.

Startet einen Flask-Server mit echten Simulations-Daten.
Öffne http://localhost:5051

Usage:
    python tests/test_simulation_visual.py
"""
import sys
from pathlib import Path

# Projekt-Root hinzufügen
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, jsonify, render_template
from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine

app = Flask(__name__, template_folder=str(project_root / "templates"))

# Globale Engine
engine = None
event_history = []


def init_engine():
    global engine, event_history

    config = SimulationConfig()
    config.grid_width = 5
    config.grid_depth = 5
    config.max_stack_height = 6
    config.bin_num = 50
    config.num_robots = 2
    config.simulation_time = 500
    config.random_seed = 42
    config.enable_visualization = False

    engine = SimulationEngine(config)
    event_history = []

    print(f"[INIT] Engine initialized with {config.num_robots} robots, "
          f"{config.bin_num} bins, {config.grid_width}x{config.grid_depth} grid")


def get_real_state():
    """Konvertiert echten State in View-Format."""
    if engine is None:
        return {}

    stacks = []
    for stack in engine.state.grid.all_stacks():
        x, y = stack.stack_id if isinstance(stack.stack_id, tuple) else (0, 0)
        bins = [{"id": b.bin_id, "abc_class": b.get_abc_class()} for b in stack.bins]
        stacks.append({
            "x": x,
            "y": y,
            "bins": bins,
            "locked_by": None
        })

    robots = []
    for robot in engine.state.robots:
        pos = robot.get_position() or (0, 0)
        task_info = None
        if robot.current_task:
            task = robot.current_task
            task_info = {
                "request_id": task.request_id,
                "target_bin": task.target_bin_id,
                "phase": task.phase,
                "blockers_remaining": len(task.temp_storage),
            }

        robots.append({
            "id": robot.robot_id,
            "pos": list(pos),
            "status": robot.status,
            "task": task_info,
            "path_remaining": robot.get_remaining_path_length(),
            "planned_path": robot.planned_path,
        })

    # Bins an Pickstation
    bins_at_pickstation = [
        {"id": b.bin_id}
        for b in engine.state.bins
        if b.get_status() == "at_pickstation"
    ]

    # Traffic-Stats
    traffic_stats = engine.state.traffic_manager.get_statistics()

    # Reservierungen (für Debugging)
    reservation_count = engine.state.reservation_table.get_reservation_count()

    return {
        "t": engine.state.t,
        "grid_width": engine.config.grid_width,
        "grid_depth": engine.config.grid_depth,
        "max_height": engine.config.max_stack_height,
        "grid": stacks,
        "robots": robots,
        "pickstation": bins_at_pickstation,
        "traffic_stats": traffic_stats,
        "reservation_count": reservation_count,
        "event_history": event_history[-10:],  # Letzte 10 Events
        "is_finished": engine.state.t >= engine.config.simulation_time,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/state')
def api_state():
    return jsonify({"state": get_real_state()})


@app.route('/api/next', methods=['POST'])
def api_next():
    global event_history

    event = engine.step()

    if event is not None:
        event_info = {
            "time": engine.state.t,
            "type": event.event_type.name if hasattr(event.event_type, 'name') else str(event.event_type),
        }
        event_history.append(event_info)

    state = get_real_state()
    state["last_event"] = str(event) if event else "None"
    return jsonify({"state": state})


@app.route('/api/step/<int:count>', methods=['POST'])
def api_step_multiple(count):
    """Führt mehrere Steps aus."""
    global event_history

    for _ in range(min(count, 100)):  # Max 100 auf einmal
        event = engine.step()
        if event is None:
            break

        event_info = {
            "time": engine.state.t,
            "type": event.event_type.name if hasattr(event.event_type, 'name') else str(event.event_type),
        }
        event_history.append(event_info)

    return jsonify({"state": get_real_state()})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    init_engine()
    return jsonify({"state": get_real_state()})


@app.route('/api/debug')
def api_debug():
    """Ausführliche Debug-Informationen."""
    if engine is None:
        return jsonify({"error": "No engine"})

    debug_info = {
        "time": engine.state.t,
        "processed_events": engine._processed_events,
        "robots": [],
        "active_queue": {
            "pending": len(engine.active_queue.pending),
            "waiting_tasks": len(engine.active_queue._waiting_tasks) if hasattr(engine.active_queue,
                                                                                '_waiting_tasks') else 0,
        },
        "traffic": engine.state.traffic_manager.get_statistics(),
        "metrics_summary": engine.metrics.summary(),
    }

    for robot in engine.state.robots:
        robot_info = {
            "id": robot.robot_id,
            "position": robot.get_position(),
            "status": robot.status,
            "path": robot.planned_path,
            "path_index": robot.path_index,
        }

        if robot.current_task:
            task = robot.current_task
            robot_info["task"] = {
                "request_id": task.request_id,
                "phase": task.phase,
                "target_stack": task.target_stack_id,
                "target_removed": task.target_removed,
                "pickstation_completed": task.pickstation_completed,
                "blockers": [r["bin_id"] for r in task.temp_storage],
            }

        debug_info["robots"].append(robot_info)

    return jsonify(debug_info)


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("🔍 Simulation Visual Debugger")
    print("=" * 60)
    print("\n📍 Öffne im Browser: http://localhost:5051")
    print("\n🎮 Steuerung:")
    print("  • 'Next' - Ein Event verarbeiten")
    print("  • 'Reset' - Simulation neu starten")
    print("  • '/api/debug' - Detaillierte Debug-Infos")
    print("\n⌨️  Zum Beenden: Strg+C")
    print("=" * 60 + "\n")

    init_engine()
    app.run(debug=True, port=5051, use_reloader=False)