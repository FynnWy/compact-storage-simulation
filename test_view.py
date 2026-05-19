"""
Kleiner Test für die View-Visualisierung.

Startet einen Flask-Server mit simulierten Events und Roboterbewegungen.
Öffne http://localhost:5051 und teste das View-Switching.

Usage:
    python test_view.py
"""

from flask import Flask, jsonify, render_template
import time

app = Flask(__name__)

# Simulierter State
current_step = 0
max_steps = 20


def get_test_state(step):
    """Generiert einen Test-State für verschiedene Simulationsschritte."""

    # Grid-Konfiguration
    grid_width = 5
    grid_depth = 5
    max_height = 6

    # Stacks mit wechselnden Höhen
    stacks = []
    for x in range(grid_width):
        for y in range(grid_depth):
            # Simuliere wachsende/schrumpfende Stacks
            height = ((x + y + step) % max_height) + 1
            bins = [{"id": f"B{x}_{y}_{i}"} for i in range(height)]

            stacks.append({
                "x": x,
                "y": y,
                "bins": bins,
                "locked_by": None
            })

    # Roboter mit Bewegungen
    robots = []

    # Roboter 0: Bewegt sich im Kreis
    robot0_positions = [
        (0, 0), (1, 0), (2, 0), (3, 0), (4, 0),
        (4, 1), (4, 2), (4, 3), (4, 4),
        (3, 4), (2, 4), (1, 4), (0, 4),
        (0, 3), (0, 2), (0, 1)
    ]
    robot0_pos = robot0_positions[step % len(robot0_positions)]
    robots.append({
        "id": 0,
        "pos": list(robot0_pos),
        "status": "busy" if step % 3 == 0 else "idle",
        "task": f"Task_{step}" if step % 3 == 0 else None
    })

    # Roboter 1: Bewegt sich diagonal
    robot1_x = step % grid_width
    robot1_y = step % grid_depth
    robots.append({
        "id": 1,
        "pos": [robot1_x, robot1_y],
        "status": "busy" if step % 2 == 0 else "idle",
        "task": f"Task_{step + 100}" if step % 2 == 0 else None
    })

    # Roboter 2: Statisch, wechselt nur Status
    robots.append({
        "id": 2,
        "pos": [2, 2],
        "status": "busy" if step % 4 < 2 else "idle",
        "task": f"Task_{step + 200}" if step % 4 < 2 else None
    })

    # Pickstation mit wechselndem Inhalt
    pickstation = []
    if step % 5 < 2:
        pickstation.append({"id": f"B_target_{step}"})

    # Event-Simulation
    event_types = [
        "ARRIVAL",
        "ROBOT_ACTION",
        "ROBOT_MOVE",
        "PICKSTATION_COMPLETE",
        "REQUEST_COMPLETE"
    ]

    event = {
        "type": event_types[step % len(event_types)],
        "time": step,
        "robot_id": step % 3,
        "action": "relocate" if step % 3 == 0 else "remove_target",
        "target_bin": f"B_{step % 10}"
    }

    # Active Queue mit wechselnden Requests
    pending_requests = []
    for i in range((step % 5) + 1):
        pending_requests.append({
            "request_id": f"REQ_{step}_{i}",
            "target_box_id": f"B_{i}"
        })

    return {
        "t": step,
        "grid_width": grid_width,
        "grid_depth": grid_depth,
        "max_height": max_height,
        "grid": stacks,
        "robots": robots,
        "pickstation": pickstation,
        "event": event,
        "active_queue": {
            "pending_count": len(pending_requests),
            "assigned_count": step % 3,
            "pending": pending_requests,
            "assigned": []
        },
        "history_index": step,
        "history_len": max_steps,
        "is_finished": step >= max_steps - 1,
        "status": "running" if step < max_steps - 1 else "finished"
    }


@app.route('/')
def index():
    """Render die Hauptseite."""
    return render_template('index.html')


@app.route('/api/state')
def api_state():
    """Gibt den aktuellen State zurück."""
    global current_step
    state = get_test_state(current_step)
    return jsonify({"state": state})


@app.route('/api/next', methods=['POST'])
def api_next():
    """Simuliert nächsten Event-Schritt."""
    global current_step

    if current_step < max_steps - 1:
        current_step += 1

    state = get_test_state(current_step)
    return jsonify({"state": state})


@app.route('/api/previous', methods=['POST'])
def api_previous():
    """Geht einen Schritt zurück."""
    global current_step

    if current_step > 0:
        current_step -= 1

    state = get_test_state(current_step)
    return jsonify({"state": state})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Reset zur Startposition."""
    global current_step
    current_step = 0

    state = get_test_state(current_step)
    return jsonify({"state": state})


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("View-Switching Test Server")
    print("=" * 60)
    print("\nÖffne im Browser: http://localhost:5051")
    print("\nFunktionen:")
    print("  • Klicke 'Next' um Simulation voranzutreiben")
    print("  • Roboter bewegen sich automatisch")
    print("  • Stack-Höhen ändern sich")
    print("  • Wechsle zwischen 'Side View' und 'Top-Down View'")
    print("  • Drücke Leertaste für Auto-Play")
    print("\nZum Beenden: Strg+C")
    print("=" * 60 + "\n")

    app.run(debug=True, port=5051, use_reloader=False)