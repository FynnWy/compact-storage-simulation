from collections import deque

class ActiveQueue:
    def __init__(self):
        self.pending = deque()
        self.assigned = {}
        self.waiting_tasks = deque()
        self.pickstation_tasks = {}

    def add(self, request):
        """
        Fügt einen neu angekommenen Request als noch nicht zugewiesen hinzu.
        """
        self.pending.append(request)

    def has_unassigned_requests(self):
        return len(self.pending) > 0

    def has_waiting_tasks(self):
        return len(self.waiting_tasks) > 0

    def add_waiting_task(self, task):
        """
        Merkt einen aktiven Task, der aktuell keinem Roboter zugewiesen ist,
        aber fachlich fortsetzbar ist.
        """
        if task not in self.waiting_tasks:
            self.waiting_tasks.append(task)

    def add_pickstation_task(self, task):
        """
        Merkt einen aktiven Task, dessen Target-Bin gerade an der Pickstation
        bearbeitet wird.

        Der Task bleibt aktiv, ist aber noch nicht fortsetzbar.
        """
        self.assigned.pop(task.request_id, None)
        self.pickstation_tasks[task.request_id] = task

    def mark_pickstation_task_completed(self, task):
        """
        Macht einen Pickstation-Task nach Serviceende wieder fortsetzbar.
        """
        self.pickstation_tasks.pop(task.request_id, None)
        self.add_waiting_task(task)

    def pop_waiting_task(self):
        if not self.waiting_tasks:
            return None

        return self.waiting_tasks.popleft()

    def mark_assigned(self, request, robot):
        """
        Markiert einen Request als einem Roboter zugewiesen.
        """
        self.assigned[request.request_id] = {
            "request": request,
            "robot": robot,
        }

    def mark_task_assigned(self, task, robot):
        """
        Markiert einen bereits existierenden Task wieder als einem Roboter zugewiesen.
        """
        self.pickstation_tasks.pop(task.request_id, None)

        self.assigned[task.request_id] = {
            "request": task.request,
            "robot": robot,
        }

    def mark_completed(self, request):
        """
        Entfernt einen abgeschlossenen Request aus allen aktiven Verwaltungen.
        """
        self.assigned.pop(request.request_id, None)
        self.pickstation_tasks.pop(request.request_id, None)

        self.waiting_tasks = deque(
            task for task in self.waiting_tasks
            if task.request_id != request.request_id
        )

    def is_empty(self):
        return (
                len(self.pending) == 0
                and len(self.assigned) == 0
                and len(self.waiting_tasks) == 0
                and len(self.pickstation_tasks) == 0
        )

    def get_assigned_target_bin_ids(self):
        """
        Gibt alle Bin-IDs zurück, die aktuell bereits einem Roboter,
        einem wartenden Task oder einem Pickstation-Service-Task zugewiesen sind.

        Dadurch kann verhindert werden, dass dieselbe Bin parallel bearbeitet wird.
        """
        assigned_bin_ids = set()

        for assignment in self.assigned.values():
            request = assignment["request"]
            assigned_bin_ids.add(request.target_box_id)

        for task in self.waiting_tasks:
            assigned_bin_ids.add(task.target_bin_id)

        for task in self.pickstation_tasks.values():
            assigned_bin_ids.add(task.target_bin_id)

        return assigned_bin_ids

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
        return (
            len(self.pending)
            + len(self.assigned)
            + len(self.waiting_tasks)
            + len(self.pickstation_tasks)
        )

    def __repr__(self):
        return (
            f"ActiveQueue("
            f"pending={len(self.pending)}, "
            f"assigned={len(self.assigned)}, "
            f"waiting_tasks={len(self.waiting_tasks)}, "
            f"pickstation_tasks={len(self.pickstation_tasks)})"
        )