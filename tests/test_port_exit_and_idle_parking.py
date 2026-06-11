# tests/test_port_exit_and_idle_parking.py

import pytest

from traffic.port_exit_guard import PortExitGuard
from traffic.idle_parking import IdleParkingManager
from utils.port_buffer_zone import calculate_buffer_zone


class TestPortExitGuard:
    def test_count_free_exits(self):
        """
        1. test_count_free_exits:
           - Port mit 4 Nachbarn, 0 blockiert → 4 frei
           - Port mit 4 Nachbarn, 3 blockiert → 1 frei
        """
        guard = PortExitGuard(grid_width=5, grid_depth=5)
        port_pos = (2, 2)
        port_positions = {port_pos}

        # Keine Blockierung
        free_0 = guard.count_free_exits(
            port_position=port_pos,
            blocked_positions=set(),
            port_positions=port_positions,
        )
        assert free_0 == 4

        # Drei Nachbarn blockiert
        neighbors = guard.get_neighbor_positions(port_pos)
        blocked_positions = set(neighbors[:3])

        free_1 = guard.count_free_exits(
            port_position=port_pos,
            blocked_positions=blocked_positions,
            port_positions=port_positions,
        )
        assert free_1 == 1

    def test_would_block_last_exit(self):
        """
        2. test_would_block_last_exit:
           - 1 Exit frei, Robot auf Port → True
           - 2 Exits frei, Robot auf Port → False
           - 1 Exit frei, kein Robot auf Port → False
        """
        guard = PortExitGuard(grid_width=5, grid_depth=5)
        port_pos = (2, 2)
        port_positions = {port_pos}

        neighbors = guard.get_neighbor_positions(port_pos)

        # Fall 1: 1 Exit frei, Robot auf Port → True
        blocked_positions = set(neighbors[:3])
        last_free = neighbors[3]

        assert guard.would_block_last_exit(
            proposed_position=last_free,
            port_position=port_pos,
            current_blocked=blocked_positions,
            port_positions=port_positions,
            robot_on_port=True,
        )

        # Fall 2: 2 Exits frei, Robot auf Port → False
        blocked_positions = set(neighbors[:2])
        still_free = neighbors[2]

        assert not guard.would_block_last_exit(
            proposed_position=still_free,
            port_position=port_pos,
            current_blocked=blocked_positions,
            port_positions=port_positions,
            robot_on_port=True,
        )

        # Fall 3: 1 Exit frei, kein Robot auf Port → False
        blocked_positions = set(neighbors[:3])
        last_free = neighbors[3]

        assert not guard.would_block_last_exit(
            proposed_position=last_free,
            port_position=port_pos,
            current_blocked=blocked_positions,
            port_positions=port_positions,
            robot_on_port=False,
        )


class TestIdleParking:
    def test_idle_parking_excludes_buffer_zone(self):
        """
        3. test_idle_parking_excludes_buffer_zone:
           - Parkposition in Pufferzone → invalid
           - Parkposition außerhalb → valid
        """
        grid_width, grid_depth = 5, 5
        port_positions = {(2, 2)}
        buffer_zone = calculate_buffer_zone(
            port_positions=list(port_positions),
            grid_width=grid_width,
            grid_depth=grid_depth,
        )

        manager = IdleParkingManager(
            grid_width=grid_width,
            grid_depth=grid_depth,
            port_positions=port_positions,
            buffer_zone=buffer_zone,
        )

        # Eine Position sicher in der Pufferzone (z.B. Port selbst)
        in_buffer = (2, 2)
        assert in_buffer in buffer_zone
        assert not manager.is_valid_parking_position(in_buffer)

        # Eine Position sicher außerhalb der Pufferzone
        outside = (0, 0)
        assert outside not in buffer_zone
        assert manager.is_valid_parking_position(outside)

    def test_idle_robot_leaves_buffer_zone(self):
        """
        4. test_idle_robot_leaves_buffer_zone:
           - Idle-Robot in Pufferzone → muss verlassen
        """
        grid_width, grid_depth = 5, 5
        port_positions = {(2, 2)}
        buffer_zone = calculate_buffer_zone(
            port_positions=list(port_positions),
            grid_width=grid_width,
            grid_depth=grid_depth,
        )

        manager = IdleParkingManager(
            grid_width=grid_width,
            grid_depth=grid_depth,
            port_positions=port_positions,
            buffer_zone=buffer_zone,
        )

        in_buffer = (2, 3)  # Nachbar des Ports → sicher in der Pufferzone
        assert in_buffer in buffer_zone
        assert manager.must_leave_current_position(in_buffer)

        outside = (0, 0)
        assert not manager.must_leave_current_position(outside)