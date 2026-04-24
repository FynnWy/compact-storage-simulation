class State:
    def __init__(self, grid, bins, robots=None, future_request_queue=None, event_queue=None):
        self.grid = grid
        self.bins = bins
        self.robots = robots if robots is not None else []
        self.future_request_queue = future_request_queue
        self.event_queue = event_queue

        self.initialized = False

    def mark_initialized(self):
        self.initialized = True

    def is_initialized(self):
        return self.initialized

    def get_bin_by_id(self, bin_id):
        for bin_obj in self.bins:
            if bin_obj.bin_id == bin_id:
                return bin_obj
        return None

    def get_stack(self, x, y):
        return self.grid.get_stack(x, y)

    def all_stacks(self):
        return self.grid.all_stacks()