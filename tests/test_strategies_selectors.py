# tests/test_strategies_selectors.py
"""
Unit-Tests für ReorderingSelector und PlacementSelector.

Ziel:
- Reordering-Strategien (LOFI / ABC / POPULARITY) deterministisch prüfen.
- Placement-Strategien (ORIGINAL / RANDOM / ABC / POPULARITY) isoliert testen.
"""
import math
import numpy as np

import pytest

from strategies.reordering_blocking_bins_selector import ReorderingSelector
from strategies.target_bin_placement_selector import PlacementSelector
from strategies.top_access_strategy import TopAccessStrategy
from simulation.robot_task import RobotTask
from strategies.relocation_selection import RelocationSelection

# ---------------------------------------------------------------------------
# Test-Dummies
# ---------------------------------------------------------------------------

class DummyBin:
    def __init__(self, bin_id, abc_class=None, access_count=0, status="in_storage"):
        self.bin_id = bin_id
        self._abc_class = abc_class
        self._access_count = access_count
        self._status = status

    def get_abc_class(self):
        return self._abc_class

    def get_access_count(self):
        return self._access_count

    def get_status(self):
        return self._status


class DummyStack:
    def __init__(self, stack_id, height_val=0, locked=False):
        self.stack_id = stack_id
        self._height = height_val
        self._locked = locked

    def height(self):
        return self._height

    def is_locked(self):
        return self._locked


class DummyGrid:
    def __init__(self, stacks):
        self._stacks = list(stacks)

    def all_stacks(self):
        return list(self._stacks)

    def get_stack(self, x, y):
        for s in self._stacks:
            if isinstance(s.stack_id, tuple) and s.stack_id == (x, y):
                return s
        return None


class DummyConfig:
    def __init__(self):
        # Defaults – Tests setzen je nach Bedarf
        self.reordering_strategy = "LOFI"
        self.placement_strategy = "ORIGINAL"
        self.popularity_warmup_requests = 0
        self.popularity_hot_threshold = 0.7
        self.popularity_cold_threshold = 0.3
        self.popularity_distance_weight = 0.5
        self.popularity_depth_weight = 0.5
        # NEU: Flag für Ordered Return von Blocking-Bins
        self.return_blocking_bins = True


class DummyState:
    def __init__(self, grid, bins, max_stack_height=None):
        self.grid = grid
        self.bins = list(bins)
        self.max_stack_height = max_stack_height
        self.config = DummyConfig()
        self.pickstations = []  # NEU: Für distance_helpers benötigt

    def get_bin_by_id(self, bin_id):
        for b in self.bins:
            if getattr(b, "bin_id", None) == bin_id:
                return b
        return None


# ---------------------------------------------------------------------------
# ReorderingSelector
# ---------------------------------------------------------------------------

class TestReorderingSelectorLOFI:
    def test_lofi_reverses_blockers(self):
        config = DummyConfig()
        config.reordering_strategy = "LOFI"
        selector = ReorderingSelector(config)

        blockers = [DummyBin(0), DummyBin(1), DummyBin(2)]
        result = selector.reorder_blockers(blockers)

        assert [b.bin_id for b in result] == [2, 1, 0]


class TestReorderingSelectorABC:
    def test_abc_orders_by_class(self):
        """
        C-Bins zuerst (landen unten), dann B, dann A (landet oben).
        """
        config = DummyConfig()
        config.reordering_strategy = "ABC"
        selector = ReorderingSelector(config)

        # Ursprungsreihenfolge: A, C, B, A
        blockers = [
            DummyBin(0, abc_class="A"),
            DummyBin(1, abc_class="C"),
            DummyBin(2, abc_class="B"),
            DummyBin(3, abc_class="A"),
        ]

        result = selector.reorder_blockers(blockers)
        classes = [b.get_abc_class() for b in result]

        # Erwartet: erst alle C, dann B, dann A
        assert classes == ["C", "B", "A", "A"]


class TestReorderingSelectorPopularity:
    def test_popularity_orders_by_access_count(self):
        """
        Bins mit niedrigem access_count zuerst (landen unten).
        """
        config = DummyConfig()
        config.reordering_strategy = "POPULARITY"
        selector = ReorderingSelector(config)

        blockers = [
            DummyBin(0, access_count=5),
            DummyBin(1, access_count=1),
            DummyBin(2, access_count=10),
        ]

        result = selector.reorder_blockers(blockers)
        counts = [b.get_access_count() for b in result]

        assert counts == [1, 5, 10]


# ---------------------------------------------------------------------------
# PlacementSelector
# ---------------------------------------------------------------------------

class TestPlacementSelectorOriginal:
    def test_original_stack_ok(self):
        """
        ORIGINAL-Strategie gibt den Original-Stack zurück, wenn er existiert,
        nicht gelocked und nicht voll ist.
        """
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=0),
            DummyStack(stack_id=(1, 0), height_val=1),
        ]
        grid = DummyGrid(stacks)
        bins = []
        state = DummyState(grid=grid, bins=bins, max_stack_height=5)

        config = DummyConfig()
        config.placement_strategy = "ORIGINAL"

        selector = PlacementSelector(config=config)

        original_stack = selector.select_return_stack(
            state=state,
            bin_obj=DummyBin(bin_id=0),
            original_stack_id=(1, 0),
        )

        assert original_stack.stack_id == (1, 0)

    def test_original_stack_raises_if_locked(self):
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=0),
            DummyStack(stack_id=(1, 0), height_val=1, locked=True),
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[], max_stack_height=5)

        config = DummyConfig()
        config.placement_strategy = "ORIGINAL"
        selector = PlacementSelector(config=config)

        with pytest.raises(RuntimeError):
            selector.select_return_stack(
                state=state,
                bin_obj=DummyBin(bin_id=0),
                original_stack_id=(1, 0),
            )

    def test_original_stack_raises_if_full(self):
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=5),
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[], max_stack_height=5)

        config = DummyConfig()
        config.placement_strategy = "ORIGINAL"
        selector = PlacementSelector(config=config)

        with pytest.raises(RuntimeError):
            selector.select_return_stack(
                state=state,
                bin_obj=DummyBin(bin_id=0),
                original_stack_id=(0, 0),
            )


class TestPlacementSelectorRandom:
    def test_random_picks_only_eligible_stacks(self):
        """
        RANDOM-Strategie darf nur nicht-volle und nicht-gelockte Stacks wählen.
        """
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=5, locked=False),  # voll, wenn max=5
            DummyStack(stack_id=(1, 0), height_val=2, locked=False),
            DummyStack(stack_id=(2, 0), height_val=1, locked=True),
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[], max_stack_height=5)

        config = DummyConfig()
        config.placement_strategy = "RANDOM"
        selector = PlacementSelector(config=config)

        # Führe Auswahl mehrfach aus und prüfe, dass nie ein unzulässiger Stack kommt
        for _ in range(20):
            stack = selector._select_random_stack(state)
            assert stack.stack_id == (1, 0)


class TestPlacementSelectorABC:
    def test_abc_prefers_near_and_shallow_for_A(self, monkeypatch):
        """
        Für A-Bins: Kombination aus Distanz zur Pickstation und Tiefe wird minimiert.

        Wir mocken get_min_distance_to_pickstation, um deterministische Distanzen
        für jede Stack-Position zu liefern.
        """
        from utils import distance_helpers

        # Stacks an drei Positionen
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=3),  # tief, aber nah
            DummyStack(stack_id=(5, 0), height_val=0),  # leer, aber weit weg
            DummyStack(stack_id=(2, 0), height_val=1),  # mittel
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(0, abc_class="A")], max_stack_height=5)

        # Mock für get_min_distance_to_pickstation
        def fake_distance(state_arg, pos):
            x, y = pos
            # Einfachheit: Distanz = |x|
            return abs(x)

        monkeypatch.setattr(distance_helpers, "get_min_distance_to_pickstation", fake_distance)

        config = DummyConfig()
        config.placement_strategy = "ABC"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=None,
        )

        # Erwartung: Stack mit kleinstem (distance + depth) Score
        # (0,0): dist=0, depth=3 -> 3
        # (2,0): dist=2, depth=1 -> 3
        # (5,0): dist=5, depth=0 -> 5
        # Die ersten beiden sind gleich gut, einer von beiden ist also ok.
        assert stack.stack_id in {(0, 0), (2, 0)}


class TestPlacementSelectorPopularity:
    def test_popularity_uses_random_in_warmup(self, monkeypatch):
        """
        Solange total_accesses < warmup_requests, wird RANDOM als Fallback genutzt.
        Wir prüfen: ausgewählter Stack ist einfach einer der zulässigen Kandidaten.
        """
        # Zwei Stacks, beide zulässig
        stacks = [
            DummyStack(stack_id=(0, 0), height_val=0),
            DummyStack(stack_id=(1, 0), height_val=0),
        ]
        grid = DummyGrid(stacks)

        # Eine Bin mit sehr wenig Zugriffen -> Warmup
        bins = [DummyBin(0, access_count=0)]
        state = DummyState(grid=grid, bins=bins, max_stack_height=5)

        config = DummyConfig()
        config.placement_strategy = "POPULARITY"
        config.popularity_warmup_requests = 10  # groß genug, dass wir im Warmup bleiben
        selector = PlacementSelector(config=config)

        # Wir wollen hier nur sicherstellen, dass KEIN Fehler auftritt
        # und dass der gewählte Stack gültig ist.
        for _ in range(10):
            stack = selector.select_return_stack(
                state=state,
                bin_obj=bins[0],
                original_stack_id=None,
            )
            assert stack.stack_id in {(0, 0), (1, 0)}


    def test_popularity_hot_bin_prefers_low_score_stack(self, monkeypatch):
        """
        Hot Bin (hohe Popularität) soll Stack mit minimalem Score wählen.
        Score = alpha * dist_norm + beta * depth_norm.
        """
        from utils import distance_helpers

        stacks = [
            DummyStack(stack_id=(0, 0), height_val=4),  # nah, aber tief
            DummyStack(stack_id=(4, 0), height_val=0),  # weit, aber leer
        ]
        grid = DummyGrid(stacks)

        # Eine "heiße" Bin mit hohem access_count
        hot_bin = DummyBin(0, access_count=100)
        cold_bin = DummyBin(1, access_count=1)
        state = DummyState(grid=grid, bins=[hot_bin, cold_bin], max_stack_height=5)

        def fake_distance(state_arg, pos):
            x, y = pos
            return abs(x)

        monkeypatch.setattr(distance_helpers, "get_min_distance_to_pickstation", fake_distance)

        config = DummyConfig()
        config.placement_strategy = "POPULARITY"
        config.popularity_warmup_requests = 0
        config.popularity_hot_threshold = 0.7
        config.popularity_cold_threshold = 0.3
        config.popularity_distance_weight = 0.5
        config.popularity_depth_weight = 0.5

        selector = PlacementSelector(config=config)

        # Popularität = access_count / max_count
        # hot_bin: 100/100 = 1.0 (hot)
        stack_for_hot = selector.select_return_stack(
            state=state,
            bin_obj=hot_bin,
            original_stack_id=None,
        )

        # Normalisierte Distanz:
        # dist(0,0)=0, dist(4,0)=4 -> max_dist=4 -> 0.0 vs 1.0
        # Normalisierte Tiefe:
        # height 4/5=0.8 vs 0/5=0.0
        # Score(0,0)=0.5*0.0 + 0.5*0.8 = 0.4
        # Score(4,0)=0.5*1.0 + 0.5*0.0 = 0.5
        # => (0,0) ist besser für hot
        assert stack_for_hot.stack_id == (0, 0)


class TestReturnBlockingBinsFlag:
    """Tests für return_blocking_bins Konfiguration."""

    def test_blocking_bins_not_returned_when_flag_false(self):
        """
        Mit return_blocking_bins=False dürfen keine Blocker-Return-Actions
        generiert werden – die Blocker bleiben an neuer Position.
        """
        # Setup: Dummy-Grid/State
        stacks = [DummyStack(stack_id=(0, 0), height_val=1)]
        grid = DummyGrid(stacks)
        bins = []
        state = DummyState(grid=grid, bins=bins, max_stack_height=5)
        state.config.return_blocking_bins = False

        # Task mit temp_storage-Einträgen und noch nicht abgeschlossener Pickstation
        task = RobotTask(request=type("R", (), {"request_id": 1, "target_box_id": 0})())
        task.temp_storage = [
            {"bin_id": 10, "from_stack": (0, 0), "buffer_stack": (1, 0)},
        ]
        task.pickstation_completed = False
        task.phase = RobotTask.PHASE_RESTORE_BLOCKERS

        strategy = TopAccessStrategy(
            relocation_selector=None,
            placement_selector=PlacementSelector(config=state.config),
        )

        result = strategy._next_restore_blockers_action(state, task)

        # Es darf keine Action erzeugt werden, stattdessen direkt in WAIT_FOR_PICKSTATION wechseln
        assert result is None
        assert task.temp_storage == []
        assert task.phase == RobotTask.PHASE_WAIT_FOR_PICKSTATION

    def test_blocking_bins_returned_when_flag_true(self):
        """
        Mit return_blocking_bins=True (Default) werden Blocker zurückgelegt.
        """
        stacks = [DummyStack(stack_id=(0, 0), height_val=1)]
        grid = DummyGrid(stacks)
        bins = []
        state = DummyState(grid=grid, bins=bins, max_stack_height=5)
        state.config.return_blocking_bins = True

        task = RobotTask(request=type("R", (), {"request_id": 1, "target_box_id": 0})())
        task.temp_storage = [
            {"bin_id": 10, "from_stack": (0, 0), "buffer_stack": (1, 0)},
        ]
        task.pickstation_completed = False
        task.phase = RobotTask.PHASE_RESTORE_BLOCKERS

        strategy = TopAccessStrategy(
            relocation_selector=None,
            placement_selector=PlacementSelector(config=state.config),
        )

        action = strategy._next_restore_blockers_action(state, task)

        assert action is not None
        assert action["type"] == "return"
        assert action["return_kind"] == "blocker"
        assert action["bin_id"] == 10
        # temp_storage wird erst beim tatsächlichen Ausführen/Markieren reduziert
        assert task.has_blockers_to_restore()

    def test_target_bin_still_returned_when_blockers_not_returned(self):
        """
        Auch wenn Blocking-Bins nicht zurückgelegt werden, muss die
        Target-Bin korrekt zurückgelagert werden.
        """
        # Grid mit einem Rückgabe-Stack
        stacks = [DummyStack(stack_id=(0, 0), height_val=0)]
        grid = DummyGrid(stacks)

        # Target-Bin an der Pickstation
        target_bin = DummyBin(bin_id=5, status="at_pickstation")
        state = DummyState(grid=grid, bins=[target_bin], max_stack_height=5)
        state.config.return_blocking_bins = False

        # Task mit Blockern, aber bereits abgeschlossener Pickstation
        task = RobotTask(request=type("R", (), {"request_id": 1, "target_box_id": 5})())
        task.temp_storage = [
            {"bin_id": 10, "from_stack": (0, 0), "buffer_stack": (1, 0)},
        ]
        task.pickstation_completed = True
        task.target_stack_id = (0, 0)
        task.phase = RobotTask.PHASE_RESTORE_BLOCKERS

        strategy = TopAccessStrategy(
            relocation_selector=None,
            placement_selector=PlacementSelector(config=state.config),
        )

        action = strategy._next_restore_blockers_action(state, task)

        # Blocker wurden verworfen, es wird direkt eine Target-Return-Action geplant
        assert action is not None
        assert action["type"] == "return"
        assert action["return_kind"] == "target"
        assert action["bin_id"] == 5
        assert action["to_stack"] == (0, 0)
        assert task.temp_storage == []
        assert task.phase in (RobotTask.PHASE_RETURN_TARGET, RobotTask.PHASE_COMPLETE)


class TestNearestPlacementStrategy:
    """
    Tests für die NEAREST Placement-Strategie.

    MODELLKORREKTUR (Phase 3B, Befund P3-04):
    Diese Klasse prüfte zuvor „Nähe zur Pickstation". Die verbindliche
    fachliche Entscheidung lautet inzwischen anders:

        NEAREST = nächstgelegener zulässiger Stack relativ zum ORIGINALSTACK
                  der Target-Bin
        Tie-Break: kleinere y-Koordinate, danach kleinere x-Koordinate
        Ist der Originalstack selbst zulässig, gewinnt er mit Distanz 0.

    Die alte Semantik war eine andere Policy („so nah wie möglich an den
    Port") und führte dazu, dass sich die gesamte Rücklagerung auf 8–13
    Stacks konzentrierte. Der Test wurde daher NICHT abgeschwächt, sondern
    auf den heute gültigen Contract umgestellt.
    """

    @staticmethod
    def _make_pickstation(pos):
        return type("PS", (), {"position": pos})()

    def test_nearest_prefers_stack_closest_to_original_stack(self):
        """
        NEAREST wählt den zulässigen Stack mit geringster Distanz zum
        Originalstack – nicht zur Pickstation.
        """
        # Pickstation bei (0, 0), Originalstack bei (10, 10)
        stacks = [
            DummyStack(stack_id=(0, 2), height_val=0, locked=False),  # PS 2  | Origin 18
            DummyStack(stack_id=(3, 0), height_val=0, locked=False),  # PS 3  | Origin 17
            DummyStack(stack_id=(5, 5), height_val=0, locked=False),  # PS 10 | Origin 10
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((0, 0))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=(10, 10),
        )

        # Nach altem Modell hätte (0, 2) gewonnen (Distanz 2 zur Pickstation).
        assert stack.stack_id == (5, 5)

    def test_nearest_returns_the_original_stack_when_admissible(self):
        """Der Originalstack gewinnt mit Distanz 0, sofern zulässig."""
        stacks = [
            DummyStack(stack_id=(0, 1), height_val=0, locked=False),
            DummyStack(stack_id=(4, 4), height_val=0, locked=False),
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((0, 0))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=(4, 4),
        )

        assert stack.stack_id == (4, 4)

    def test_nearest_tie_break_is_y_then_x(self):
        """Bei gleicher Distanz gewinnt kleineres y, danach kleineres x."""
        # Originalstack (2, 2); alle Kandidaten haben Distanz 2.
        stacks = [
            DummyStack(stack_id=(2, 4), height_val=0, locked=False),  # y=4
            DummyStack(stack_id=(4, 2), height_val=0, locked=False),  # y=2, x=4
            DummyStack(stack_id=(0, 2), height_val=0, locked=False),  # y=2, x=0
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((0, 0))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=(2, 2),
        )

        assert stack.stack_id == (0, 2)

    def test_nearest_respects_capacity_and_locks(self):
        """
        NEAREST berücksichtigt nur zulässige Stacks (Kapazität, Lock).
        """
        stacks = [
            DummyStack(stack_id=(0, 1), height_val=5, locked=False),  # voll bei max=5
            DummyStack(stack_id=(1, 0), height_val=0, locked=True),   # gelockt
            DummyStack(stack_id=(1, 1), height_val=0, locked=False),  # zulässig
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((0, 0))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=None,
        )

        assert stack.stack_id == (1, 1)

    def test_nearest_excludes_port_buffer_zone(self):
        """
        Stacks in der Port-Pufferzone werden nicht als Kandidaten betrachtet.
        """
        class DummyStateWithBuffer(DummyState):
            def is_valid_storage_position(self, x, y):
                # (1, 0) liegt in der Pufferzone und ist damit unzulässig
                if (x, y) == (1, 0):
                    return False
                return True

        stacks = [
            DummyStack(stack_id=(1, 0), height_val=0, locked=False),  # wäre nah, aber Pufferzone
            DummyStack(stack_id=(2, 0), height_val=0, locked=False),  # nächster zulässiger Kandidat
        ]
        grid = DummyGrid(stacks)
        state = DummyStateWithBuffer(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((0, 0))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        stack = selector.select_return_stack(
            state=state,
            bin_obj=state.bins[0],
            original_stack_id=None,
        )

        assert stack.stack_id == (2, 0)

    def test_nearest_tiebreak_is_deterministic(self):
        """
        Bei mehreren Stacks mit gleicher Distanz zur Pickstation ist die Auswahl deterministisch.
        """
        # Pickstation bei (1, 1)
        stacks = [
            DummyStack(stack_id=(0, 1), height_val=0, locked=False),  # Distanz 1
            DummyStack(stack_id=(2, 1), height_val=0, locked=False),  # Distanz 1
        ]
        grid = DummyGrid(stacks)
        state = DummyState(grid=grid, bins=[DummyBin(bin_id=0)], max_stack_height=5)
        state.pickstations = [self._make_pickstation((1, 1))]

        config = DummyConfig()
        config.placement_strategy = "NEAREST"
        selector = PlacementSelector(config=config)

        # Mehrfach ausführen, Ergebnis muss immer gleich sein
        for _ in range(20):
            stack = selector.select_return_stack(
                state=state,
                bin_obj=state.bins[0],
                original_stack_id=None,
            )
            # Tie-Break: zuerst y, dann x -> (0, 1) wird immer gewählt
            assert stack.stack_id == (0, 1)


# ---------------------------------------------------------------------------
# Relocation-Tests
# ---------------------------------------------------------------------------

class TestRelocationSelectionRandomForRRRR:
    """
    Tests für Random-Relocation von Blocker-Bins im RR+RR-Setup:

    placement_strategy = "RANDOM"
    return_blocking_bins = False
    """

    class _DummyStack:
        def __init__(self, stack_id, height_val=0, locked=False):
            self.stack_id = stack_id
            self._height = height_val
            self._locked = locked

        def height(self):
            return self._height

        def is_locked(self):
            return self._locked

    class _DummyGrid:
        def __init__(self, stacks):
            self._stacks = list(stacks)

        def all_stacks(self):
            return list(self._stacks)

        def get_stack(self, x, y):
            for s in self._stacks:
                if isinstance(s.stack_id, tuple) and s.stack_id == (x, y):
                    return s
            return None

    class _DummyConfig:
        def __init__(self):
            self.placement_strategy = "RANDOM"
            self.return_blocking_bins = False
            self.max_stack_height = 5

    class _DummyState:
        def __init__(self, grid):
            self.grid = grid
            self.config = TestRelocationSelectionRandomForRRRR._DummyConfig()

        def get_bin_by_id(self, bin_id):
            return None  # für diesen Test nicht benötigt

        @property
        def max_stack_height(self):
            return self.config.max_stack_height

    def test_random_relocation_picks_only_eligible_and_varies(self):
        """
        Im RR+RR-Setup sollen Blocker zufällig auf zulässige Stacks verteilt werden:
        - nur nicht-volle, nicht-gelockte, nicht-Pufferzonen-Stapel
        - bei mehrfachen Aufrufen werden nicht immer dieselben Stacks gewählt
        """
        s0 = self._DummyStack(stack_id=(0, 0), height_val=5, locked=False)  # voll
        s1 = self._DummyStack(stack_id=(1, 0), height_val=0, locked=False)  # zulässig
        s2 = self._DummyStack(stack_id=(2, 0), height_val=0, locked=False)  # zulässig
        s3 = self._DummyStack(stack_id=(3, 0), height_val=0, locked=True)   # gelockt

        grid = self._DummyGrid([s0, s1, s2, s3])
        state = self._DummyState(grid=grid)

        selector = RelocationSelection(rng=np.random.default_rng(123))

        chosen_ids = set()
        for _ in range(50):
            stack = selector.select_temporary_stack(state=state, source_stack=s0)
            # Nur zulässige Stacks
            assert stack.stack_id in {(1, 0), (2, 0)}
            chosen_ids.add(stack.stack_id)

        # Erwartung: bei genügend Versuchen wurden beide zulässigen Stacks mindestens einmal gewählt
        assert chosen_ids == {(1, 0), (2, 0)}