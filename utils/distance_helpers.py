# utils/distance_helpers.py

def get_min_distance_to_pickstation(state, stack_position):
    """
    Berechnet die minimale Manhattan-Distanz von einer Stack-Position
    zur nächsten Pickstation.

    Args:
        state: Simulationszustand mit state.pickstations Liste
        stack_position: (x, y) Tuple der Stack-Position

    Returns:
        Minimale Manhattan-Distanz zur nächsten Pickstation (int).
        Gibt 0 zurück, wenn keine Pickstation existiert.
    """
    if stack_position is None:
        raise ValueError("stack_position must not be None")

    if not state.pickstations:
        return 0

    x, y = stack_position
    min_dist = float("inf")

    for pickstation in state.pickstations:
        ps_x, ps_y = pickstation.position
        dist = abs(x - ps_x) + abs(y - ps_y)
        if dist < min_dist:
            min_dist = dist

    # Defensive: falls aus irgendeinem Grund keine Distanz berechnet wurde
    if min_dist == float("inf"):
        return 0

    return int(min_dist)