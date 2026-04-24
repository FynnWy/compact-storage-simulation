from collections import deque

class ActiveQueue:
    def __init__(self):
        self.queue = deque()

    def add(self, request):
        self.queue.append(request)

    def pop(self):
        return self.queue.popleft() if self.queue else None

    def remove(self, request):
        self.queue.remove(request)

    def is_empty(self):
        return len(self.queue) == 0

    def __len__(self):
        return len(self.queue)

    def __repr__(self):
        return f"ActiveQueue(size={len(self.queue)})"