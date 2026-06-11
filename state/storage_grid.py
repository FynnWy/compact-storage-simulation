from state.storage_stack import StorageStack
from typing import Set, Tuple


class StorageGrid:
    def __init__(self, width, depth, port_positions: Set[Tuple[int, int]] = None):
        self.width = width
        self.depth = depth

        # Dictionary: (x, y) → Stack
        self.stacks = {}
        self.port_positions: Set[Tuple[int, int]] = port_positions or set()

        self._initialize_grid()

    def _initialize_grid(self):
        for x in range(self.width):
            for y in range(self.depth):
                if self.is_port_position(x, y):
                    # An Port-Positionen gibt es keinen StorageStack
                    self.stacks[(x, y)] = None
                    continue
                stack_id = f"S_{x}_{y}"
                self.stacks[(x, y)] = StorageStack(stack_id)

    def is_port_position(self, x: int, y: int) -> bool:
        """True, wenn (x, y) eine Port-/Pickstation-Position ist."""
        return (x, y) in self.port_positions

    def is_storage_position(self, x: int, y: int) -> bool:
        """
        True, wenn (x, y) eine gültige Grid-Position ist UND kein Port ist.
        """
        if not (0 <= x < self.width and 0 <= y < self.depth):
            return False
        return not self.is_port_position(x, y)

    def get_stack(self, x, y):
        # An Port-Positionen gibt es explizit keinen Stack
        if self.is_port_position(x, y):
            return None
        return self.stacks.get((x, y))

    def all_stacks(self):
        # Nur echte Stacks (None für Ports herausfiltern)
        return (stack for stack in self.stacks.values() if stack is not None)

    def __repr__(self):
        return f"Grid({self.width}x{self.depth})"