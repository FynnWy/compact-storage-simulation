# traffic/deadlock_detector.py

class DeadlockDetector:
    """
    Erkennt zyklische Wartebeziehungen zwischen Robotern (Wait-For-Graph).

    Wait-For-Graph:
    - Knoten: Roboter
    - Kante A → B: Roboter A wartet auf Roboter B

    Deadlock = Zyklus im Graphen

    Beispiel:
    - Robot 0 wartet auf Robot 1
    - Robot 1 wartet auf Robot 2
    - Robot 2 wartet auf Robot 0
    => Zyklus = Deadlock
    """

    def __init__(self):
        # robot_id → {"waiting_for": robot_id, "reason": str, "since": int}
        self._wait_graph = {}

    def register_wait(self, waiting_robot_id, blocking_robot_id, reason="", current_time=0):
        """
        Registriert eine Wartebeziehung.

        Args:
            waiting_robot_id: ID des wartenden Roboters
            blocking_robot_id: ID des blockierenden Roboters
            reason: Grund für Wartebeziehung (z.B. "path_blocked")
            current_time: Zeitpunkt der Registrierung
        """
        self._wait_graph[waiting_robot_id] = {
            "waiting_for": blocking_robot_id,
            "reason": reason,
            "since": current_time,
        }

    def clear_wait(self, robot_id):
        """
        Löscht Wartebeziehung eines Roboters.

        Args:
            robot_id: ID des Roboters
        """
        self._wait_graph.pop(robot_id, None)

    def clear_all(self):
        """Löscht alle Wartebeziehungen."""
        self._wait_graph.clear()

    def detect_cycle(self):
        """
        Prüft auf Zyklen im Wait-For-Graph mittels DFS.

        Returns:
            list[robot_id] | None: Liste der Roboter im Zyklus (falls vorhanden)
        """
        visited = set()
        rec_stack = set()

        for start_robot in self._wait_graph:
            if start_robot in visited:
                continue

            cycle = self._dfs_cycle(start_robot, visited, rec_stack, [])
            if cycle:
                return cycle

        return None

    def _dfs_cycle(self, node, visited, rec_stack, path):
        """
        Tiefensuche zur Zykluserkennung.

        Args:
            node: Aktueller Knoten (robot_id)
            visited: Menge besuchter Knoten
            rec_stack: Rekursionsstack (für Zyklus-Erkennung)
            path: Aktueller Pfad

        Returns:
            list[robot_id] | None: Zyklus falls gefunden
        """
        if node in rec_stack:
            # Zyklus gefunden - extrahiere Zyklus aus Pfad
            cycle_start_idx = path.index(node)
            return path[cycle_start_idx:]

        if node in visited:
            return None

        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        # Folge der Wartebeziehung
        wait_info = self._wait_graph.get(node)
        if wait_info is not None:
            next_node = wait_info["waiting_for"]
            cycle = self._dfs_cycle(next_node, visited, rec_stack, path)
            if cycle:
                return cycle

        rec_stack.remove(node)
        path.pop()
        return None

    def get_wait_time(self, robot_id, current_time):
        """
        Gibt zurück, wie lange ein Roboter bereits wartet.

        Args:
            robot_id: ID des Roboters
            current_time: Aktueller Zeitpunkt

        Returns:
            int: Wartezeit in Zeiteinheiten (0 wenn nicht wartend)
        """
        wait_info = self._wait_graph.get(robot_id)
        if wait_info is None:
            return 0
        return current_time - wait_info["since"]

    def is_waiting(self, robot_id):
        """Prüft ob Roboter aktuell wartet."""
        return robot_id in self._wait_graph

    def get_waiting_robots(self):
        """Gibt Liste aller wartenden Roboter zurück."""
        return list(self._wait_graph.keys())

    def __repr__(self):
        return f"DeadlockDetector(waiting_robots={len(self._wait_graph)})"


class DeadlockResolver:
    """
    Löst erkannte Deadlocks auf.

    Strategien:
    - lowest_priority: Roboter mit niedrigster Priorität plant neu
    - random: Zufälliger Roboter plant neu
    - longest_wait: Roboter der am längsten wartet plant neu
    """

    def __init__(self, strategy="lowest_priority"):
        """
        Args:
            strategy: Auflösungsstrategie
                - "lowest_priority": Nach Task-Priorität
                - "random": Zufällig
                - "longest_wait": Roboter mit längster Wartezeit
        """
        self.strategy = strategy

    def resolve(self, cycle, robots, scheduler=None, current_time=0):
        """
        Löst einen erkannten Deadlock auf.

        Args:
            cycle: Liste von robot_ids im Zyklus
            robots: Liste aller Robot-Instanzen
            scheduler: Scheduler-Instanz (für Prioritäten)
            current_time: Aktueller Zeitpunkt

        Returns:
            robot_id: ID des Roboters, der neu planen soll
        """
        if not cycle:
            return None

        if self.strategy == "lowest_priority":
            return self._resolve_lowest_priority(cycle, robots, scheduler)

        if self.strategy == "random":
            return self._resolve_random(cycle)

        if self.strategy == "longest_wait":
            return self._resolve_longest_wait(cycle, current_time)

        raise ValueError(f"Unknown resolution strategy: {self.strategy}")

    def _resolve_lowest_priority(self, cycle, robots, scheduler):
        """
        Wählt Roboter mit niedrigster Priorität zur Neuplanung.

        Priorität wird vom Scheduler bestimmt (Task-basiert).
        Fallback: höchste robot_id = niedrigste Priorität
        """
        if scheduler is None:
            # Fallback: höchste ID
            return max(cycle)

        cycle_robots = [r for r in robots if r.robot_id in cycle]

        # Nach Priorität sortieren (höhere Werte = niedrigere Priorität)
        def get_priority(robot):
            if robot.current_task is None:
                return 999  # Roboter ohne Task hat niedrigste Priorität
            return scheduler._get_task_priority(robot.current_task)

        victim = max(cycle_robots, key=lambda r: (get_priority(r), r.robot_id))
        return victim.robot_id

    def _resolve_random(self, cycle):
        """Wählt zufälligen Roboter aus Zyklus."""
        import random
        return random.choice(cycle)

    def _resolve_longest_wait(self, cycle, current_time):
        """Wählt Roboter mit längster Wartezeit (nicht implementiert in v1)."""
        # Würde DeadlockDetector.get_wait_time() nutzen
        # Für v1: Fallback auf ersten Roboter
        return cycle[0]