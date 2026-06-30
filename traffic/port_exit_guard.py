"""
Garantiert dass Ports nie vollständig eingeschlossen werden.
"""
from typing import Set, Tuple, List, Optional


class PortExitGuard:
    """
    Prüft und garantiert dass Ports immer ein freies Ausfahrfeld haben.
    """

    def __init__(self, grid_width: int, grid_depth: int):
        self.grid_width = grid_width
        self.grid_depth = grid_depth

    def get_neighbor_positions(
        self,
        position: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        """Gibt alle gültigen Nachbarpositionen zurück."""
        x, y = position
        candidates = [
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
        ]
        return [
            (nx, ny) for (nx, ny) in candidates
            if 0 <= nx < self.grid_width and 0 <= ny < self.grid_depth
        ]

    def count_free_exits(
        self,
        port_position: Tuple[int, int],
        blocked_positions: Set[Tuple[int, int]],
        port_positions: Set[Tuple[int, int]]
    ) -> int:
        """
        Zählt freie Ausfahrfelder für einen Port.

        Args:
            port_position: Position des Ports
            blocked_positions: Positionen die blockiert sind (Roboter etc.)
            port_positions: Alle Port-Positionen (andere Ports)

        Returns:
            Anzahl freier Ausfahrfelder
        """
        neighbors = self.get_neighbor_positions(port_position)
        free_count = 0

        for neighbor in neighbors:
            # Nicht zählen wenn:
            # - Blockiert durch Roboter
            # - Ist selbst ein Port
            if neighbor not in blocked_positions and neighbor not in port_positions:
                free_count += 1

        return free_count

    def would_block_last_exit(
        self,
        proposed_position: Tuple[int, int],
        port_position: Tuple[int, int],
        current_blocked: Set[Tuple[int, int]],
        port_positions: Set[Tuple[int, int]],
        robot_on_port: bool
    ) -> bool:
        """
        Prüft ob eine Bewegung das letzte Ausfahrfeld blockieren würde.

        Args:
            proposed_position: Position die blockiert werden soll
            port_position: Position des Ports
            current_blocked: Aktuell blockierte Positionen
            port_positions: Alle Port-Positionen
            robot_on_port: Ob ein Roboter auf dem Port steht

        Returns:
            True wenn dies das letzte Ausfahrfeld blockieren würde
            UND ein Roboter auf dem Port steht
        """
        if not robot_on_port:
            # Wenn kein Roboter auf Port, kein Problem
            return False

        # Simuliere Blockierung
        simulated_blocked = current_blocked | {proposed_position}

        free_after = self.count_free_exits(
            port_position,
            simulated_blocked,
            port_positions
        )

        return free_after == 0

    def validate_path_for_ports(
        self,
        path: List[Tuple[int, int]],
        path_times: List[int],
        port_positions: Set[Tuple[int, int]],
        get_blocked_at_time: callable,  # (time) -> Set[positions]
        get_robot_on_port: callable      # (port_pos, time) -> bool
    ) -> Tuple[bool, Optional[str]]:
        """
        Validiert ob ein Pfad Ports einschließen würde.

        Returns:
            (True, None) wenn OK
            (False, reason) wenn Pfad Port einschließen würde
        """
        for pos, time in zip(path, path_times):
            for port_pos in port_positions:
                if pos in self.get_neighbor_positions(port_pos):
                    blocked = get_blocked_at_time(time)
                    robot_on = get_robot_on_port(port_pos, time)

                    if self.would_block_last_exit(
                        pos, port_pos, blocked, port_positions, robot_on
                    ):
                        return (
                            False,
                            f"Would block last exit of port at {port_pos} "
                            f"at time {time}"
                        )

        return (True, None)