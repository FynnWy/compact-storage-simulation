"""
Berechnung und Verwaltung der Port-Pufferzonen.

Die Pufferzone umfasst alle Positionen mit Manhattan-Distanz ≤ 1
zu irgendeinem Port. Diese Positionen sind für Rücklagerung VERBOTEN.
"""
from typing import Set, Tuple, List


def calculate_buffer_zone(
    port_positions: List[Tuple[int, int]],
    grid_width: int,
    grid_depth: int
) -> Set[Tuple[int, int]]:
    """
    Berechnet alle Positionen in der Pufferzone.

    Args:
        port_positions: Liste der Port-Koordinaten
        grid_width: Breite des Grids
        grid_depth: Tiefe des Grids

    Returns:
        Set aller Positionen mit Distanz ≤ 1 zu irgendeinem Port,
        gefiltert auf gültige Grid-Koordinaten.
    """
    buffer_zone: Set[Tuple[int, int]] = set()

    for (px, py) in port_positions:
        # Nur gültige Port-Positionen berücksichtigen
        if 0 <= px < grid_width and 0 <= py < grid_depth:
            # Port selbst (Distanz 0)
            buffer_zone.add((px, py))

        # 4-Nachbarn (Distanz 1)
        neighbors = [
            (px - 1, py),  # links
            (px + 1, py),  # rechts
            (px, py - 1),  # oben
            (px, py + 1),  # unten
        ]

        for (nx, ny) in neighbors:
            # Nur gültige Grid-Positionen
            if 0 <= nx < grid_width and 0 <= ny < grid_depth:
                buffer_zone.add((nx, ny))

    return buffer_zone


def is_valid_storage_target(
    position: Tuple[int, int],
    buffer_zone: Set[Tuple[int, int]],
    port_positions: Set[Tuple[int, int]],
) -> bool:
    """
    Prüft ob eine Position für Rücklagerung geeignet ist.

    Returns:
        True wenn Position NICHT in Pufferzone und NICHT Port-Position.
    """
    return position not in buffer_zone and position not in port_positions