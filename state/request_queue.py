import heapq

class FutureRequestQueue:
    def __init__(self):
        self.queue = []

    def push(self, request):
        heapq.heappush(self.queue, (request.arrival_time, request))

    def pop_ready(self, current_time):
        ready = []

        while self.queue and self.queue[0][0] <= current_time:
            _, req = heapq.heappop(self.queue)
            ready.append(req)

        return ready

    def is_empty(self):
        return len(self.queue) == 0

    def __len__(self):
        return len(self.queue)

    def __repr__(self):
        return f"Queue(size={len(self.queue)})"