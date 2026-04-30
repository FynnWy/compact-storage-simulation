from collections import deque

class ActiveQueue:
    def __init__(self):
        self.pending = deque()
        self.assigned = {}

    def add(self, request):
        """
        Fügt einen neu angekommenen Request als noch nicht zugewiesen hinzu.
        """
        self.pending.append(request)

    def has_unassigned_requests(self):
        return len(self.pending) > 0

    def mark_assigned(self, request, robot):
        """
        Markiert einen Request als einem Roboter zugewiesen.
        """
        self.assigned[request.request_id] = {
            "request": request,
            "robot": robot,
        }

    def mark_completed(self, request):
        """
        Entfernt einen abgeschlossenen Request aus den aktiven Assignments.
        """
        self.assigned.pop(request.request_id, None)

    def is_empty(self):
        return len(self.pending) == 0 and len(self.assigned) == 0


    """
    Scheduler Strategien:
    """
    def pop_next_fifo(self):
        """
        FIFO: Wählt den ältesten noch nicht zugewiesenen Request.
        """
        return self.pending.popleft() if self.pending else None

    def pop_next_edf(self):
        """
        EDF: Wählt den Request mit der frühesten Deadline.
        """
        if not self.pending:
            return None

        best_request = min(self.pending, key=lambda request: request.latest_time)
        self.pending.remove(best_request)
        return best_request



    def __len__(self):
        return len(self.pending) + len(self.assigned)

    def __repr__(self):
        return (
            f"ActiveQueue("
            f"pending={len(self.pending)}, "
            f"assigned={len(self.assigned)})"
        )