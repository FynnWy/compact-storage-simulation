# tests/test_reservation_table.py
"""
Unit-Tests für ReservationTable.

Testet:
- INV-R1: Keine zwei Roboter auf derselben Zelle zur selben Zeit
- INV-R2: Head-on Collision Detection
- INV-R3: Atomare Pfad-Reservierung (Rollback bei Konflikt)
- Cleanup und Speicher-Management
"""
import pytest


class TestReservationTableBasics:
    """Grundlegende Reservierungs-Operationen."""

    def test_reserve_single_cell(self, reservation_table):
        """Einzelne Zelle reservieren."""
        rt = reservation_table

        success = rt.reserve(robot_id=0, x=2, y=2, t=10)

        assert success is True
        assert rt.is_free(2, 2, 10, exclude_robot=None) is False
        assert rt.get_blocking_robot(2, 2, 10) == 0

    def test_reserve_idempotent(self, reservation_table):
        """Gleiche Reservierung zweimal = idempotent."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=2, y=2, t=10)
        success = rt.reserve(robot_id=0, x=2, y=2, t=10)  # Nochmal

        assert success is True  # Idempotent, kein Fehler

    def test_is_free_with_exclude(self, reservation_table):
        """is_free mit exclude_robot ignoriert eigene Reservierung."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=2, y=2, t=10)

        assert rt.is_free(2, 2, 10, exclude_robot=0) is True
        assert rt.is_free(2, 2, 10, exclude_robot=1) is False
        assert rt.is_free(2, 2, 10, exclude_robot=None) is False


class TestINVR1NoDoubleReservation:
    """INV-R1: Keine zwei Roboter auf derselben Zelle zur selben Zeit."""

    def test_no_double_reservation_same_cell_same_time(self, reservation_table):
        """Zwei verschiedene Roboter können nicht gleiche Zelle zur gleichen Zeit reservieren."""
        rt = reservation_table

        assert rt.reserve(robot_id=0, x=2, y=2, t=10) is True
        assert rt.reserve(robot_id=1, x=2, y=2, t=10) is False  # Konflikt!
        assert rt.get_blocking_robot(2, 2, 10) == 0

    def test_same_cell_different_times_ok(self, reservation_table):
        """Gleiche Zelle zu verschiedenen Zeiten = OK."""
        rt = reservation_table

        assert rt.reserve(robot_id=0, x=2, y=2, t=10) is True
        assert rt.reserve(robot_id=1, x=2, y=2, t=11) is True  # Andere Zeit = OK

    def test_different_cells_same_time_ok(self, reservation_table):
        """Verschiedene Zellen zur gleichen Zeit = OK."""
        rt = reservation_table

        assert rt.reserve(robot_id=0, x=0, y=0, t=10) is True
        assert rt.reserve(robot_id=1, x=1, y=1, t=10) is True  # Andere Zelle = OK


class TestReservePathAtomic:
    """Atomare Pfad-Reservierung mit Rollback bei Konflikt."""

    def test_reserve_simple_path(self, reservation_table):
        """Einfacher Pfad wird komplett reserviert."""
        rt = reservation_table

        path = [(0, 0), (1, 0), (2, 0), (3, 0)]
        success, conflict = rt.reserve_path(robot_id=0, path=path, start_time=0)

        assert success is True
        assert conflict is None

        # Alle Positionen reserviert
        for i, (x, y) in enumerate(path):
            assert rt.is_free(x, y, i, exclude_robot=None) is False
            assert rt.get_blocking_robot(x, y, i) == 0

    def test_reserve_path_atomic_rollback(self, reservation_table):
        """Bei Konflikt wird KEIN Teil des Pfads reserviert (atomare Operation)."""
        rt = reservation_table

        # Roboter 0 blockiert Position (3, 0) zur Zeit 3
        rt.reserve(robot_id=99, x=3, y=0, t=3)

        # Roboter 1 versucht Pfad, der diese Position kreuzt
        path = [(1, 0), (2, 0), (3, 0), (4, 0)]  # t=1, t=2, t=3 (Konflikt!), t=4
        success, conflict = rt.reserve_path(robot_id=1, path=path, start_time=1)

        assert success is False
        assert conflict is not None
        assert conflict["position"] == (3, 0)
        assert conflict["time"] == 3
        assert conflict["blocking_robot"] == 99

        # WICHTIG: Keine Reservierung von Roboter 1 darf existieren!
        assert rt.get_reservations_for_robot(1) == []

        # Roboter 1 hat NICHTS reserviert, auch nicht die konfliktfreien Zellen
        assert rt.is_free(1, 0, 1, exclude_robot=None) is True
        assert rt.is_free(2, 0, 2, exclude_robot=None) is True

    def test_reserve_empty_path(self, reservation_table):
        """Leerer Pfad = Erfolg, keine Reservierungen."""
        rt = reservation_table

        success, conflict = rt.reserve_path(robot_id=0, path=[], start_time=0)

        assert success is True
        assert conflict is None


class TestINVR2HeadOnCollision:
    """INV-R2: Head-on Collision Detection."""

    def test_head_on_collision_detection(self, reservation_table):
        """A→B und B→A gleichzeitig = Head-on Collision."""
        rt = reservation_table

        # Roboter 0: (0,0) → (1,0) zur Zeit t=0→1
        rt.reserve(robot_id=0, x=0, y=0, t=0)
        rt.reserve(robot_id=0, x=1, y=0, t=1)

        # Roboter 1: (1,0) → (0,0) zur Zeit t=0→1 = Head-on!
        path_robot1 = [(1, 0), (0, 0)]
        success, conflict = rt.reserve_path(robot_id=1, path=path_robot1, start_time=0)

        # Muss als Konflikt erkannt werden
        assert success is False
        assert conflict is not None
        # Die genaue Fehlermeldung hängt von der Implementierung ab
        # Entweder collision_type="head_on" oder normaler Positionskonflikt

    def test_no_head_on_if_different_times(self, reservation_table):
        """Kein Head-on, wenn Zeiten nicht überlappen."""
        rt = reservation_table

        # Roboter 0: (0,0) → (1,0) zur Zeit t=0→1
        rt.reserve(robot_id=0, x=0, y=0, t=0)
        rt.reserve(robot_id=0, x=1, y=0, t=1)

        # Roboter 1: (1,0) → (0,0) zur Zeit t=5→6 = Kein Konflikt
        path_robot1 = [(1, 0), (0, 0)]
        success, conflict = rt.reserve_path(robot_id=1, path=path_robot1, start_time=5)

        assert success is True

class TestINVR3SwapCollision:
    """INV-R3: Swap-Collision (Positionstausch gleichzeitig)."""

    def test_swap_collision_detection(self, reservation_table):
        """
        Zwei Roboter tauschen gleichzeitig benachbarte Positionen.

        Szenario:
        - Roboter 0: (0,0) → (0,1)
        - Roboter 1: (0,1) → (0,0)
        """
        rt = reservation_table

        # Roboter 0 reserviert Pfad (0,0)->(0,1) ab t=0
        path_robot0 = [(0, 0), (0, 1)]
        success0, conflict0 = rt.reserve_path(robot_id=0, path=path_robot0, start_time=0)
        assert success0 is True
        assert conflict0 is None

        # Roboter 1 versucht den "gespiegelten" Pfad zur gleichen Zeit
        path_robot1 = [(0, 1), (0, 0)]
        success1, conflict1 = rt.reserve_path(robot_id=1, path=path_robot1, start_time=0)

        # Muss als Konflikt erkannt werden (Swap-Collision / Head-on-Variante)
        assert success1 is False
        assert conflict1 is not None
        assert conflict1.get("position") in {(0, 0), (0, 1)}


class TestRelease:
    """Freigabe von Reservierungen."""

    def test_release_single(self, reservation_table):
        """Einzelne Reservierung freigeben."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=2, y=2, t=10)
        rt.release(robot_id=0, x=2, y=2, t=10)

        assert rt.is_free(2, 2, 10, exclude_robot=None) is True

    def test_release_all(self, reservation_table):
        """Alle Reservierungen eines Roboters freigeben."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=0, y=0, t=0)
        rt.reserve(robot_id=0, x=1, y=0, t=1)
        rt.reserve(robot_id=0, x=2, y=0, t=2)

        rt.release_all(robot_id=0)

        assert rt.is_free(0, 0, 0, exclude_robot=None) is True
        assert rt.is_free(1, 0, 1, exclude_robot=None) is True
        assert rt.is_free(2, 0, 2, exclude_robot=None) is True
        assert rt.get_reservations_for_robot(0) == []


class TestCleanup:
    """Speicher-Management mit cleanup_before."""

    def test_cleanup_removes_old_reservations(self, reservation_table):
        """cleanup_before entfernt alte Reservierungen."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=0, y=0, t=5)
        rt.reserve(robot_id=0, x=1, y=0, t=10)
        rt.reserve(robot_id=0, x=2, y=0, t=15)

        rt.cleanup_before(current_time=12)

        # t=5 und t=10 sollten weg sein
        assert rt.is_free(0, 0, 5, exclude_robot=None) is True
        assert rt.is_free(1, 0, 10, exclude_robot=None) is True
        # t=15 sollte bleiben
        assert rt.is_free(2, 0, 15, exclude_robot=None) is False

    def test_cleanup_updates_robot_reservations(self, reservation_table):
        """cleanup_before aktualisiert auch robot_reservations dict."""
        rt = reservation_table

        rt.reserve(robot_id=0, x=0, y=0, t=5)
        rt.reserve(robot_id=0, x=1, y=0, t=20)

        assert len(rt.get_reservations_for_robot(0)) == 2

        rt.cleanup_before(current_time=10)

        # Nur noch eine Reservierung übrig
        remaining = rt.get_reservations_for_robot(0)
        assert len(remaining) == 1
        assert (1, 0, 20) in remaining


class TestPickstationPositions:
    """Positionen außerhalb des Grids (für Pickstations)."""

    def test_negative_x_allowed(self, reservation_table):
        """Negative x-Werte (Pickstation links vom Grid) sind erlaubt."""
        rt = reservation_table

        success = rt.reserve(robot_id=0, x=-1, y=2, t=10)

        assert success is True
        assert rt.is_free(-1, 2, 10, exclude_robot=None) is False