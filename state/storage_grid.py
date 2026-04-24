from state.storage_stack import StorageStack
class StorageGrid:
    def __init__(self, width, depth):
        self.width = width
        self.depth = depth

        # Dictionary: (x, y) → Stack
        self.stacks = {}

        self._initialize_grid()

    def _initialize_grid(self):
        for x in range(self.width):
            for y in range(self.depth):
                stack_id = f"S_{x}_{y}"
                self.stacks[(x, y)] = StorageStack(stack_id)

    def get_stack(self, x, y):
        return self.stacks.get((x, y))

    def all_stacks(self):
        return self.stacks.values()

    def __repr__(self):
        return f"Grid({self.width}x{self.depth})"