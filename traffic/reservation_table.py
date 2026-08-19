# traffic/test_reservation_table.py

class ReservationTable:
    """
    Space-Time Reservierungstabelle für Multi-Agent-Koordination.

    Verwaltet Reservierungen im Format (x, y, t) → robot_id.

    Invarianten:
    - INV-R1: Keine zwei Roboter auf derselben Zelle zur selben Zeit
    - INV-R2: Keine Head-on Collisions (A→B und B→A gleichzeitig)
    - INV-R3: Keine Swap Collisions (A und B tauschen Positionen gleichzeitig)

    Wichtig:
    - Diese Klasse verändert keinen State
    - Sie verwaltet nur Reservierungen
    - Tatsächliche Bewegung wird vom EventHandler durchgeführt
    """

    def __init__(self, grid_width, grid_depth, time_horizon=100):
        """
        Args:
            grid_width: Breite des Grids
            grid_depth: Tiefe des Grids
            time_horizon: Wie weit in die Zukunft reserviert werden kann
        """
        self.grid_width = grid_width
        self.grid_depth = grid_depth
        self.time_horizon = time_horizon

        # (x, y, t) → robot_id
        self._reservations = {}

        # robot_id → [(x, y, t), ...]
        self._robot_reservations = {}

    # ================================================================
    # Einzelne Zell-Reservierung
    # ================================================================

    def reserve(self, robot_id, x, y, t):
        """
        Reserviert eine einzelne Zelle für einen Roboter.

        Args:
            robot_id: ID des Roboters
            x, y: Grid-Position
            t: Zeitpunkt

        Returns:
            bool: True wenn Reservierung erfolgreich, False bei Konflikt
        """
        if not self._is_valid_position(x, y):
            return False

        key = (x, y, t)

        # Prüfen ob bereits reserviert (durch anderen Roboter)
        if key in self._reservations:
            existing_robot = self._reservations[key]
            if existing_robot != robot_id:
                return False  # Konflikt
            # Bereits durch denselben Roboter reserviert - idempotent
            return True

        # Reservierung eintragen
        self._reservations[key] = robot_id

        if robot_id not in self._robot_reservations:
            self._robot_reservations[robot_id] = []
        self._robot_reservations[robot_id].append(key)

        return True

    def is_free(self, x, y, t, exclude_robot=None):
        """
        Prüft ob eine Zelle zu einem Zeitpunkt frei ist.

        Args:
            x, y: Grid-Position
            t: Zeitpunkt
            exclude_robot: Optional - Roboter-ID, dessen Reservierungen ignoriert werden

        Returns:
            bool: True wenn frei
        """
        key = (x, y, t)

        if key not in self._reservations:
            return True

        blocking_robot = self._reservations[key]

        if exclude_robot is not None and blocking_robot == exclude_robot:
            return True

        return False

    def get_blocking_robot(self, x, y, t):
        """
        Gibt ID des Roboters zurück, der eine Zelle blockiert.

        Returns:
            robot_id | None
        """
        return self._reservations.get((x, y, t))

    def get_blocked_at(self, t):
        """
        Gibt alle Positionen zurück, die zur Zeit t blockiert sind.

        Returns:
            set[(x, y)]
        """
        return {
            (x, y)
            for (x, y, ts), _robot in self._reservations.items()
            if ts == t
        }

    # ================================================================
    # Pfad-Reservierung
    # ================================================================

    def reserve_path(self, robot_id, path, start_time):
        """
        Reserviert einen kompletten Pfad für einen Roboter.

        Bei Konflikt wird kein Teil des Pfads reserviert (atomare Operation).

        Args:
            robot_id: ID des Roboters
            path: Liste von (x, y) Wegpunkten
            start_time: Startzeitpunkt

        Returns:
            (success: bool, conflict_info: dict | None)

            conflict_info enthält bei Fehler:
            {
                "position": (x, y),
                "time": t,
                "blocking_robot": robot_id
            }
        """
        if not path:
            return True, None

        # Phase 1: Prüfen ob gesamter Pfad reservierbar ist
        reservations_to_make = []

        for i, (x, y) in enumerate(path):
            t = start_time + i

            # Prüfen ob Zelle frei ist
            if not self.is_free(x, y, t, exclude_robot=robot_id):
                blocking_robot = self.get_blocking_robot(x, y, t)
                return False, {
                    "position": (x, y),
                    "time": t,
                    "blocking_robot": blocking_robot,
                }

            # Prüfen auf Head-on Collision
            if i > 0:
                prev_x, prev_y = path[i - 1]
                if self._check_head_on_collision(
                        robot_id, (prev_x, prev_y), (x, y), start_time + i - 1
                ):
                    blocking_robot = self.get_blocking_robot(x, y, start_time + i - 1)
                    return False, {
                        "position": (x, y),
                        "time": t,
                        "blocking_robot": blocking_robot,
                        "collision_type": "head_on",
                    }

            reservations_to_make.append((x, y, t))

        # Phase 2: Alle Reservierungen durchführen
        for x, y, t in reservations_to_make:
            self.reserve(robot_id, x, y, t)

        return True, None

    def _check_head_on_collision(self, robot_id, from_pos, to_pos, t):
        """
        Prüft ob ein anderer Roboter gleichzeitig in die entgegengesetzte
        Richtung fährt.

        Szenario:
        - Roboter A: (0,0) → (1,0) zur Zeit t
        - Roboter B: (1,0) → (0,0) zur Zeit t
        => Head-on Collision

        Args:
            robot_id: ID des bewegenden Roboters
            from_pos: (x, y) Startposition
            to_pos: (x, y) Zielposition
            t: Zeitpunkt

        Returns:
            bool: True wenn Head-on Collision erkannt
        """
        # Prüfen ob ein anderer Roboter zur Zeit t auf to_pos ist
        other_robot = self.get_blocking_robot(*to_pos, t)

        if other_robot is None or other_robot == robot_id:
            return False

        # Prüfen ob dieser andere Roboter zur Zeit t+1 auf from_pos sein wird
        next_pos_of_other = self.get_blocking_robot(*from_pos, t + 1)

        return next_pos_of_other == other_robot

    # ================================================================
    # Freigabe
    # ================================================================

    def release(self, robot_id, x, y, t):
        """
        Gibt eine einzelne Reservierung frei.

        Args:
            robot_id: ID des Roboters
            x, y: Grid-Position
            t: Zeitpunkt
        """
        key = (x, y, t)

        if key in self._reservations and self._reservations[key] == robot_id:
            del self._reservations[key]

            if robot_id in self._robot_reservations:
                try:
                    self._robot_reservations[robot_id].remove(key)
                except ValueError:
                    pass

    def release_all(self, robot_id):
        """
        Gibt alle Reservierungen eines Roboters frei.

        Args:
            robot_id: ID des Roboters
        """
        if robot_id not in self._robot_reservations:
            return

        # Kopie erstellen, da wir während Iteration löschen
        reservations = list(self._robot_reservations[robot_id])

        for key in reservations:
            if self._reservations.get(key) == robot_id:
                del self._reservations[key]

        self._robot_reservations[robot_id] = []

    def cleanup_before(self, current_time):
        """
        Entfernt alle Reservierungen vor einem bestimmten Zeitpunkt.

        Wird periodisch aufgerufen um Speicher freizugeben.

        Args:
            current_time: Zeitpunkt - alles davor wird gelöscht
        """
        keys_to_remove = [
            key for key in self._reservations
            if key[2] < current_time
        ]

        for key in keys_to_remove:
            robot_id = self._reservations[key]
            del self._reservations[key]

            if robot_id in self._robot_reservations:
                try:
                    self._robot_reservations[robot_id].remove(key)
                except ValueError:
                    pass

    # ================================================================
    # Hilfsfunktionen
    # ================================================================

    def _is_valid_position(self, x, y):
        """
        Prüft ob Position innerhalb des Grids liegt.

        Erlaubt auch Positionen außerhalb (z.B. Pickstations bei x=-1).
        """
        # Großzügige Prüfung - erlaubt Pickstations außerhalb
        return -5 <= x < self.grid_width + 5 and -5 <= y < self.grid_depth + 5

    def get_reservations_for_robot(self, robot_id):
        """
        Gibt alle Reservierungen eines Roboters zurück.

        Returns:
            list[(x, y, t)]
        """
        return list(self._robot_reservations.get(robot_id, []))

    def get_reservation_count(self):
        """Gibt Anzahl aktiver Reservierungen zurück."""
        return len(self._reservations)

    def get_robot_count(self):
        """Gibt Anzahl Roboter mit aktiven Reservierungen zurück."""
        return len([r for r in self._robot_reservations.values() if r])

    # ================================================================
    # Debugging
    # ================================================================

    def __repr__(self):
        return (
            f"ReservationTable("
            f"grid={self.grid_width}x{self.grid_depth}, "
            f"reservations={self.get_reservation_count()}, "
            f"active_robots={self.get_robot_count()}"
            f")"
        )