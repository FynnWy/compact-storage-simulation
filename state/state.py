from typing import Set, Tuple, List, Optional

from utils.port_buffer_zone import calculate_buffer_zone

class State:
    def __init__(self, grid, bins, robots=None, future_request_queue=None, event_queue=None, pickstations=None, reservation_table=None, traffic_manager=None):
        self.grid = grid
        self.bins = bins
        self.robots = robots if robots is not None else []
        self.future_request_queue = future_request_queue
        self.event_queue = event_queue
        self.pickstations = pickstations if pickstations is not None else []
        self.reservation_table = reservation_table
        self.traffic_manager = traffic_manager  # NEU

        # Port- und Pufferzonen-Verwaltung
        # Port-Positionen können bereits im Grid hinterlegt sein
        self.port_positions: Set[Tuple[int, int]] = set(
            getattr(self.grid, "port_positions", set())
        )
        self.buffer_zone: Set[Tuple[int, int]] = set()

        self.t = 0

        self.initialized = False

    def advance_time(self):
        self.t += 1

    def set_time(self, t):
        self.t = t

    def mark_initialized(self):
        self.initialized = True

    def is_initialized(self):
        return self.initialized

    def initialize_port_zones(self, pickstations: List):
        """
        Initialisiert Port-Positionen und Pufferzonen EINMALIG beim Start.

        Args:
            pickstations: Liste der Pickstation-Objekte mit .position
        """
        # Port-Positionen aus Pickstations ableiten
        self.port_positions = {ps.position for ps in pickstations}

        # Pufferzone auf Basis der Port-Positionen berechnen
        self.buffer_zone = calculate_buffer_zone(
            port_positions=list(self.port_positions),
            grid_width=self.grid.width,
            grid_depth=self.grid.depth,
        )

        # Grid über aktuelle Port-Positionen informieren (für is_port_position)
        if hasattr(self.grid, "port_positions"):
            self.grid.port_positions = set(self.port_positions)

    def is_valid_storage_position(self, x: int, y: int) -> bool:
        """
        True, wenn (x, y) eine gültige Storage-Position ist UND
        NICHT in der Port-Pufferzone liegt.

        Verboten:
        - Port-Positionen selbst (Distanz 0)
        - Alle Positionen mit Manhattan-Distanz ≤ 1 zu einem Port
        """
        # Erst sicherstellen, dass es überhaupt eine Storage-Position ist
        if not self.grid.is_storage_position(x, y):
            return False

        # Pufferzonen-Check
        if (x, y) in getattr(self, "buffer_zone", set()):
            return False

        return True

    def get_bin_by_id(self, bin_id):
        for bin_obj in self.bins:
            if bin_obj.bin_id == bin_id:
                return bin_obj
        return None

    def get_robot(self, robot_id):
        """
        Gibt Robot anhand seiner ID zurück.

        Durchsucht die Liste aller Robots und liefert den Robot mit der
        angegebenen ID. Analog zu get_bin_by_id() und get_pickstation().

        Args:
            robot_id: ID des gesuchten Roboters (int)

        Returns:
            Robot | None: Der gefundene Robot oder None wenn nicht vorhanden
        """
        for robot in self.robots:
            if robot.robot_id == robot_id:
                return robot
        return None

    def get_stack(self, x, y):
        return self.grid.get_stack(x, y)

    def get_pickstation(self, station_id):
        """
        Gibt Pickstation anhand ihrer ID zurück.

        Args:
            station_id: ID der Pickstation (z.B. "PS_0")

        Returns:
            Pickstation | None
        """
        for ps in self.pickstations:
            if ps.station_id == station_id:
                return ps
        return None

    def reserve_pickstation(self, station_id: str, robot_id: int) -> bool:
        """
        Reserviert eine Pickstation für einen Roboter.

        Returns:
            True wenn erfolgreich, False wenn nicht verfügbar
        """
        pickstation = self.get_pickstation(station_id)
        if pickstation is None:
            return False
        return pickstation.reserve(robot_id)

    def release_pickstation(self, station_id: str):
        """Gibt Pickstation-Reservierung frei."""
        pickstation = self.get_pickstation(station_id)
        if pickstation is not None:
            pickstation.release_reservation()

    def get_available_pickstations(self) -> List["Pickstation"]:
        """Gibt alle nicht-reservierten Pickstations zurück."""
        return [ps for ps in self.pickstations if ps.is_available()]

    def find_pickstation_at(self, position: Tuple[int, int]) -> Optional["Pickstation"]:
        """Findet Pickstation an einer Position."""
        for ps in self.pickstations:
            if ps.position == position:
                return ps
        return None
    
    def get_nearest_pickstation(self, position):
        """
        Gibt nächstgelegene Pickstation basierend auf Manhattan-Distanz zurück.
        
        Args:
            position: (x, y) Ausgangsposition
        
        Returns:
            Pickstation | None
        """
        if not self.pickstations:
            return None
        
        def manhattan_distance(pos1, pos2):
            return abs(pos1[0] - pos2[0]) + abs(pos1[1] - pos2[1])
        
        return min(
            self.pickstations,
            key=lambda ps: manhattan_distance(position, ps.position)
        )
    
    def get_all_pickstations(self):
        """Gibt Liste aller Pickstations zurück."""
        return list(self.pickstations)