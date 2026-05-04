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

    def _handle_request_complete(self, event):
        payload = event.payload
        robot = payload["robot"]
        request = payload["request"]

        self.active_queue.mark_completed(request)
        robot.clear_task()

    def schedule_available_robots(self, current_time):
        """
        Scheduled so viele Requests, wie freie Roboter und pending Requests vorhanden sind.
        Wird von der SimulationEngine nach Completion-/Arrival-Phase aufgerufen.
        """
        while self.active_queue.has_unassigned_requests():
            scheduling_result = self.scheduler.try_schedule(self.state, current_time)

            if scheduling_result is None:
                return

            events = self.event_builder.build_events_from_plan(
                plan=scheduling_result["plan"],
                request=scheduling_result["request"],
                robot=scheduling_result["robot"],
                start_time=scheduling_result["start_time"],
            )

            for event in events:
                self.event_queue.push(event)