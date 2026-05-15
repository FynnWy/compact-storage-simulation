class Bin:
    def __init__(self, bin_id, stack_id, level, status):
        self.bin_id = bin_id
        self.stack_id = stack_id  # (x, y)
        self.stack_level = level  # Höhe im Stack
        self.status = status
        self.in_transit = False  # True, solange die Bin physisch bewegt wird

    def get_status(self):
        return self.status

    def set_status(self, status):
        self.status = status

    def set_level(self, level):
        self.stack_level = level

    def get_level(self):
        return self.stack_level

    def set_stack(self, stack_id):
        self.stack_id = stack_id

    def get_stack(self):
        return self.stack_id

    def mark_in_transit(self):
        self.in_transit = True

    def mark_transit_done(self):
        self.in_transit = False

    def __repr__(self):
        return (
            f"Bin(id={self.bin_id}, stack={self.stack_id}, "
            f"level={self.stack_level}, status={self.status}, "
            f"in_transit={self.in_transit})"
        )