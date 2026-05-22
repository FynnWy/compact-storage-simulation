class Scheduler:
    def __init__(self, active_queue, strategy, scheduler_strategy="FIFO"):
        self.active_queue = active_queue
        self.strategy = strategy
        self.scheduler_strategy = scheduler_strategy.upper()

    def try_schedule(self, state, current_time):
        """
        Versucht, genau einen pending Request einem freien Roboter zuzuordnen.

        Gibt ein Scheduling-Ergebnis zurück oder None, wenn nichts geplant werden kann.
        """
        robot = self._find_idle_robot(state)

        if robot is None:
            return None

        if not self.active_queue.has_unassigned_requests():
            return None

        request = self._select_next_request()

        if request is None:
            return None

        robot.assign_task(request.request_id)
        self.active_queue.mark_assigned(request, robot)

        plan = self.strategy.plan(state, request)

        return {
            "request": request,
            "robot": robot,
            "plan": plan,
            "start_time": current_time,
        }

    def _select_next_request(self):
        blocked_bin_ids = self.active_queue.get_assigned_target_bin_ids()

        if self.scheduler_strategy == "FIFO":
            return self._pop_next_fifo_excluding(blocked_bin_ids)

        if self.scheduler_strategy == "EDF":
            return self._pop_next_edf_excluding(blocked_bin_ids)

        raise ValueError(f"Unknown scheduler_strategy: {self.scheduler_strategy}")

    def _pop_next_fifo_excluding(self, blocked_bin_ids):
        for request in list(self.active_queue.pending):
            if request.target_box_id not in blocked_bin_ids:
                self.active_queue.pending.remove(request)
                return request

        return None

    def _pop_next_edf_excluding(self, blocked_bin_ids):
        candidates = [
            request
            for request in self.active_queue.pending
            if request.target_box_id not in blocked_bin_ids
        ]

        if not candidates:
            return None

        best_request = min(candidates, key=lambda request: request.latest_time)
        self.active_queue.pending.remove(best_request)
        return best_request

    def _find_idle_robot(self, state):
        for robot in state.robots:
            if robot.status == "idle":
                return robot

        return None