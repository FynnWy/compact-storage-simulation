# tests/test_highway_rules.py
"""
Unit-Tests für HighwayRules.

Ziel:
- Sicherstellen, dass die verschiedenen Patterns sinnvolle preferred_directions liefern.
- Prüfen, dass get_direction_penalty korrekt zwischen bevorzugter und
  „falscher“ Richtung unterscheidet.
"""

from traffic.highway_rules import HighwayRules


class TestHighwayRingPattern:
    def test_ring_pattern_top_row_prefers_right(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="ring")

        # Obere linke Ecke (0,0): sollte nach rechts bevorzugen
        dirs = hw.get_preferred_directions(0, 0)
        assert (1, 0) in dirs

        # Obere rechte Ecke (4,0): sollte nach unten bevorzugen
        dirs_top_right = hw.get_preferred_directions(4, 0)
        assert (0, 1) in dirs_top_right

    def test_ring_penalty_zero_for_preferred_direction(self):
        hw = HighwayRules(grid_width=3, grid_depth=3, pattern="ring")

        # (0,0) → nach rechts ist bevorzugt
        penalty = hw.get_direction_penalty(0, 0, 1, 0)
        assert penalty == 0

    def test_ring_penalty_positive_for_wrong_direction(self):
        hw = HighwayRules(grid_width=3, grid_depth=3, pattern="ring")
        hw.wrong_direction_penalty = 7

        # (0,0): nach links (-1,0) ist nicht bevorzugt
        penalty = hw.get_direction_penalty(0, 0, -1, 0)
        assert penalty == 7


class TestHighwayRowPattern:
    def test_rows_even_row_prefers_right(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="rows")

        # y=0 (gerade Reihe) -> nach rechts (1,0) bevorzugt
        dirs = hw.get_preferred_directions(2, 0)
        assert (1, 0) in dirs

    def test_rows_odd_row_prefers_left(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="rows")

        # y=1 (ungerade Reihe) -> nach links (-1,0) bevorzugt
        dirs = hw.get_preferred_directions(2, 1)
        assert (-1, 0) in dirs

    def test_rows_penalty_respects_pattern(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="rows")
        hw.wrong_direction_penalty = 3

        # Gerade Reihe (y=0): rechts ist bevorzugt, links bestraft
        assert hw.get_direction_penalty(2, 0, 1, 0) == 0
        assert hw.get_direction_penalty(2, 0, -1, 0) == 3


class TestHighwayLanePattern:
    def test_lanes_even_column_prefers_down(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="lanes")

        # x=0 (gerade Spalte) -> nach unten (0,1) bevorzugt
        dirs = hw.get_preferred_directions(0, 2)
        assert (0, 1) in dirs

    def test_lanes_odd_column_prefers_up(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="lanes")

        # x=1 (ungerade Spalte) -> nach oben (0,-1) bevorzugt
        dirs = hw.get_preferred_directions(1, 2)
        assert (0, -1) in dirs

    def test_lanes_penalty_for_wrong_vertical_direction(self):
        hw = HighwayRules(grid_width=5, grid_depth=5, pattern="lanes")
        hw.wrong_direction_penalty = 4

        # Gerade Spalte (x=0): runter (0,1) bevorzugt, hoch (0,-1) bestraft
        assert hw.get_direction_penalty(0, 2, 0, 1) == 0
        assert hw.get_direction_penalty(0, 2, 0, -1) == 4


class TestHighwayNonePattern:
    def test_none_pattern_all_directions_preferred(self):
        hw = HighwayRules(grid_width=3, grid_depth=3, pattern="none")

        dirs = hw.get_preferred_directions(1, 1)
        # Alle vier Richtungen sollten gleichberechtigt sein
        for move in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            assert move in dirs

    def test_none_pattern_zero_penalty_for_all_directions(self):
        hw = HighwayRules(grid_width=3, grid_depth=3, pattern="none")
        hw.wrong_direction_penalty = 10  # sollte aber nie greifen

        for move in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            assert hw.get_direction_penalty(1, 1, *move) == 0