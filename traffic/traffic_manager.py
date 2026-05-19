# traffic/traffic_manager.py

from traffic.pathfinder import Pathfinder
from traffic.deadlock_detector import DeadlockDetector, DeadlockResolver


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
        highway_rules=None,  # NEU
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
        self.highway_rules = highway_rules  # NEU
        
        # Pathfinder mit Highway-Regeln erstellen
        self.pathfinder = pathfinder or Pathfinder(
            grid,
            reservation_table,
            highway_rules=highway_rules,  # NEU
        )
        
        self.deadlock_detector = deadlock_detector or DeadlockDetector()
        self.deadlock_resolver = deadlock_resolver or DeadlockResolver(
            strategy="lowest_priority"
        )
        
        # Statistiken
        self._deadlocks_detected = 0
        self._deadlocks_resolved = 0
    
    # ... rest bleibt unverändert ...
    
    def request_path(
        self,
        robot,
        target,
        current_time,
        allow_waiting=True,
        max_attempts=3,
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
            )
            
            if path is None:
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