from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class RobotCandidate:
    """Kandidat für Port-Zuweisung."""
    robot_id: int
    position: Tuple[int, int]
    deadline: int  # Absolute Deadline (Zeitpunkt)
    task_id: Optional[str] = None  # Für Debugging


@dataclass
class PrioritizationResult:
    """Ergebnis der Priorisierung."""
    selected_robot_id: int
    estimated_arrival: int
    slack: int  # Kann negativ sein (verspätet)
    is_feasible: bool
    reason: str


class PortPrioritizer:
    """
    Wählt den besten Roboter für Port-Zugang aus.

    Strategie:
    1. Berechne für jeden Kandidaten: Ankunftszeit und Slack
    2. Filtere auf Kandidaten die Deadline einhalten können
    3. Wähle den mit frühester Ankunftszeit (minimiert Port-Leerlauf)
    4. Falls keiner Deadline einhalten kann: Wähle least tardy
    """

    def __init__(self, move_cost_per_cell: int = 1):
        """
        Args:
            move_cost_per_cell: Zeiteinheiten pro Bewegung (Default: 1)
        """
        self.move_cost = move_cost_per_cell

    def calculate_distance(
        self,
        from_pos: Tuple[int, int],
        to_pos: Tuple[int, int]
    ) -> int:
        """Manhattan-Distanz zwischen zwei Positionen."""
        return abs(from_pos[0] - to_pos[0]) + abs(from_pos[1] - to_pos[1])

    def estimate_arrival_time(
        self,
        robot_position: Tuple[int, int],
        port_position: Tuple[int, int],
        current_time: int
    ) -> int:
        """Schätzt Ankunftszeit am Port."""
        distance = self.calculate_distance(robot_position, port_position)
        travel_time = distance * self.move_cost
        return current_time + travel_time

    def calculate_slack(
        self,
        estimated_arrival: int,
        deadline: int
    ) -> int:
        """
        Berechnet Slack (Puffer bis Deadline).

        Positiv = Zeit übrig
        Negativ = Verspätung
        """
        return deadline - estimated_arrival

    def select_robot(
        self,
        candidates: List[RobotCandidate],
        port_position: Tuple[int, int],
        current_time: int
    ) -> Optional[PrioritizationResult]:
        """
        Wählt den besten Roboter aus den Kandidaten.

        Args:
            candidates: Liste der Roboter die den Port wollen
            port_position: Position des Ports
            current_time: Aktuelle Simulationszeit

        Returns:
            PrioritizationResult oder None wenn keine Kandidaten
        """
        if not candidates:
            return None

        # Berechne Metriken für alle Kandidaten
        evaluated = []
        for candidate in candidates:
            arrival = self.estimate_arrival_time(
                candidate.position,
                port_position,
                current_time
            )
            slack = self.calculate_slack(arrival, candidate.deadline)
            is_feasible = slack >= 0

            evaluated.append({
                "candidate": candidate,
                "arrival": arrival,
                "slack": slack,
                "is_feasible": is_feasible,
            })

        # Trenne in feasible und non-feasible
        feasible = [e for e in evaluated if e["is_feasible"]]

        if feasible:
            # Wähle feasible mit frühester Ankunft
            # Bei Gleichstand: niedrigere Robot-ID
            feasible.sort(key=lambda e: (e["arrival"], e["candidate"].robot_id))
            best = feasible[0]
            reason = "feasible_earliest_arrival"
        else:
            # Keiner feasible: Wähle least tardy
            evaluated.sort(key=lambda e: (-e["slack"], e["candidate"].robot_id))
            best = evaluated[0]  # Höchster (am wenigsten negativer) Slack
            reason = "least_tardy"

        return PrioritizationResult(
            selected_robot_id=best["candidate"].robot_id,
            estimated_arrival=best["arrival"],
            slack=best["slack"],
            is_feasible=best["is_feasible"],
            reason=reason,
        )

    def select_robot_for_port(
        self,
        candidates: List[RobotCandidate],
        port_position: Tuple[int, int],
        current_time: int,
        excluded_robot_ids: Optional[set] = None
    ) -> Optional[PrioritizationResult]:
        """
        Wrapper mit optionalem Ausschluss bestimmter Roboter.

        Args:
            excluded_robot_ids: Robot-IDs die ausgeschlossen werden sollen
        """
        if excluded_robot_ids:
            candidates = [
                c for c in candidates
                if c.robot_id not in excluded_robot_ids
            ]
        return self.select_robot(candidates, port_position, current_time)