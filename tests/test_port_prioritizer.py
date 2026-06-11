# tests/test_port_prioritizer.py
import pytest

from traffic.port_prioritizer import PortPrioritizer, RobotCandidate


@pytest.fixture
def prioritizer():
    # move_cost_per_cell = 1 → Manhattan-Distanz = Reisezeit
    return PortPrioritizer(move_cost_per_cell=1)


def make_candidate(robot_id, distance, current_time, deadline_offset):
    """
    Hilfsfunktion für einfache 1D-Szenarien:
    - Port bei Position (0, 0)
    - Roboter auf (distance, 0) (oder (0, distance) – egal wegen Manhattan)
    - Deadline = current_time + deadline_offset
    """
    return RobotCandidate(
        robot_id=robot_id,
        position=(distance, 0),
        deadline=current_time + deadline_offset,
        task_id=f"task_{robot_id}",
    )


def test_select_feasible_with_earlier_arrival(prioritizer):
    """
    1. Robot A: Distanz 2, Deadline +50 → arrival=t+2, feasible
       Robot B: Distanz 4, Deadline +50 → arrival=t+4, feasible
       Gewinner: Robot A (frühere Ankunft)
    """
    t = 10
    port_pos = (0, 0)

    a = make_candidate(robot_id=1, distance=2, current_time=t, deadline_offset=50)
    b = make_candidate(robot_id=2, distance=4, current_time=t, deadline_offset=50)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert result.selected_robot_id == 1
    assert result.is_feasible
    assert result.reason == "feasible_earliest_arrival"


def test_feasible_beats_earlier_arrival_non_feasible(prioritizer):
    """
    2. Robot A: Distanz 2, Deadline +1 → NOT feasible
       Robot B: Distanz 4, Deadline +50 → feasible
       Gewinner: Robot B (einziger feasible)
    """
    t = 0
    port_pos = (0, 0)

    # A: arrival = t+2 = 2, deadline = 1 → slack = -1 → nicht feasible
    a = make_candidate(robot_id=1, distance=2, current_time=t, deadline_offset=1)
    # B: arrival = t+4 = 4, deadline = 50 → slack = 46 → feasible
    b = make_candidate(robot_id=2, distance=4, current_time=t, deadline_offset=50)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert result.selected_robot_id == 2
    assert result.is_feasible
    assert result.reason == "feasible_earliest_arrival"


def test_nearby_robot_with_later_deadline_wins(prioritizer):
    """
    3. Robot A: Distanz 4, Deadline +5  → feasible, arrival=t+4
       Robot B: Distanz 2, Deadline +50 → feasible, arrival=t+2
       Gewinner: Robot B (frühere Ankunft, beide feasible)
    """
    t = 0
    port_pos = (0, 0)

    a = make_candidate(robot_id=1, distance=4, current_time=t, deadline_offset=5)
    b = make_candidate(robot_id=2, distance=2, current_time=t, deadline_offset=50)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert result.selected_robot_id == 2
    assert result.is_feasible
    assert result.reason == "feasible_earliest_arrival"


def test_tight_deadline_still_feasible_wins(prioritizer):
    """
    4. Robot A: Distanz 4, Deadline +5  → arrival=t+4, slack=1, feasible
       Robot B: Distanz 40, Deadline +100 → arrival=t+40, feasible
       Gewinner: Robot A (frühere Ankunft)
    """
    t = 0
    port_pos = (0, 0)

    a = make_candidate(robot_id=1, distance=4, current_time=t, deadline_offset=5)
    b = make_candidate(robot_id=2, distance=40, current_time=t, deadline_offset=100)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert result.selected_robot_id == 1
    assert result.is_feasible
    assert result.reason == "feasible_earliest_arrival"


def test_least_tardy_when_none_feasible(prioritizer):
    """
    5. Robot A: Distanz 10, Deadline +5  → arrival=t+10, slack=-5
       Robot B: Distanz 20, Deadline +5  → arrival=t+20, slack=-15
       Gewinner: Robot A (weniger verspätet)
    """
    t = 0
    port_pos = (0, 0)

    a = make_candidate(robot_id=1, distance=10, current_time=t, deadline_offset=5)
    b = make_candidate(robot_id=2, distance=20, current_time=t, deadline_offset=5)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert not result.is_feasible
    # A: slack = -5, B: slack = -15 → -5 > -15 → least tardy
    assert result.selected_robot_id == 1
    assert result.reason == "least_tardy"


def test_deterministic_tiebreaker(prioritizer):
    """
    6. Robot A (ID=0): Distanz 5, Deadline +50
       Robot B (ID=1): Distanz 5, Deadline +50
       Gewinner: Robot A (niedrigere ID)
    """
    t = 0
    port_pos = (0, 0)

    a = make_candidate(robot_id=0, distance=5, current_time=t, deadline_offset=50)
    b = make_candidate(robot_id=1, distance=5, current_time=t, deadline_offset=50)

    result = prioritizer.select_robot([a, b], port_pos, t)

    assert result is not None
    assert result.is_feasible
    # Beide haben identische arrival & slack → niedrigere Robot-ID gewinnt
    assert result.selected_robot_id == 0
    assert result.reason == "feasible_earliest_arrival"


def test_empty_candidates(prioritizer):
    """
    7. test_empty_candidates:
       - Keine Kandidaten → None
    """
    t = 0
    port_pos = (0, 0)

    result = prioritizer.select_robot([], port_pos, t)

    assert result is None