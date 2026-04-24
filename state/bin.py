class Bin:
    def __init__(self, bin_id, stack_id, level, status):
        self.bin_id = bin_id
        self.stack_id = stack_id  # (x, y)
        self.stack_level = level  #Höhe im Stack
        self.status = status

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

    def __repr__(self):
        return f"Bin(id={self.bin_id}, stack={self.stack_id}, level={self.stack_level}), status={self.status}"