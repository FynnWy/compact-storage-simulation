# traffic/traffic_manager.py

from traffic.pathfinder import Pathfinder
from traffic.deadlock_detector import DeadlockDetector, DeadlockResolver
from traffic.port_exit_guard import PortExitGuard

class TrafficManager:
    """
    Zentrale Koordination aller Roboter-Bewegungen.
    
    Verantwortlichkeiten:
    - Pfadanfragen entgegennehmen
    - Space-Time Reservierungen koordinieren
    - Kollisionen proaktiv verhindern
    - Replanning bei Konflikten
    - Deadlock-Erkennung und -Auflösung
    - Highway-Regeln durchsetzen (optional)
    
    NICHT verantwortlich für:
    - Task-Zuweisung (Scheduler)
    - Aktionsausführung (Executor)
    - Zeitkosten-Berechnung (CostModel)
    """
    
    def __init__(
        self,
        grid,
        reservation_table,
        pathfinder=None,
        deadlock_detector=None,
        deadlock_resolver=None,
        highway_rules=None,
        port_positions=None,  # Port-Positionen für Ausfahrfeld-Garantie
    ):
        """
        Args:
            grid: StorageGrid-Instanz
            reservation_table: ReservationTable-Instanz
            pathfinder: Optional - Pathfinder-Instanz
            deadlock_detector: Optional - DeadlockDetector-Instanz
            deadlock_resolver: Optional - DeadlockResolver-Instanz
            highway_rules: Optional - HighwayRules-Instanz
        """
        self.grid = grid
        self.reservation_table = reservation_table
        self.highway_rules = highway_rules

        # Port-Positionen & Ausfahrfeld-Garantie
        self.port_positions = set(port_positions or getattr(grid, "port_positions", set()))
        self.port_exit_guard = PortExitGuard(
            grid_width=grid.width,
            grid_depth=grid.depth,
        )
        
        # Pathfinder mit Highway-Regeln erstellen
        self.pathfinder = pathfinder or Pathfinder(
            grid,
            reservation_table,
            highway_rules=highway_rules,
        )
        
        self.deadlock_detector = deadlock_detector or DeadlockDetector()
        self.deadlock_resolver = deadlock_resolver or DeadlockResolver(
            strategy="lowest_priority"
        )
        
        # Rückverweis auf den State. Wird von `SimulationEngine._initialize_state`
        # gesetzt, sobald der State existiert (der TrafficManager wird davor
        # gebaut). Er liefert die PHYSISCHE Wahrheit über Roboterpositionen und
        # Portbelegung, die die Reservierungstabelle allein nicht kennt.
        self.state = None

        # Statistiken
        self._deadlocks_detected = 0
        self._deadlocks_resolved = 0
        self.port_admission_denials = 0

    # ------------------------------------------------------------------ #
    # Port-Zutritt (Klasse C, 2026-08-22)
    # ------------------------------------------------------------------ #

    def get_port_exit_cells_to_keep_free(self, robot_id):
        """
        Zellen, die frei bleiben müssen, damit ein Roboter den Port verlassen kann.

        Hintergrund (Klasse C): Steht ein Roboter auf einer Portzelle, sind ihre
        drei Nachbarn seine einzigen Ausfahrten. Werden alle drei belegt, ist er
        eingeschlossen. Er kann die Station nicht räumen, alle nachfolgenden
        Roboter warten auf genau diese Zelle, und der Lauf macht keinen
        Fortschritt mehr — ohne dass eine Invariante verletzt wäre.

        Warum die vorhandene `PortExitGuard`-Prüfung das nicht verhindert hat:
        Sie wertet ausschließlich die RESERVIERUNGSTABELLE aus. Ein Roboter, der
        steht (leerer Pfad, keine künftigen Reservierungen), taucht dort nicht
        auf. `get_robot_on_port` lieferte deshalb False, und die Prüfung brach
        sofort ab — gemessen in ABC+ABC/Seed 42 (Roboter 1 auf (0,15), Pfadrest
        leer, 0 freie Nachbarn) und POPULARITY/Seed 1 (Roboter 3 auf (19,15),
        ebenfalls 0 freie Nachbarn).

        Diese Methode fragt stattdessen den tatsächlichen Zustand ab: Wer steht
        laut `Pickstation.robot_on_port` physisch auf einem Port, und welche
        seiner Nachbarzellen sind aktuell von Robotern besetzt? Bleibt genau
        eine freie Ausfahrt übrig, wird diese Zelle für alle anderen Roboter
        gesperrt.

        Keine willkürliche Kapazitätszahl: die Regel folgt direkt aus der
        Geometrie (Port am Rand ⇒ drei Nachbarn) und aus der physischen
        Bedingung, dass ein besetzter Port mindestens eine Ausfahrt braucht.
        Keine zweite Reservierungsstruktur, kein Zufall, deterministisch.

        Args:
            robot_id: Roboter, für den geplant wird. Er selbst wird nicht
                gegen seine eigene aktuelle Position gesperrt.

        Returns:
            set[(x, y)]: zu meidende Zellen.
        """
        state = self.state
        if state is None or not self.port_positions:
            return set()

        # Belegt = physisch besetzt ODER von einem anderen Roboter bereits
        # eingeplant.
        #
        # Die Planung allein reichte nicht (TOCTOU, gefunden 2026-08-22):
        # Sind noch ZWEI Ausfahrten frei, sperrt die Regel nichts. Planen
        # daraufhin zwei fremde Roboter nacheinander je eine davon an, ist der
        # Port nach Ausführung beider Wege eingeschlossen — jede Einzelprüfung
        # war für sich korrekt. Deshalb zählt ein bereits geplanter Weg auf
        # eine Ausfahrt genauso wie ein Roboter, der dort schon steht.
        besetzt = {}
        for r in getattr(state, "robots", []) or []:
            if r.robot_id == robot_id:
                continue
            pos = r.get_position()
            if pos is not None:
                besetzt[pos] = r.robot_id
            pfad = getattr(r, "planned_path", None) or []
            index = getattr(r, "path_index", 0) or 0
            for wegpunkt in pfad[index:]:
                besetzt.setdefault(wegpunkt, r.robot_id)

        # Zusätzlich die Reservierungstabelle: dort steht ein Weg bereits,
        # bevor der Aufrufer ihn dem Roboter zuweist. Ohne diese Quelle bleibt
        # zwischen `request_path` und `robot.set_path` ein Fenster offen, in
        # dem ein zweiter Roboter dieselbe Ausfahrt planen darf.
        reserviert_von = {}
        for (x, y, _t), belegender in getattr(
                self.reservation_table, "_reservations", {}).items():
            if belegender != robot_id:
                reserviert_von.setdefault((x, y), belegender)

        gesperrt = set()
        for station in getattr(state, "pickstations", []) or []:
            belegt_von = getattr(station, "robot_on_port", None)
            if belegt_von is None or belegt_von == robot_id:
                # Kein fremder Roboter auf dem Port → nichts zu schützen.
                continue

            ausfahrten = [
                pos for pos in self.port_exit_guard.get_neighbor_positions(
                    station.position)
                if pos not in self.port_positions
            ]
            frei = [pos for pos in ausfahrten
                    if pos not in besetzt and pos not in reserviert_von]

            if len(frei) <= 1:
                # Letzte Ausfahrt: für alle anderen sperren.
                gesperrt.update(frei)

        return gesperrt

    def request_path(
            self,
            robot,
            target,
            current_time,
            allow_waiting=True,
            max_attempts=3,
            blocked_cells=None,  # NEU: Zusätzliche blockierte Zellen
    ):
        """
        Plant Pfad und reserviert ihn.

        Wenn Pfad nicht sofort reserviert werden kann, werden mehrere
        Versuche mit leicht verzögertem Start unternommen.

        Args:
            robot: Robot-Instanz
            target: (x, y) Zielposition
            current_time: Aktueller Zeitpunkt
            allow_waiting: Ob Warten als Aktion erlaubt ist
            max_attempts: Maximale Versuche mit zeitlicher Verzögerung
            blocked_cells: Optional - Set von (x, y) Positionen, die gemieden werden sollen

        Returns:
            list[(x, y)] | None: Pfad (ohne Startposition) oder None bei Fehler
        """
        start = robot.get_position()

        if start is None:
            # Roboter hat noch keine Position - setze auf Ziel
            return []

        if start == target:
            # Bereits am Ziel
            return []

        # Klasse C: letzte Ausfahrt eines besetzten Ports freihalten.
        #
        # KEINE Ausnahme für das eigene Ziel (korrigiert 2026-08-22). Die
        # frühere Fassung nahm `target` aus der Sperre heraus, damit ein
        # Roboter, der genau dorthin muss, planen kann. Damit war die Garantie
        # aber wirkungslos: ein fremder Roboter durfte die letzte Ausfahrt
        # belegen, sobald sie sein Ziel war — nachgewiesen im Randfalltest.
        #
        # Die Ausnahme wird auch nicht gebraucht: Zellen der Port-Pufferzone
        # sind keine gültigen Storage-Positionen, also nie Ziel eines Pickups
        # oder einer Ablage, und das Idle-Parking meidet die Zone ohnehin. Das
        # einzige legitime Ziel innerhalb der Zone ist die Portzelle selbst —
        # und die ist keine Ausfahrt. Für den Roboter AUF dem Port wird
        # ohnehin nichts gesperrt.
        freizuhaltende = self.get_port_exit_cells_to_keep_free(robot.robot_id)
        if freizuhaltende:
            if target in freizuhaltende:
                self.port_admission_denials += 1
                print(
                    f"[PORT_ADMISSION] robot {robot.robot_id} target {target} "
                    f"ist letzte Ausfahrt eines besetzten Ports -> kein Pfad"
                )
                return None
            blocked_cells = set(blocked_cells or set()) | freizuhaltende

        # Mehrere Versuche mit zeitlicher Verzögerung
        for attempt in range(max_attempts):
            start_time = current_time + attempt

            # Pfad berechnen
            path = self.pathfinder.find_path(
                start=start,
                target=target,
                start_time=start_time,
                robot_id=robot.robot_id,
                allow_waiting=allow_waiting,
                blocked_cells=blocked_cells,  # NEU: Weitergeben an Pathfinder
            )
            
            if path is None:
                continue

            # Ausfahrfeld-Garantie für Ports prüfen (HARTE Constraint)
            if self.port_positions:
                times = [start_time + i for i in range(len(path))]

                is_valid, reason = self.port_exit_guard.validate_path_for_ports(
                    path=path,
                    path_times=times,
                    port_positions=self.port_positions,
                    get_blocked_at_time=lambda t: self.reservation_table.get_blocked_at(t),
                    get_robot_on_port=lambda p, t: self._robot_on_port_at(p, t),
                )

                if not is_valid:
                    # Pfad würde Port einschließen → ablehnen
                    print(f"[BLOCKED] Path for robot {robot.robot_id} rejected: {reason}")
                    continue
            
            # Pfad reservieren
            success, conflict = self.reservation_table.reserve_path(
                robot_id=robot.robot_id,
                path=path,
                start_time=start_time,
            )
            
            if success:
                # Erfolg - Wartebeziehung löschen
                self.deadlock_detector.clear_wait(robot.robot_id)
                return path
            
            # NEU: Bei Konflikt Wartebeziehung registrieren
            if conflict and conflict.get("blocking_robot"):
                self.deadlock_detector.register_wait(
                    waiting_robot_id=robot.robot_id,
                    blocking_robot_id=conflict["blocking_robot"],
                    reason="path_blocked",
                    current_time=current_time,
                )
        
        # Alle Versuche fehlgeschlagen
        return None

    def _robot_on_port_at(self, port_pos, t):
        """
        Prüft, ob zur Zeit t ein Roboter auf einem Port steht.

        Implementierung über Reservierungstabelle:
        Sobald eine Zelle (Port) für t reserviert ist, gilt sie als belegt.
        """
        if port_pos not in self.port_positions:
            return False

        blocking_robot = self.reservation_table.get_blocking_robot(
            port_pos[0], port_pos[1], t
        )
        return blocking_robot is not None
    
    def release_robot_reservations(self, robot):
        """
        Gibt alle Reservierungen eines Roboters frei.
        
        Args:
            robot: Robot-Instanz
        """
        self.reservation_table.release_all(robot.robot_id)
        self.deadlock_detector.clear_wait(robot.robot_id)
    
    def replan(self, robot, target, current_time):
        """
        Lokales Replanning bei Blockierung.
        
        Gibt bestehende Reservierungen frei und plant neu.
        
        Args:
            robot: Robot-Instanz
            target: (x, y) Zielposition
            current_time: Aktueller Zeitpunkt
        
        Returns:
            list[(x, y)] | None: Neuer Pfad oder None
        """
        # Alte Reservierungen freigeben
        self.release_robot_reservations(robot)
        
        # Neu planen
        return self.request_path(robot, target, current_time)
    
    def check_and_resolve_deadlock(self, robots, scheduler=None, current_time=0):
        """
        Prüft auf Deadlock und löst ihn ggf. auf.
        
        Args:
            robots: Liste aller Robot-Instanzen
            scheduler: Optional - Scheduler für Prioritäten
            current_time: Aktueller Zeitpunkt
        
        Returns:
            robot_id | None: ID des Roboters, der neu planen soll (falls Deadlock)
        """
        cycle = self.deadlock_detector.detect_cycle()
        
        if cycle is None:
            return None
        
        # Deadlock erkannt
        self._deadlocks_detected += 1
        
        print(
            f"[DEADLOCK] Detected cycle at t={current_time}: "
            f"robots {cycle}"
        )
        
        # Auflösen
        victim_id = self.deadlock_resolver.resolve(
            cycle=cycle,
            robots=robots,
            scheduler=scheduler,
            current_time=current_time,
        )
        
        if victim_id is not None:
            self._deadlocks_resolved += 1
            print(f"[DEADLOCK] Resolved: robot {victim_id} will replan")
        
        return victim_id
    
    def cleanup(self, current_time):
        """
        Räumt abgelaufene Reservierungen auf.
        
        Args:
            current_time: Aktueller Zeitpunkt
        """
        self.reservation_table.cleanup_before(current_time)
    
    def get_statistics(self):
        """
        Gibt Statistiken über Reservierungen, Deadlocks und Highway zurück.
        
        Returns:
            dict: Statistik-Dictionary
        """
        stats = {
            "total_reservations": self.reservation_table.get_reservation_count(),
            "active_robots": self.reservation_table.get_robot_count(),
            "waiting_robots": len(self.deadlock_detector.get_waiting_robots()),
            "deadlocks_detected": self._deadlocks_detected,
            "deadlocks_resolved": self._deadlocks_resolved,
        }
        
        # NEU: Highway-Statistiken
        if self.highway_rules is not None:
            stats["highway"] = self.highway_rules.get_statistics()
        
        return stats