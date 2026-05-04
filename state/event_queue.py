import heapq

class EventQueue:
    def __init__(self):
        self.queue = []

    def push(self, event):
        heapq.heappush(self.queue, event)

    def pop(self):
        return heapq.heappop(self.queue)

    def peek(self):
        if self.is_empty():
            return None

        return self.queue[0]

    def is_empty(self):
        return len(self.queue) == 0

    def __len__(self):
        return len(self.queue)