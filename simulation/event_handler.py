from events.event_types import EventType


class EventHandler:

    def __init__(
        self,
        state,
        active_queue,
        event_queue,
        request_handler,
        metrics,
        constraint_manager,
        scheduler,
        executor,
        event_builder,
    ):
        self.state = state
        self.active_queue = active_queue
        self.event_queue = event_queue
        self.request_handler = request_handler
        self.metrics = metrics
        self.constraint_manager = constraint_manager
        self.scheduler = scheduler
        self.executor = executor
        self.event_builder = event_builder

    def get_next_event(self):
        """
        Holt das nächste Event aus der EventQueue und verarbeitet danach das Event.

        Die Zeitsynchronisation passiert zentral in der SimulationEngine.
        """
        if self.event_queue.is_empty():
            return None

        event = self.event_queue.pop()
        self.handle(event)
        return event

    def _advance_time_until(self, target_time):
        """
        Deprecated:
        Zeitsynchronisation passiert zentral in der SimulationEngine.
        """
        raise RuntimeError(
            "EventHandler._advance_time_until should not be used. "
            "Time advancement is handled by SimulationEngine."
        )
    def handle(self, event):
        """
        Liest den Event-Typ und führt die dazugehörige Logik aus.
        """
        if event.event_type == EventType.ARRIVAL:
            request = event.payload
            self.active_queue.add(request)

        elif event.event_type == EventType.ROBOT_ACTION:
            self._handle_robot_action(event)

        elif event.event_type == EventType.REQUEST_COMPLETE:
            self._handle_request_complete(event)

        else:
            raise ValueError(f"Unknown event_type: {event.event_type}")

    def _handle_robot_action(self, event):
        action = self.event_builder.get_action_from_event(event)
        can_execute, reason = self.constraint_manager.can_execute_with_reason(
            action,
            self.state,
        )

        if not can_execute:
            request = event.payload.get("request")
            robot = event.payload.get("robot")

            print(
                "[BLOCKED] "
                f"t={self.state.t}, "
                f"retry={event.retry_count}, "
                f"robot={robot.robot_id if robot is not None else None}, "
                f"request={request.request_id if request is not None else None}, "
                f"action={action}, "
                f"reason={reason}"
            )

            delayed_event = self.event_builder.delay_event(
                event=event,
                current_time=self.state.t,
            )
            self.event_queue.push(delayed_event)
            return

        if action.get("type") == "remove_target":
            request = event.payload.get("request")
            self.metrics.record_target_bin_removed(self.state, action, request)

        self.executor.execute(event, self.state)
        self._schedule_next_action_for_same_task(event)

    def _schedule_next_action_for_same_task(self, event):
        robot = event.payload.get("robot")

        if robot is None:
            raise RuntimeError("Cannot schedule next action: event has no robot")

        task = robot.current_task

        if task is None:
            return

        next_action = self.scheduler.strategy.next_action(self.state, task)

        if next_action is None:
            return

        next_event = self.event_builder.build_event_from_action(
            action=next_action,
            request=task.request,
            robot=robot,
            time=self.state.t + self.event_builder.action_duration,
        )

        self.event_queue.push(next_event)

    def _handle_request_complete(self, event):
        payload = event.payload
        robot = payload["robot"]
        request = payload["request"]

        self.active_queue.mark_completed(request)
        robot.clear_task()

    def schedule_available_robots(self, current_time):
        """
        Scheduled so viele Requests, wie freie Roboter und pending Requests vorhanden sind.

        Neuer Flow:
        Pro Scheduling wird genau ein RobotTask erzeugt und genau eine erste Action
        als Event in die Queue gelegt.
        """
        while self.active_queue.has_unassigned_requests():
            scheduling_result = self.scheduler.try_schedule(self.state, current_time)

            if scheduling_result is None:
                return

            action = scheduling_result["action"]

            if action is None:
                return

            event = self.event_builder.build_event_from_action(
                action=action,
                request=scheduling_result["request"],
                robot=scheduling_result["robot"],
                time=scheduling_result["start_time"],
            )

            self.event_queue.push(event)