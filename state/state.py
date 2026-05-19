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

    def get_bin_by_id(self, bin_id):
        for bin_obj in self.bins:
            if bin_obj.bin_id == bin_id:
                return bin_obj
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