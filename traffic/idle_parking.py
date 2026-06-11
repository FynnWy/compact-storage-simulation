"""
Verwaltet Parkpositionen für Idle-Roboter.
"""
from typing import Set, Tuple, List, Optional


class IdleParkingManager:
    """
    Findet gültige Parkpositionen für Idle-Roboter.

    Idle-Roboter dürfen NICHT parken in:
     - Port-Positionen
     - Pufferzone (Distanz ≤ 1 zu Port)
    """

    def __init__(
        self,
        grid_width: int,
        grid_depth: int,
        port_positions: Set[Tuple[int, int]],
        buffer_zone: Set[Tuple[int, int]]
    ):
        self.grid_width = grid_width
        self.grid_depth = grid_depth
        self.port_positions = port_positions
        self.buffer_zone = buffer_zone

        # Berechne gültige Parkpositionen
        self.valid_parking_positions = self._calculate_parking_positions()

    def _calculate_parking_positions(self) -> Set[Tuple[int, int]]:
        """Berechnet alle gültigen Parkpositionen."""
        all_positions = {
            (x, y)
            for x in range(self.grid_width)
            for y in range(self.grid_depth)
        }

        # Entferne Ports und Pufferzone
        invalid = self.port_positions | self.buffer_zone

        return all_positions - invalid

    def is_valid_parking_position(self, position: Tuple[int, int]) -> bool:
        """Prüft ob Position zum Parken geeignet ist."""
        return position in self.valid_parking_positions

    def find_nearest_parking_position(
        self,
        from_position: Tuple[int, int],
        occupied_positions: Set[Tuple[int, int]]
    ) -> Optional[Tuple[int, int]]:
        """
        Findet nächste freie Parkposition.

        Args:
            from_position: Aktuelle Position des Roboters
            occupied_positions: Positionen die bereits belegt sind

        Returns:
            Nächste freie Parkposition oder None
        """
        available = self.valid_parking_positions - occupied_positions

        if not available:
            return None

        # Finde nächste (Manhattan-Distanz)
        def distance(pos):
            return abs(pos[0] - from_position[0]) + abs(pos[1] - from_position[1])

        return min(available, key=distance)

    def must_leave_current_position(self, position: Tuple[int, int]) -> bool:
        """Prüft ob Roboter aktuelle Position verlassen muss."""
        return position not in self.valid_parking_positions