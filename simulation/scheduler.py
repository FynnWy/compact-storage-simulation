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
        if self.scheduler_strategy == "FIFO":
            return self.active_queue.pop_next_fifo()

        if self.scheduler_strategy == "EDF":
            return self.active_queue.pop_next_edf()

        raise ValueError(f"Unknown scheduler_strategy: {self.scheduler_strategy}")

    def _find_idle_robot(self, state):
        for robot in state.robots:
            if robot.status == "idle":
                return robot

        return None