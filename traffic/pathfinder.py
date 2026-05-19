# traffic/pathfinder.py

import heapq


class Pathfinder:
    """
    Space-Time A* Pathfinding mit Reservation-Awareness.

    Implementiert A* im Space-Time-Graphen:
    - Knoten: (x, y, t)
    - Kanten: Bewegung oder Warten
    
    Berücksichtigt:
    - Reservierungen in ReservationTable
    - Head-on Collisions
    - Grid-Grenzen
    - Highway-Regeln (optional)
    """
    
    def __init__(self, grid, reservation_table, highway_rules=None):
        """
        Args:
            grid: StorageGrid-Instanz
            reservation_table: ReservationTable-Instanz
            highway_rules: Optional - HighwayRules-Instanz
        """
        self.grid = grid
        self.reservation_table = reservation_table
        self.highway_rules = highway_rules  # NEU
        self.grid_width = grid.width
        self.grid_depth = grid.depth
    
    def find_path(
        self,
        start,
        target,
        start_time,
        robot_id,
        allow_waiting=True,
        max_iterations=1000,
    ):
        """
        Findet einen kollisionsfreien Pfad von start nach target.
        
        Args:
            start: (x, y) Startposition
            target: (x, y) Zielposition
            start_time: Startzeitpunkt
            robot_id: ID des Roboters
            allow_waiting: Ob Warten als Aktion erlaubt ist
            max_iterations: Maximale A*-Iterationen
        
        Returns:
            list[(x, y)] | None: Pfad (ohne Startposition) oder None bei Fehler
        """
        if start == target:
            return []
        
        # A* mit Space-Time Knoten
        # f = g + h
        # g = bisherige Kosten (inkl. Highway-Penalties)
        # h = Heuristik (Manhattan-Distanz)
        
        def heuristic(pos):
            return abs(pos[0] - target[0]) + abs(pos[1] - target[1])
        
        # Priority Queue: (f_score, counter, (x, y, t), path, g_score)
        counter = 0
        open_set = []
        heapq.heappush(
            open_set,
            (heuristic(start), counter, (*start, start_time), [start], 0)
        )
        counter += 1
        
        # Visited: (x, y, t) → g_score
        visited = {}
        
        iterations = 0
        
        while open_set and iterations < max_iterations:
            iterations += 1
            
            f_score, _, current_node, path, g_score = heapq.heappop(open_set)
            x, y, t = current_node
            current_pos = (x, y)
            
            # Ziel erreicht?
            if current_pos == target:
                # Pfad ohne Startposition zurückgeben
                return path[1:]
            
            # Bereits mit besseren Kosten besucht?
            if current_node in visited and visited[current_node] <= g_score:
                continue
            visited[current_node] = g_score
            
            # Nachbarn expandieren
            neighbors = self._get_neighbors(x, y, t, robot_id, allow_waiting)
            
            for nx, ny, nt, move_cost in neighbors:
                neighbor_node = (nx, ny, nt)
                
                new_g_score = g_score + move_cost
                
                # Besser als bisheriger Weg zu diesem Knoten?
                if neighbor_node in visited and visited[neighbor_node] <= new_g_score:
                    continue
                
                new_path = path + [(nx, ny)]
                h_score = heuristic((nx, ny))
                new_f_score = new_g_score + h_score
                
                heapq.heappush(
                    open_set,
                    (new_f_score, counter, neighbor_node, new_path, new_g_score)
                )
                counter += 1
        
        # Kein Pfad gefunden
        return None
    
    def _get_neighbors(self, x, y, t, robot_id, allow_waiting):
        """
        Gibt mögliche nächste Positionen mit Kosten zurück.
        
        NEU: Berücksichtigt Highway-Penalties.
        
        Args:
            x, y: Aktuelle Position
            t: Aktueller Zeitpunkt
            robot_id: ID des bewegenden Roboters
            allow_waiting: Ob Warten erlaubt ist
        
        Returns:
            list[(x, y, t, cost)]: Liste möglicher Bewegungen mit Kosten
        """
        neighbors = []
        
        # 4 Bewegungsrichtungen
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        
        for dx, dy in directions:
            nx, ny = x + dx, y + dy
            
            # Grid-Grenzen prüfen (erlaubt Pickstations außerhalb)
            if not self._is_valid_position(nx, ny):
                continue
            
            # Reservierung prüfen
            if not self.reservation_table.is_free(nx, ny, t + 1, exclude_robot=robot_id):
                continue
            
            # Head-on Collision prüfen
            if self._would_cause_head_on_collision(
                robot_id, (x, y), (nx, ny), t
            ):
                continue
            
            # NEU: Highway-Penalty berechnen
            move_cost = 1  # Basis-Bewegungskosten
            if self.highway_rules is not None:
                highway_penalty = self.highway_rules.get_direction_penalty(x, y, dx, dy)
                move_cost += highway_penalty
            
            neighbors.append((nx, ny, t + 1, move_cost))
        
        # Warten (gleiche Position, nächster Zeitschritt)
        if allow_waiting:
            if self.reservation_table.is_free(x, y, t + 1, exclude_robot=robot_id):
                neighbors.append((x, y, t + 1, 1))  # Warten kostet 1
        
        return neighbors


    def _is_valid_position(self, x, y):
        """
        Prüft ob Position gültig ist.

        Erlaubt großzügig Positionen außerhalb des Grids für Pickstations.
        """
        # Grid-Positionen
        if 0 <= x < self.grid_width and 0 <= y < self.grid_depth:
            return True

        # Pickstations außerhalb (links vom Grid)
        if -5 <= x < 0 and -5 <= y < self.grid_depth + 5:
            return True

        return False

    def _would_cause_head_on_collision(self, robot_id, from_pos, to_pos, t):
        """
        Prüft ob Bewegung eine Head-on Collision verursachen würde.

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
        other_robot = self.reservation_table.get_blocking_robot(*to_pos, t)

        if other_robot is None or other_robot == robot_id:
            return False

        # Prüfen ob dieser andere Roboter zur Zeit t+1 auf from_pos sein wird
        next_pos_of_other = self.reservation_table.get_blocking_robot(*from_pos, t + 1)

        return next_pos_of_other == other_robot