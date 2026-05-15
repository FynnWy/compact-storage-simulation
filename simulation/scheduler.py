from simulation.robot_task import RobotTask


class Scheduler:
    def __init__(self, active_queue, strategy, scheduler_strategy="FIFO"):
        self.active_queue = active_queue
        self.strategy = strategy
        self.scheduler_strategy = scheduler_strategy.upper()

    def try_schedule(self, state, current_time):
        """
        Versucht, genau einen Task oder Request einem freien Roboter zuzuordnen.

        Reihenfolge:
        1. Wartende aktive Tasks fortsetzen.
        2. Falls kein wartender Task vorhanden ist, neuen Request zuweisen.
        """
        robot = self._find_idle_robot(state)

        if robot is None:
            return None

        waiting_task_result = self._try_schedule_waiting_task(
            state=state,
            robot=robot,
            current_time=current_time,
        )

        if waiting_task_result is not None:
            return waiting_task_result

        if not self.active_queue.has_unassigned_requests():
            return None

        request = self._select_next_request()

        if request is None:
            return None

        task = RobotTask(request)

        robot.assign_task(task)
        self.active_queue.mark_assigned(request, robot)

        action = self.strategy.next_action(state, task)

        return {
            "request": request,
            "robot": robot,
            "task": task,
            "action": action,
            "start_time": current_time,
        }

    def _try_schedule_waiting_task(self, state, robot, current_time):
        if not self.active_queue.has_waiting_tasks():
            return None

        task = self.active_queue.pop_waiting_task()
        robot.assign_task(task)
        self.active_queue.mark_task_assigned(task, robot)

        action = self.strategy.next_action(state, task)

        if action is None:
            robot.clear_task()
            self.active_queue.add_waiting_task(task)
            return None

        return {
            "request": task.request,
            "robot": robot,
            "task": task,
            "action": action,
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