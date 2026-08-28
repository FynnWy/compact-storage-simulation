class Robot:
    def __init__(self, robot_id, position=None):
        self.robot_id = robot_id
        self.position = position
        self.status = "idle"
        self.current_task = None

        # HARDENING (2026-08-19): Explizite Roboter→Bin-Verknüpfung.
        # Bisher existierte keine Möglichkeit festzustellen, WELCHER Roboter
        # eine `in_transit`-Bin trägt. Recovery-Pfade (Deadlock-Requeue)
        # konnten dadurch einen tragenden Roboter von seinem Task trennen und
        # die Bin im Nirgendwo zurücklassen.
        # Wird beim erfolgreichen Pickup gesetzt und beim erfolgreichen Drop
        # gelöscht – bewusst NICHT von `clear_task()` angefasst, weil die Bin
        # physisch weiterhin am Roboter hängt.
        self.carried_bin_id = None
        
        # NEU: Pfad-Verwaltung
        self.planned_path = []      # Liste von (x, y) Wegpunkten
        self.path_index = 0         # Aktueller Schritt im Pfad
        self.path_target_action = None  # Aktion, die nach Pfad ausgeführt wird

    def set_position(self, position):
        """
        Setzt Position des Roboters.

        ✅ WICHTIG: Position darf NIE auf None gesetzt werden, nachdem sie
        einmal initialisiert wurde!
        """
        if position is None and self.position is not None:
            raise RuntimeError(
                f"Cannot set position of robot {self.robot_id} to None - "
                f"robot already has position {self.position}"
            )
        self.position = position

    def get_position(self):
        return self.position

    def get_status(self):
        return self.status

    # ================================================================
    # Getragene Bin (Transit-Verknüpfung)
    # ================================================================

    def set_carried_bin(self, bin_id):
        """Merkt, welche Bin der Roboter physisch trägt."""
        self.carried_bin_id = bin_id

    def get_carried_bin(self):
        return self.carried_bin_id

    def clear_carried_bin(self):
        self.carried_bin_id = None

    def is_carrying_bin(self):
        """True, solange der Roboter eine Bin physisch transportiert."""
        return self.carried_bin_id is not None

    def set_status(self, status):
        self.status = status

    def assign_task(self, task):
        self.current_task = task
        self.status = "busy"

    def clear_task(self):
        self.current_task = None
        self.status = "idle"
        self.clear_path()  # NEU: Pfad auch löschen
    
    # ================================================================
    # NEU: Pfad-Verwaltung
    # ================================================================
    
    def set_path(self, path, target_action=None):
        """
        Setzt geplanten Pfad für den Roboter.
        
        Args:
            path: Liste von (x, y) Wegpunkten
            target_action: Aktion, die nach Erreichen des Ziels ausgeführt wird
        """
        self.planned_path = list(path) if path else []
        self.path_index = 0
        self.path_target_action = target_action
    
    def get_next_waypoint(self):
        """
        Gibt nächsten Wegpunkt zurück, ohne Index zu erhöhen.
        
        Returns:
            (x, y) | None
        """
        if self.path_index >= len(self.planned_path):
            return None
        return self.planned_path[self.path_index]
    
    def advance_to_next_waypoint(self):
        """
        Bewegt Roboter zum nächsten Wegpunkt und erhöht Index.
        
        Returns:
            (x, y): Neue Position
        
        Raises:
            RuntimeError: Wenn kein weiterer Wegpunkt vorhanden ist
        """
        waypoint = self.get_next_waypoint()
        if waypoint is None:
            raise RuntimeError(
                f"Cannot advance robot {self.robot_id}: no more waypoints in path"
            )
        
        self.position = waypoint
        self.path_index += 1
        return waypoint
    
    def has_reached_destination(self):
        """
        Prüft, ob Roboter das Ende seines Pfads erreicht hat.
        
        Returns:
            bool
        """
        return self.path_index >= len(self.planned_path)
    
    def clear_path(self):
        """Löscht aktuellen Pfad."""
        self.planned_path = []
        self.path_index = 0
        self.path_target_action = None
    
    def get_remaining_path_length(self):
        """Gibt Anzahl verbleibender Schritte zurück."""
        return max(0, len(self.planned_path) - self.path_index)

    def __repr__(self):
        task_id = None

        if self.current_task is not None:
            task_id = getattr(self.current_task, "request_id", self.current_task)

        return (
            f"Robot(id={self.robot_id}, "
            f"status={self.status}, "
            f"task={task_id}, "
            f"pos={self.position}, "
            f"path_remaining={self.get_remaining_path_length()})"
        )