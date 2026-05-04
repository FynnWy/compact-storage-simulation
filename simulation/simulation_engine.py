# simulation/simulation_engine.py

import math
import numpy as np

from config.init_strategy import initialize_bins
from requests_.active_queue import ActiveQueue
from requests_.request_generator import RequestGenerator
from simulation.action_executer import ActionExecutor
from simulation.constraint_manager import ConstraintManager
from simulation.event_builder import EventBuilder
from simulation.event_handler import EventHandler
from simulation.metrics import Metrics
from simulation.request_handler import RequestHandler
from simulation.scheduler import Scheduler
from state.bin import Bin
from state.event_queue import EventQueue
from state.request_queue import FutureRequestQueue
from state.robot import Robot
from state.state import State
from state.storage_grid import StorageGrid
from strategies.top_access_strategy import TopAccessStrategy
from events.event_types import EventType


class SimulationEngine:
    def __init__(self, config):
        self.config = config
        self.rng = np.random.default_rng(self.config.random_seed)

        self.state = None
        self.hot_bin_ids = []

        self._initialize_state()
        self._initialize_simulation_components()

    def _initialize_state(self):
        """
        Erstellt Grid, Bins, Roboter, Requests und initialisiert das Lager
        gemäß der gewählten Strategie.
        """
        grid = StorageGrid(self.config.grid_width, self.config.grid_depth)
        bins = self._create_bins(self.config.bin_num)
        robots = self._create_robots(self.config.num_robots)
        future_request_queue = self._create_future_request_queue()
        event_queue = EventQueue()

        self.hot_bin_ids = self._determine_hot_bin_ids()

        initialize_bins(
            grid=grid,
            bins=bins,
            init_strategy=self._resolve_init_strategy(),
            hot_bin_ids=self.hot_bin_ids,
            random_seed=self.config.random_seed,
            max_stack_height=self.config.max_stack_height,
        )

        self.state = State(
            grid=grid,
            bins=bins,
            robots=robots,
            future_request_queue=future_request_queue,
            event_queue=event_queue,
        )
        self.state.config = self.config
        self.state.mark_initialized()

    def _initialize_simulation_components(self):
        """
        Verdrahtet alle Komponenten für den eigentlichen DES-Lauf.
        """
        self.active_queue = ActiveQueue()
        self.event_builder = EventBuilder()
        self.request_handler = RequestHandler(
            state=self.state,
            event_builder=self.event_builder,
        )
        self.constraint_manager = ConstraintManager()
        self.executor = ActionExecutor()
        self.metrics = Metrics()

        strategy = TopAccessStrategy()

        self.scheduler = Scheduler(
            active_queue=self.active_queue,
            strategy=strategy,
            scheduler_strategy=self.config.scheduler_strategy,
        )

        self.event_handler = EventHandler(
            state=self.state,
            active_queue=self.active_queue,
            event_queue=self.state.event_queue,
            request_handler=self.request_handler,
            metrics=self.metrics,
            constraint_manager=self.constraint_manager,
            scheduler=self.scheduler,
            executor=self.executor,
            event_builder=self.event_builder,
        )

    def run(self, debug=False, max_events=10000):
        """
        Führt die Simulation bis simulation_time oder bis keine Events/Requests mehr existieren.

        debug=True gibt einen einfachen Event-Trace aus.
        max_events schützt vor Endlosschleifen.
        """
        self._validate_initial_state()

        self.request_handler.add_ready_requests_to_event_queue()

        processed_events = 0

        while processed_events < max_events:
            if self.state.t >= self.config.simulation_time:
                break

            if self.state.event_queue.is_empty():
                if self.state.future_request_queue.is_empty():
                    break

                self.state.advance_time()
                self.request_handler.add_ready_requests_to_event_queue()
                continue

            next_event = self.state.event_queue.peek()

            if next_event.time < self.state.t:
                raise RuntimeError(
                    f"Next event is in the past: event.time={next_event.time}, "
                    f"state.t={self.state.t}, event={next_event}"
                )

            if next_event.time > self.state.t:
                while self.state.t < next_event.time:
                    self.state.advance_time()
                    self.request_handler.add_ready_requests_to_event_queue()

                continue

            # Phase 1: Alle Nicht-Robot-Events der aktuellen Zeit verarbeiten
            did_process_non_robot_event = False

            while not self.state.event_queue.is_empty():
                next_event = self.state.event_queue.peek()

                if next_event.time != self.state.t:
                    break

                if next_event.event_type == EventType.ROBOT_ACTION:
                    break

                event = self.event_handler.get_next_event()
                processed_events += 1
                did_process_non_robot_event = True

                if debug and event is not None:
                    print(f"[EVENT] {event}")

                self._validate_runtime_state()

            # Phase 2: Nach REQUEST_COMPLETE und ARRIVAL genau jetzt schedulen
            if did_process_non_robot_event:
                self.event_handler.schedule_available_robots(self.state.t)
                continue

            # Phase 3: RobotAction der aktuellen Zeit verarbeiten
            event = self.event_handler.get_next_event()
            processed_events += 1

            if debug and event is not None:
                print(f"[EVENT] {event}")

            self._validate_runtime_state()

        if processed_events >= max_events:
            raise RuntimeError(
                f"Simulation stopped after max_events={max_events}. "
                f"Possible endless event loop."
            )

        return self.metrics.summary()

    def _validate_initial_state(self):
        """
        Prüft, ob der Startzustand konsistent ist.
        """
        self._validate_bin_uniqueness()
        self._validate_stack_capacities()
        self._validate_bin_metadata()

    def _validate_runtime_state(self):
        """
        Prüft während der Simulation grundlegende Invarianten.
        """
        self._validate_bin_uniqueness()
        self._validate_stack_capacities()

    def _validate_bin_uniqueness(self):
        bins_in_stacks = []

        for stack in self.state.grid.all_stacks():
            bins_in_stacks.extend(stack.bins)

        bins_at_pickstation = [
            bin_obj
            for bin_obj in self.state.bins
            if bin_obj.get_status() == "at_pickstation"
        ]

        visible_bins = bins_in_stacks + bins_at_pickstation
        visible_bin_ids = [bin_obj.bin_id for bin_obj in visible_bins]

        duplicate_bin_ids = [
            bin_id
            for bin_id in set(visible_bin_ids)
            if visible_bin_ids.count(bin_id) > 1
        ]

        if duplicate_bin_ids:
            raise RuntimeError(
                f"Invalid state: duplicate bin detected. "
                f"duplicate_bin_ids={duplicate_bin_ids}"
            )

        if len(visible_bin_ids) != len(self.state.bins):
            raise RuntimeError(
                f"Invalid state: expected {len(self.state.bins)} bins, "
                f"found {len(visible_bin_ids)} visible bins."
            )

    def _validate_stack_capacities(self):
        for stack in self.state.grid.all_stacks():
            if stack.height() > self.config.max_stack_height:
                raise RuntimeError(
                    f"Stack {stack.stack_id} exceeds max_stack_height: "
                    f"{stack.height()} > {self.config.max_stack_height}"
                )

    def _validate_bin_metadata(self):
        for stack in self.state.grid.all_stacks():
            stack_position = self._parse_stack_position(stack)

            for level, bin_obj in enumerate(stack.bins):
                if bin_obj.get_stack() != stack_position:
                    raise RuntimeError(
                        f"Invalid bin stack metadata for bin {bin_obj.bin_id}: "
                        f"{bin_obj.get_stack()} != {stack_position}"
                    )

                if bin_obj.get_level() != level:
                    raise RuntimeError(
                        f"Invalid bin level metadata for bin {bin_obj.bin_id}: "
                        f"{bin_obj.get_level()} != {level}"
                    )

    def _parse_stack_position(self, stack):
        stack_id = stack.stack_id

        if isinstance(stack_id, tuple):
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")

            if len(parts) == 3:
                return int(parts[1]), int(parts[2])

        return stack_id

    def _create_bins(self, bin_num):
        """
        Erstellt alle Bins ohne feste Platzierung.
        """
        bins = []
        for bin_id in range(bin_num):
            bin_obj = Bin(
                bin_id=bin_id,
                stack_id=None,
                level=None,
                status="not_locked",
            )
            bins.append(bin_obj)
        return bins

    def _create_robots(self, num_robots):
        """
        Erstellt alle Roboter.

        Roboter starten idle und ohne feste Position.
        Ein Roboter kann pro Zeiteinheit eine Aktion ausführen.
        """
        robots = []
        for robot_id in range(num_robots):
            robots.append(Robot(robot_id=robot_id, position=None))
        return robots

    def _create_future_request_queue(self):
        """
        Generiert alle Requests vorab und speichert sie in der Future-Queue.
        """
        request_generator = RequestGenerator(self.config)
        requests = request_generator.generate_requests()

        future_queue = FutureRequestQueue()
        for request in requests:
            future_queue.push(request)

        return future_queue

    def _determine_hot_bin_ids(self):
        """
        Ermittelt Hot Items aus der Request-Strategie.

        Wichtig:
        Diese IDs beeinflussen nicht die initiale Lagerposition.
        Hot Items werden über die Request-Wahrscheinlichkeit simuliert.
        """
        if self.config.bin_request_prob_strategy.lower() != "zipf":
            return []

        hot_fraction = 0.2
        hot_count = max(1, math.ceil(self.config.bin_num * hot_fraction))
        return list(range(hot_count))

    def _resolve_init_strategy(self):
        if self.config.init_strategy == "random_distribution":
            return "random_distribution"

        raise ValueError(f"Unknown init_strategy: {self.config.init_strategy}")

    def is_ready(self):
        return self.state is not None and self.state.is_initialized()