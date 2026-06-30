import pytest

from state.pickstation import Pickstation


def _make_pickstation():
    # station_id und capacity sind für diese Unit-Tests irrelevant
    return Pickstation(station_id="PS_0", position=(0, 0), capacity=1)


def test_reserve_available_port():
    ps = _make_pickstation()

    # Port verfügbar → reserve(0) → True
    assert ps.reserve(0) is True

    # is_reserved_by(0) → True
    assert ps.is_reserved_by(0) is True
    assert ps.is_reserved() is True
    assert ps.is_available() is False


def test_reserve_already_reserved():
    ps = _make_pickstation()

    assert ps.reserve(0) is True
    # Reservierung für anderen Roboter nicht möglich
    assert ps.reserve(1) is False
    # Reservierung bleibt beim ersten Roboter
    assert ps.is_reserved_by(0) is True
    assert ps.is_reserved_by(1) is False


def test_reserve_idempotent():
    ps = _make_pickstation()

    assert ps.reserve(0) is True
    # Nochmal gleicher Roboter → weiterhin True
    assert ps.reserve(0) is True
    assert ps.is_reserved_by(0) is True


def test_robot_enters_with_reservation():
    ps = _make_pickstation()

    assert ps.reserve(0) is True

    # Darf ohne Fehler einfahren
    ps.robot_enters(0)

    assert ps.is_occupied() is True
    assert ps.robot_on_port == 0
    assert ps.is_reserved_by(0) is True


def test_robot_enters_without_reservation():
    ps = _make_pickstation()

    # Keine Reservierung gesetzt → Einfahrt wirft Fehler
    with pytest.raises(RuntimeError):
        ps.robot_enters(0)

    assert ps.is_occupied() is False
    assert ps.is_reserved() is False


def test_robot_enters_wrong_reservation():
    ps = _make_pickstation()

    assert ps.reserve(0) is True

    # Falscher Roboter versucht einzufahren → Fehler
    with pytest.raises(RuntimeError):
        ps.robot_enters(1)

    assert ps.is_occupied() is False
    assert ps.is_reserved_by(0) is True


def test_robot_leaves_releases_all():
    ps = _make_pickstation()

    assert ps.reserve(0) is True
    ps.robot_enters(0)

    ps.robot_leaves()

    assert ps.is_available() is True
    assert ps.is_reserved() is False
    assert ps.is_occupied() is False
    assert ps.reserved_for_robot is None
    assert ps.robot_on_port is None


def test_double_occupation_blocked():
    ps = _make_pickstation()

    # Erster Roboter reserviert und fährt ein
    assert ps.reserve(0) is True
    ps.robot_enters(0)
    assert ps.is_occupied() is True

    # Zweiter Roboter kann nicht reservieren, solange Port besetzt ist
    assert ps.reserve(1) is False

    # Und Einfahrt würde auch explizit scheitern
    with pytest.raises(RuntimeError):
        ps.robot_enters(1)

    # Zustand unverändert beim ersten Roboter
    assert ps.is_reserved_by(0) is True
    assert ps.robot_on_port == 0