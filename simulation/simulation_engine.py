# simulation/simulation_engine.py

import math
import numpy as np

from config.init_strategy import initialize_bins
from requests_.active_queue import ActiveQueue
from requests_.request_generator import RequestGenerator
from simulation.action_cost_model import ActionCostModel
from simulation.action_executer import ActionExecutor
from simulation.constraint_manager import ConstraintManager
from simulation.event_builder import EventBuilder
from simulation.event_handler import EventHandler
from simulation.metrics import Metrics
from metrics.distribution_metrics import DistributionMetrics
from simulation.request_handler import RequestHandler
from simulation.scheduler import Scheduler
from state.bin import Bin
from state.event_queue import EventQueue
from state.request_queue import FutureRequestQueue
from state.robot import Robot
from state.state import State
from state.storage_grid import StorageGrid
from strategies.top_access_strategy import TopAccessStrategy
from strategies.relocation_selection import RelocationSelection
from strategies.target_bin_placement_selector import PlacementSelector
from strategies.reordering_blocking_bins_selector import ReorderingSelector
from events.event_types import EventType
from state.pickstation import Pickstation
from traffic.reservation_table import ReservationTable
from traffic.traffic_manager import TrafficManager
from traffic.highway_rules import HighwayRules


class SimulationEngine:
    def __init__(self, config):
        self.config = config
        self.rng = np.random.default_rng(self.config.random_seed)

        self.state = None
        self.hot_bin_ids = []
        self._is_started = False
        self._processed_events = 0

        # WP5/RQ3: Letzter Snapshot-Zeitpunkt
        self._last_distribution_snapshot_time = None

        self._initialize_state()
        self._initialize_simulation_components()

    def _initialize_state(self):
        """
        Erstellt Grid, Bins, Roboter, Requests, Pickstations und initialisiert das Lager
        gemäß der gewählten Strategie.
        """
        grid, pickstations = self._create_grid()
        bins = self._create_bins(self.config.bin_num)
        robots = self._create_robots(self.config.num_robots)
        future_request_queue = self._create_future_request_queue()
        event_queue = EventQueue()

        # ReservationTable erstellen
        reservation_table = ReservationTable(
            grid_width=self.config.grid_width,
            grid_depth=self.config.grid_depth,
            time_horizon=self.config.simulation_time,
        )

        # Highway-Regeln erstellen (falls aktiviert)
        highway_rules = None
        if self.config.enable_highway_system:
            highway_rules = HighwayRules(
                grid_width=self.config.grid_width,
                grid_depth=self.config.grid_depth,
                pattern=self.config.highway_pattern,
            )
            highway_rules.wrong_direction_penalty = self.config.highway_wrong_direction_penalty

        # TrafficManager mit Highway-Regeln erstellen
        traffic_manager = TrafficManager(
            grid=grid,
            reservation_table=reservation_table,
            highway_rules=highway_rules,
            port_positions={ps.position for ps in pickstations},
        )

        self.hot_bin_ids = self._determine_hot_bin_ids()

        initialize_bins(
            grid=grid,
            bins=bins,
            init_strategy=self._resolve_init_strategy(),
            hot_bin_ids=self.hot_bin_ids,
            random_seed=self.config.random_seed,
            max_stack_height=self.config.max_stack_height,
            # ABC-Thresholds aus Config an Initialisierung übergeben
            abc_threshold_a=self.config.abc_threshold_a,
            abc_threshold_b=self.config.abc_threshold_b,
        )

        self.state = State(
            grid=grid,
            bins=bins,
            robots=robots,
            future_request_queue=future_request_queue,
            event_queue=event_queue,
            pickstations=pickstations,
            reservation_table=reservation_table,
            traffic_manager=traffic_manager
        )
        self.state.config = self.config
        # Port-Pufferzonen initialisieren (einmalig beim Start)
        self.state.initialize_port_zones(pickstations)
        self.state.mark_initialized()

    def _initialize_simulation_components(self):
        """
        Verdrahtet alle Komponenten für den eigentlichen DES-Lauf.
        """
        self.active_queue = ActiveQueue()

        self.cost_model = ActionCostModel(
            config=self.config,
            rng=self.rng,
        )

        self.event_builder = EventBuilder(
            cost_model=self.cost_model,
            config=self.config,  # NEU: Config übergeben
        )

        self.request_handler = RequestHandler(
            state=self.state,
            event_builder=self.event_builder,
        )
        self.constraint_manager = ConstraintManager()
        self.executor = ActionExecutor(event_builder=self.event_builder)
        self.metrics = Metrics()

        # WP4: ConvergenceDetector an Config anpassen (falls vorhanden)
        if hasattr(self.config, "convergence_window_size"):
            self.metrics.convergence_detector.window_size = self.config.convergence_window_size
        if hasattr(self.config, "convergence_threshold"):
            self.metrics.convergence_detector.threshold = self.config.convergence_threshold

        # WP5/RQ3: DistributionMetrics für Verteilungs-Snapshots
        self.distribution_metrics = DistributionMetrics(
            state=self.state,
            config=self.config,
        )

        # Relocation-Selection mit Kostenmodell und ActiveQueue verdrahten
        relocation_selector = RelocationSelection(
            cost_model=self.cost_model,
            active_queue=self.active_queue,
        )

        # NEU: Strategie-Konfiguration aus SimulationConfig auslesen
        reordering_strategy = getattr(self.config, "reordering_strategy", "LOFI")
        placement_strategy = getattr(self.config, "placement_strategy", "ORIGINAL")

        # NEU: PlacementSelector für Target-Bin-Rücklagerung (CIRS / Baseline / Erweiterungen)
        placement_selector = PlacementSelector(
            config=self.config,
            rng=self.rng,
        )

        # NEU: ReorderingSelector für Blocking-Bin-Reordering (LOFI / ABC)
        reordering_selector = ReorderingSelector(
            config=self.config,
        )

        strategy = TopAccessStrategy(
            relocation_selector=relocation_selector,
            reordering_strategy=reordering_strategy,
            placement_strategy=placement_strategy,
            placement_selector=placement_selector,
            reordering_selector=reordering_selector,
        )

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

    def step(self):
        """
        Verarbeitet genau ein Simulationsevent und gibt dieses Event zurück.
        """
        if not self._is_started:
            self._validate_initial_state()
            self.request_handler.add_ready_requests_to_event_queue()
            self._is_started = True

        while True:
            # WP5/RQ3: Periodische Distribution-Snapshots & Positions-Tracking
            snapshot_interval = getattr(self.config, "distribution_snapshot_interval", None)
            if snapshot_interval is not None and snapshot_interval > 0:
                if (
                        self._last_distribution_snapshot_time is None
                        or (self.state.t - self._last_distribution_snapshot_time) >= snapshot_interval
                ):
                    snapshot = self.distribution_metrics.snapshot()
                    self.metrics.record_distribution_snapshot(snapshot)
                    # Positionsänderungen für RQ3/RQ4 tracken
                    self.metrics.record_position_state(self.state)
                    self._last_distribution_snapshot_time = self.state.t

            # Optionales Early-Stopping auf Basis von Konvergenz
            if getattr(self.config, "stop_on_convergence", False):
                if self.metrics.convergence_detector.is_converged():
                    conv_time = self.metrics.convergence_detector.get_convergence_time()
                    patience = getattr(self.config, "convergence_patience", 0)
                    if conv_time is not None and self.state.t >= conv_time + patience:
                        # Simulation vorzeitig beenden
                        return None

            if self.state.t >= self.config.simulation_time:
                return None

            if self.state.event_queue.is_empty():
                if self.state.future_request_queue.is_empty():
                    return None

                self.state.advance_time()
                self.request_handler.add_ready_requests_to_event_queue()

                # Periodisches Cleanup der ReservationTable (alle 10 ZE)
                if self.state.t % 10 == 0:
                    self.state.reservation_table.cleanup_before(self.state.t)

                    # NEU: Periodisches Deadlock-Check (alle 10 ZE)
                    victim_id = self.state.traffic_manager.check_and_resolve_deadlock(
                        robots=self.state.robots,
                        scheduler=self.scheduler,
                        current_time=self.state.t,
                    )

                    if victim_id is not None:
                        # Roboter neu planen lassen
                        for robot in self.state.robots:
                            if robot.robot_id == victim_id:
                                self.state.traffic_manager.release_robot_reservations(robot)
                                # HARDENING (2026-08-19): Trägt der Roboter
                                # eine Bin, darf er NICHT von seinem Task
                                # getrennt werden – die Bin wäre sonst weder
                                # in einem Stack noch einem Task zugeordnet.
                                # (Gleiche Invariante wie in
                                # `EventHandler._resolve_move_deadlock`.)
                                if robot.is_carrying_bin():
                                    break
                                # Task in Warteschlange
                                if robot.current_task is not None:
                                    self.active_queue.add_waiting_task(robot.current_task)
                                    robot.clear_task()
                                break

                continue

            next_event = self.state.event_queue.peek()

            if next_event.time < self.state.t:
                raise RuntimeError(
                    f"Next event is in the past: event.time={next_event.time}, "
                    f"state.t={self.state.t}, event={next_event}"
                )

            if next_event.time > self.state.t:
                # ZEIT VORWÄRTS: aber nicht stumpf bis next_event.time,
                # sondern so lange, bis ein Event mit time <= state.t existiert.
                target_time = next_event.time

                while self.state.t < target_time:
                    self.state.advance_time()
                    self.request_handler.add_ready_requests_to_event_queue()

                    # NEU: Auch hier Cleanup, falls Zeit vorwärts springt
                    if self.state.t % 10 == 0:
                        self.state.reservation_table.cleanup_before(self.state.t)

                    # Nach neuen Arrivals kann jetzt ein früheres Event fällig sein
                    current_next = self.state.event_queue.peek()
                    if current_next is not None and current_next.time <= self.state.t:
                        # Wir haben jetzt ein Event, das "dran" ist
                        break

                # Zurück zum Schleifenanfang: next_event neu bestimmen
                continue

            event = self.event_handler.get_next_event()
            self._processed_events += 1

            if event is not None:
                self._validate_runtime_state()

                if event.event_type in {
                    EventType.ARRIVAL,
                    EventType.REQUEST_COMPLETE,
                    EventType.PICKSTATION_COMPLETE,
                }:
                    self.event_handler.schedule_available_robots(self.state.t)

                if getattr(self.config, "enable_step_debug", False):
                    # ------------------------------------------------------
                    # NEU: Debug-Logging nach jedem verarbeiteten Event
                    # ------------------------------------------------------
                    gw, gd = self.state.grid.width, self.state.grid.depth

                    # Positionen und mögliche Kollisionen ermitteln
                    pos_to_robot = {}
                    collisions = []
                    illegal_positions = []

                    for r in self.state.robots:
                        pos = r.get_position()
                        if pos is None:
                            continue

                        x, y = pos
                        if not (0 <= x < gw and 0 <= y < gd):
                            illegal_positions.append((r.robot_id, pos))

                        if pos in pos_to_robot:
                            collisions.append((pos, pos_to_robot[pos], r.robot_id))
                        else:
                            pos_to_robot[pos] = r.robot_id

                    # Basiszustand loggen
                    print(
                        f"[STATE][STEP] t={self.state.t} "
                        f"event_type={getattr(event.event_type, 'name', event.event_type)} "
                        f"robots={{"
                        + ", ".join(
                            f"{r.robot_id}: {r.get_position()}"
                            for r in self.state.robots
                        )
                        + "}"
                    )

                    # Kollisionen explizit markieren
                    for pos, r0, r1 in collisions:
                        print(
                            f"[COLLISION][STEP] t={self.state.t} pos={pos} "
                            f"robots={r0},{r1} "
                            f"after_event={getattr(event.event_type, 'name', event.event_type)}"
                        )

                    # Out-of-bounds Positionen explizit markieren
                    for rid, pos in illegal_positions:
                        print(
                            f"[ILLEGAL_POS][STEP] t={self.state.t} robot={rid} "
                            f"pos={pos} (grid={gw}x{gd}) "
                            f"after_event={getattr(event.event_type, 'name', event.event_type)}"
                        )

            return event

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

        # NEU: Bins die gerade vom Roboter getragen werden (in_transit)
        bins_in_transit = [
            bin_obj
            for bin_obj in self.state.bins
            if getattr(bin_obj, "in_transit", False)
               and bin_obj.get_status() != "at_pickstation"  # Nicht doppelt zählen
               and bin_obj not in bins_in_stacks  # Nicht doppelt zählen
        ]

        visible_bins = bins_in_stacks + bins_at_pickstation + bins_in_transit
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
            # Debug-Info für fehlende Bins
            all_bin_ids = {b.bin_id for b in self.state.bins}
            visible_ids = set(visible_bin_ids)
            missing_ids = all_bin_ids - visible_ids

            raise RuntimeError(
                f"Invalid state: expected {len(self.state.bins)} bins, "
                f"found {len(visible_bin_ids)} visible bins. "
                f"Missing bin_ids: {missing_ids}"
            )
    """
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
    """

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

    """
    def _create_robots(self, num_robots):
        """"""
        Erstellt alle Roboter.

        Roboter starten idle und mit zufälliger Startposition
        innerhalb des Grids.

        Hintergrund:
        - Realistische Initialisierung: Roboter stehen irgendwo im Lager.
        - Alle Bewegungen erfolgen danach über Pathfinder/ReservationTable,
          es gibt keine Teleports mehr.
        """"""
        robots = []

        for robot_id in range(num_robots):
            # Zufällige Startposition im Grid
            x = int(self.rng.integers(0, self.config.grid_width))
            y = int(self.rng.integers(0, self.config.grid_depth))

            start_pos = (x, y)
            robots.append(Robot(robot_id=robot_id, position=start_pos))

        return robots
        """

    def _create_robots(self, num_robots):
        """
        Erstellt alle Roboter.

        Roboter starten idle und mit zufälliger Startposition
        innerhalb des Grids.

        Hintergrund:
        - Realistische Initialisierung: Roboter stehen irgendwo im Lager.
        - Alle Bewegungen erfolgen danach über Pathfinder/ReservationTable,
          es gibt keine Teleports mehr.
        - WICHTIG: Jeder Roboter muss eine eindeutige Startposition haben.
        """
        robots = []
        occupied_positions = set()

        for robot_id in range(num_robots):
            # Zufällige Startposition im Grid, die noch nicht belegt ist
            max_attempts = self.config.grid_width * self.config.grid_depth
            attempts = 0

            while attempts < max_attempts:
                x = int(self.rng.integers(0, self.config.grid_width))
                y = int(self.rng.integers(0, self.config.grid_depth))
                start_pos = (x, y)

                if start_pos not in occupied_positions:
                    occupied_positions.add(start_pos)
                    break

                attempts += 1
            else:
                raise RuntimeError(
                    f"Cannot find unique start position for robot {robot_id}. "
                    f"Grid size ({self.config.grid_width}x{self.config.grid_depth}) "
                    f"may be too small for {num_robots} robots."
                )

            robots.append(Robot(robot_id=robot_id, position=start_pos))

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

    def _create_grid(self):
        """
        Erstellt StorageGrid und Pickstations inkl. Port-Integration.

        - Berechnet Pickstation-Positionen im Grid
        - Extrahiert Port-Positionen
        - Übergibt Port-Positionen an StorageGrid
        """
        pickstations = self._create_pickstations()
        port_positions = {ps.position for ps in pickstations}

        grid = StorageGrid(
            self.config.grid_width,
            self.config.grid_depth,
            port_positions=port_positions,
        )
        return grid, pickstations

    def _create_pickstations(self):
        """
        Erstellt alle Pickstations basierend auf Config.

        Neue Platzierung:
        - Pickstations liegen IM Grid
        - Genau 2 Pickstations (oder 1, falls so konfiguriert)
        - Gegenüberliegend
        - In der Mitte der längeren Seite
        - Am Rand (erste/letzte Zeile oder Spalte)

        Returns:
            list[Pickstation]
        """
        pickstations = []

        num_stations = self.config.num_pickstations
        capacity = self.config.pickstation_capacity
        width = self.config.grid_width
        depth = self.config.grid_depth

        if num_stations not in (1, 2):
            raise ValueError(
                f"Unsupported number of pickstations: {num_stations}. "
                f"This configuration expects 1 or 2 pickstations."
            )

        if depth >= width:
            # Längere Seite ist depth → Ports links/rechts
            mid_y = depth // 2
            port_1_position = (0, mid_y)              # Linker Rand
            port_2_position = (width - 1, mid_y)      # Rechter Rand
        else:
            # Längere Seite ist width → Ports oben/unten
            mid_x = width // 2
            port_1_position = (mid_x, 0)              # Oberer Rand
            port_2_position = (mid_x, depth - 1)      # Unterer Rand

        positions = []
        if num_stations >= 1:
            positions.append(port_1_position)
        if num_stations == 2:
            positions.append(port_2_position)

        for i, position in enumerate(positions):
            station_id = f"PS_{i}"
            pickstation = Pickstation(
                station_id=station_id,
                position=position,
                capacity=capacity,
            )
            pickstations.append(pickstation)

        return pickstations