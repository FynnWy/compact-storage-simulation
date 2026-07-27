import json
import threading
import webbrowser
import copy
from flask import Flask, render_template, jsonify, request
from events.event_types import EventType

class WebVisualizer:
    def __init__(self, engine, port=5000):
        self.engine = engine
        self.port = port
        self.app = Flask(__name__, 
                         template_folder='../templates', 
                         static_folder='../static')
        
        self.history = []
        self.history_index = -1
        self.is_finished = False
        self.last_event = None
        
        # Initial snapshot
        self._store_snapshot(None)
        
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template('index.html')

        @self.app.route('/api/state')
        def get_state():
            return jsonify(self._serialize_current_state())

        @self.app.route('/api/next', methods=['POST'])
        def next_step():
            if self.history_index < len(self.history) - 1:
                self.history_index += 1
                return jsonify(self._serialize_current_state())
            
            if self.is_finished:
                state = self._serialize_current_state()
                state["status"] = "finished"
                return jsonify(state)

            event = self._step_to_next_visible_event()
            if event is None:
                self.is_finished = True
                state = self._serialize_current_state()
                state["status"] = "finished"
                return jsonify(state)

            self._store_snapshot(event)
            return jsonify(self._serialize_current_state())

        @self.app.route('/api/previous', methods=['POST'])
        def previous_step():
            if self.history_index > 0:
                self._restore_snapshot(self.history_index - 1)

            return jsonify(self._serialize_current_state())

        @self.app.route('/api/reset', methods=['POST'])
        def reset():
            self._restore_snapshot(0)
            self.is_finished = False

            return jsonify(self._serialize_current_state())

    def _serialize_current_state(self):
        # Restore state from history for serialization
        snapshot = self.history[self.history_index]
        engine = snapshot["engine"]
        event = snapshot["event"]

        state = engine.state

        grid_data = []
        for (x, y), stack in state.grid.stacks.items():
            if stack is None:
                grid_data.append({
                    "x": x,
                    "y": y,
                    "bins": [],
                    "locked_by": None,
                })
                continue

            grid_data.append({
                "x": x,
                "y": y,
                "bins": [
                    {
                        "id": bin_obj.bin_id,
                        "status": bin_obj.status,
                    }
                    for bin_obj in stack.bins
                ],
                "locked_by": stack.locked_by,
            })

        robots_data = []
        for robot in state.robots:
            robots_data.append({
                "id": robot.robot_id,
                "pos": robot.position,
                "status": robot.status,
                "task": self._serialize_task(robot.current_task),
            })

        pickstation_bins = [
            {"id": bin_obj.bin_id}
            for bin_obj in state.bins
            if bin_obj.status == "at_pickstation"
        ]

        event_info = None
        if event is not None:
            event_info = {
                "type": event.event_type.value,
                "time": event.time,
                "robot_id": self._get_robot_id(event),
                "action": self._get_action_type(event),
                "target_bin": self._get_target_bin_id(event),
            }

        active_queue_info = self._serialize_active_queue(engine)

        return {
            "t": state.t,
            "grid_width": state.grid.width,
            "grid_depth": state.grid.depth,
            "max_height": engine.config.max_stack_height,
            "grid": grid_data,
            "robots": robots_data,
            "pickstation": pickstation_bins,
            "event": event_info,
            "active_queue": active_queue_info,
            "history_index": self.history_index,
            "history_len": len(self.history),
            "is_finished": self.is_finished,
        }

    def _serialize_active_queue(self, engine):
        active_queue = getattr(engine, "active_queue", None)

        if active_queue is None:
            return {
                "pending_count": 0,
                "assigned_count": 0,
                "pending": [],
                "assigned": [],
            }

        pending = [
            self._serialize_request(request)
            for request in list(getattr(active_queue, "pending", []))
        ]

        assigned = []
        for request_id, assignment in getattr(active_queue, "assigned", {}).items():
            request = assignment.get("request")
            robot = assignment.get("robot")

            assigned.append({
                "request_id": request_id,
                "target_bin": getattr(request, "target_box_id", None),
                "robot_id": getattr(robot, "robot_id", None),
            })

        return {
            "pending_count": len(pending),
            "assigned_count": len(assigned),
            "pending": pending,
            "assigned": assigned,
        }

    def _serialize_request(self, request):
        return {
            "request_id": getattr(request, "request_id", None),
            "target_bin": getattr(request, "target_box_id", None),
            "arrival_time": getattr(request, "arrival_time", None),
            "latest_time": getattr(request, "latest_time", None),
        }

    def _serialize_robot_task(self, task):
        """Serialisiert ein RobotTask-Objekt für JSON."""
        if task is None:
            return None

        return {
            "request_id": getattr(task, "request_id", None),
            "target_bin_id": getattr(task, "target_bin_id", None),
            "phase": getattr(task, "phase", None),
            "target_stack_id": task.target_stack_id,
            "target_removed": task.target_removed,
            "target_at_pickstation": task.target_at_pickstation,
            "pickstation_completed": task.pickstation_completed,
            "target_returned": task.target_returned,
            "blockers_count": len(task.temp_storage) if task.temp_storage else 0,
        }

    def _serialize_task(self, task):
        """Serialisiert einen RobotTask für JSON-Ausgabe."""
        if task is None:
            return None

        return {
            "request_id": task.request_id,
            "target_bin_id": task.target_bin_id,
            "phase": task.phase,
            "target_stack_id": task.target_stack_id,
            "target_at_pickstation": task.target_at_pickstation,
            "pickstation_completed": task.pickstation_completed,
            "target_returned": task.target_returned,
            "blockers_remaining": len(task.temp_storage),
        }

    def _restore_snapshot(self, index):
        if index < 0 or index >= len(self.history):
            return

        self.history_index = index
        self.engine = copy.deepcopy(self.history[index]["engine"])

        if self.history_index < len(self.history) - 1:
            self.is_finished = False

    def _store_snapshot(self, event):
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]

        self.history.append({
            "engine": copy.deepcopy(self.engine),
            "event": event,
        })
        self.history_index = len(self.history) - 1
        
        if len(self.history) > 200: # Web can handle a bit more history
            self.history.pop(0)
            self.history_index -= 1

    def _step_to_next_visible_event(self):
        latest_engine = copy.deepcopy(self.history[self.history_index]["engine"])

        while True:
            simulation_event = latest_engine.step()

            if simulation_event is None:
                return None

            if simulation_event.event_type != EventType.ARRIVAL:
                self.engine = latest_engine
                return simulation_event

    def _get_target_bin_id(self, event):
        if event is None: return None
        if event.event_type == EventType.ARRIVAL:
            return getattr(event.payload, "target_box_id", None)
        if isinstance(event.payload, dict):
            req = event.payload.get("request")
            act = event.payload.get("action")
            if req: return getattr(req, "target_box_id", None)
            if act: return act.get("bin_id")
        return None

    def _get_robot_id(self, event):
        if event is None or not isinstance(event.payload, dict): return None
        robot = event.payload.get("robot")
        return robot.robot_id if robot else None

    def _get_action_type(self, event):
        if event is None or not isinstance(event.payload, dict): return None
        action = event.payload.get("action")
        return action.get("type") if action else None

    def run(self):
        print(f"Starting web visualizer on http://localhost:{self.port}")
        # webbrowser.open(f"http://localhost:{self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=False, use_reloader=False)

def show_web_visualizer(engine, port=5050):
    visualizer = WebVisualizer(engine, port=port)
    visualizer.run()
    return visualizer
