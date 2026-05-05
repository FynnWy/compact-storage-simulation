class StorageStack:
    def __init__(self, stack_id):
        self.stack_id = stack_id
        self.bins = []  # Liste von Bin-Objekten
        self.locked_by = None  # für Constraints (z. B. welcher Roboter)

    # --- Zugriff ---
    def push(self, bin_obj):
        self.bins.append(bin_obj)

    def pop(self):
        if not self.bins:
            return None

        return self.bins.pop()

    def peek(self):
        return self.bins[-1] if self.bins else None

    # --- Infos ---
    def is_empty(self):
        return len(self.bins) == 0

    def height(self):
        return len(self.bins)

    def is_locked(self):
        return self.locked_by is not None

    def lock(self, robot_id):
        self.locked_by = robot_id

    def unlock(self):
        self.locked_by = None

    def __repr__(self):
        return f"Stack(id={self.stack_id}, height={len(self.bins)})"