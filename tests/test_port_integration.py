# tests/test_port_integration.py

import pytest

from config.simulation_config import SimulationConfig
from simulation.simulation_engine import SimulationEngine
from state.storage_grid import StorageGrid
from utils.port_buffer_zone import calculate_buffer_zone


def _build_engine(width, depth, num_pickstations=2):
    config = SimulationConfig()
    config.grid_width = width
    config.grid_depth = depth
    config.num_pickstations = num_pickstations
    # Sicherstellen, dass Initialisierung läuft
    config.init_strategy = "random_distribution"
    # Bin-Request-Strategie, damit _determine_hot_bin_ids robust ist
    config.bin_request_prob_strategy = "uniform"
    return SimulationEngine(config)


def test_port_positions_calculated_correctly_landscape():
    """
    Grid 20x30 (width=20, depth=30):
    - Längere Seite = depth (30)
    - Ports an: x=0 und x=19
    - y-Position = 15
    """
    engine = _build_engine(width=20, depth=30, num_pickstations=2)
    positions = {ps.position for ps in engine.state.get_all_pickstations()}

    assert (0, 15) in positions
    assert (19, 15) in positions
    assert len(positions) == 2


def test_port_positions_calculated_correctly_portrait():
    """
    Grid 30x20 (width=30, depth=20):
    - Längere Seite = width (30)
    - Ports an: y=0 und y=19
    - x-Position = 15
    """
    engine = _build_engine(width=30, depth=20, num_pickstations=2)
    positions = {ps.position for ps in engine.state.get_all_pickstations()}

    assert (15, 0) in positions
    assert (15, 19) in positions
    assert len(positions) == 2


def test_port_positions_calculated_correctly_square():
    """
    Grid 20x20 (width=20, depth=20):
    - Beide Seiten gleich → wir verwenden depth >= width → links/rechts
    - Ports an: x=0 und x=19
    - y-Position = 10
    """
    engine = _build_engine(width=20, depth=20, num_pickstations=2)
    positions = {ps.position for ps in engine.state.get_all_pickstations()}

    assert (0, 10) in positions
    assert (19, 10) in positions
    assert len(positions) == 2


def test_grid_has_no_stack_at_port():
    width, depth = 20, 30
    mid_y = depth // 2
    port_positions = {(0, mid_y), (width - 1, mid_y)}

    grid = StorageGrid(width, depth, port_positions=port_positions)

    for (x, y) in port_positions:
        assert grid.get_stack(x, y) is None


def test_grid_is_port_position():
    width, depth = 10, 10
    port_positions = {(0, 5), (9, 5)}
    grid = StorageGrid(width, depth, port_positions=port_positions)

    # Ports
    assert grid.is_port_position(0, 5)
    assert grid.is_port_position(9, 5)

    # Andere Positionen
    assert not grid.is_port_position(1, 5)
    assert not grid.is_port_position(0, 4)

    # is_storage_position entsprechend
    assert not grid.is_storage_position(0, 5)  # Port
    assert grid.is_storage_position(1, 5)      # Normaler Storage
    assert not grid.is_storage_position(-1, 5) # Außerhalb Grid


def test_all_stacks_excludes_ports():
    width, depth = 8, 6
    mid_y = depth // 2
    port_positions = {(0, mid_y), (width - 1, mid_y)}

    grid = StorageGrid(width, depth, port_positions=port_positions)

    all_stacks = list(grid.all_stacks())
    assert len(all_stacks) == width * depth - 2


def test_pickstation_position_is_valid_grid_coordinate():
    width, depth = 20, 30
    engine = _build_engine(width=width, depth=depth, num_pickstations=2)

    grid = engine.state.grid
    for pickstation in engine.state.get_all_pickstations():
        x, y = pickstation.position
        assert 0 <= x < grid.width
        assert 0 <= y < grid.depth


# ---------------------------------------------------------------------------
# Neue Tests für Port-Pufferzonen & Storage-Validierung
# ---------------------------------------------------------------------------

def test_buffer_zone_calculation_single_port():
    """
    Port bei (5, 5) in 10x10 Grid.
    Erwartete Pufferzone: (5,5), (4,5), (6,5), (5,4), (5,6)
    """
    width, depth = 10, 10
    port_positions = [(5, 5)]

    buffer_zone = calculate_buffer_zone(
        port_positions=port_positions,
        grid_width=width,
        grid_depth=depth,
    )

    expected = {(5, 5), (4, 5), (6, 5), (5, 4), (5, 6)}
    for pos in expected:
        assert pos in buffer_zone

    assert len(buffer_zone) == len(expected)


def test_buffer_zone_respects_grid_boundaries():
    """
    Port bei (0, 5) (am linken Rand).
    Pufferzone darf keine Positionen mit x < 0 enthalten.
    """
    width, depth = 10, 10
    port_positions = [(0, 5)]

    buffer_zone = calculate_buffer_zone(
        port_positions=port_positions,
        grid_width=width,
        grid_depth=depth,
    )

    assert (-1, 5) not in buffer_zone
    assert (0, 5) in buffer_zone
    assert (1, 5) in buffer_zone


def test_buffer_zone_two_ports_overlap():
    """
    Zwei Ports in 10x10 Grid:
    - (0, 5) und (9, 5)
    Beide Pufferzonen werden korrekt berechnet, Überlappung ist erlaubt.
    """
    width, depth = 10, 10
    port_positions = [(0, 5), (9, 5)]

    buffer_zone = calculate_buffer_zone(
        port_positions=port_positions,
        grid_width=width,
        grid_depth=depth,
    )

    # Stichproben für beide Seiten
    for pos in [(0, 5), (1, 5), (0, 4), (0, 6),
                (9, 5), (8, 5), (9, 4), (9, 6)]:
        assert pos in buffer_zone


def test_placement_strategy_avoids_buffer_zone():
    """
    Placement-Strategien nutzen nur Positionen, die state.is_valid_storage_position
    als gültig markiert – damit werden Pufferzonen effektiv ausgeschlossen.
    """
    from strategies.target_bin_placement_selector import PlacementSelector

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

    class DummyState:
        def __init__(self, grid, valid_positions, max_stack_height=None):
            self.grid = grid
            self.max_stack_height = max_stack_height
            self.bins = []
            self.config = type("Cfg", (), {})()
            self._valid_positions = set(valid_positions)

        def is_valid_storage_position(self, x, y):
            return (x, y) in self._valid_positions

    # Zwei Stacks: einer in der Pufferzone, einer erlaubt
    forbidden_pos = (5, 5)
    allowed_pos = (2, 2)

    stacks = [
        DummyStack(stack_id=forbidden_pos, height_val=0, locked=False),
        DummyStack(stack_id=allowed_pos, height_val=0, locked=False),
    ]
    grid = DummyGrid(stacks)
    state = DummyState(grid=grid, valid_positions={allowed_pos}, max_stack_height=5)

    config = type("Cfg", (), {})()
    config.placement_strategy = "RANDOM"
    selector = PlacementSelector(config=config)

    # Mehrfach prüfen, dass niemals die verbotene Position gewählt wird
    for _ in range(20):
        stack = selector._select_random_stack(state)
        assert stack.stack_id == allowed_pos


def test_relocation_avoids_buffer_zone():
    """
    Buffer-Stacks für temporäre Umlagerung dürfen nicht in der Pufferzone liegen.
    """
    from strategies.relocation_selection import RelocationSelection

    class DummyStack:
        def __init__(self, stack_id, height_val=0, locked=False):
            self.stack_id = stack_id
            self._height = height_val
            self._locked = locked
            self.bins = []

        def height(self):
            return self._height

        def is_locked(self):
            return self._locked

    class DummyGrid:
        def __init__(self, stacks):
            self._stacks = list(stacks)

        def all_stacks(self):
            return list(self._stacks)

    class DummyState:
        def __init__(self, grid, valid_positions, max_stack_height=None):
            self.grid = grid
            self.max_stack_height = max_stack_height
            self.bins = []
            self.config = type("Cfg", (), {})()
            self._valid_positions = set(valid_positions)

        def get_bin_by_id(self, bin_id):
            return None

        def is_valid_storage_position(self, x, y):
            return (x, y) in self._valid_positions

    forbidden_pos = (3, 3)
    allowed_pos = (1, 1)

    source_stack = DummyStack(stack_id=(0, 0), height_val=1)
    forbidden_stack = DummyStack(stack_id=forbidden_pos, height_val=0)
    allowed_stack = DummyStack(stack_id=allowed_pos, height_val=0)

    grid = DummyGrid([source_stack, forbidden_stack, allowed_stack])
    state = DummyState(grid=grid, valid_positions={allowed_pos}, max_stack_height=5)

    selector = RelocationSelection()

    target_stack = selector.select_temporary_stack(state, source_stack)

    assert target_stack.stack_id == allowed_pos


def test_is_valid_storage_position():
    """
    Integrationstest:
    - Port-Position → False
    - Pufferzonen-Position → False
    - Normale Position → True
    """
    width, depth = 10, 10
    engine = _build_engine(width=width, depth=depth, num_pickstations=2)
    state = engine.state

    # Port-Positionen aus dem State
    port_positions = set(state.port_positions)
    assert port_positions, "Expected at least one port position"

    # 1) Port-Positionen sind ungültig
    for (x, y) in port_positions:
        assert state.is_valid_storage_position(x, y) is False

    # 2) Pufferzonen-Position (Distanz 1) ist ebenfalls ungültig
    #    Wir nehmen eine Nachbarposition eines Ports, falls innerhalb des Grids.
    grid = state.grid
    buffer_zone = state.buffer_zone

    # Finde eine Position, die in der Pufferzone liegt, aber kein Port ist
    buffer_only_pos = None
    for pos in buffer_zone:
        if pos not in port_positions:
            buffer_only_pos = pos
            break

    assert buffer_only_pos is not None, "Expected at least one pure buffer-zone position"
    bx, by = buffer_only_pos
    assert state.is_valid_storage_position(bx, by) is False

    # 3) Normale Position (nicht Port, nicht in Pufferzone) ist gültig
    normal_pos = None
    for x in range(grid.width):
        for y in range(grid.depth):
            if (x, y) not in port_positions and (x, y) not in buffer_zone:
                normal_pos = (x, y)
                break
        if normal_pos is not None:
            break

    assert normal_pos is not None, "Expected at least one normal storage position"
    nx, ny = normal_pos
    assert state.is_valid_storage_position(nx, ny) is True