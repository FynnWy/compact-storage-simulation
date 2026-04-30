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
        Holt das nächste Event aus der EventQueue, synchronisiert die Simulationszeit
        und verarbeitet danach das Event.
        """
        if self.event_queue.is_empty():
            return None

        event = self.event_queue.pop()

        self._advance_time_until(event.time)

        self.handle(event)
        return event

    def _advance_time_until(self, target_time):
        """
        Erhöht die Simulationszeit schrittweise bis zur Zeit des nächsten Events.
        Bei jeder neuen Zeiteinheit werden neu angekommene Requests in die
        EventQueue gelegt.
        """
        if target_time < self.state.t:
            raise ValueError(
                f"Event time {target_time} is smaller than current simulation time {self.state.t}."
            )

        while self.state.t < target_time:
            self.state.advance_time()
            self.request_handler.add_ready_requests_to_event_queue()

    def handle(self, event):
        """
        Liest den Event-Typ und führt die dazugehörige Logik aus.
        """
        if event.event_type == EventType.ARRIVAL:
            request = event.payload
            self.active_queue.add(request)
            self._try_schedule_and_enqueue_plan(event.time)

        elif event.event_type == EventType.ROBOT_ACTION:
            self._handle_robot_action(event)

        elif event.event_type == EventType.REQUEST_COMPLETE:
            self._handle_request_complete(event)

        else:
            raise ValueError(f"Unknown event_type: {event.event_type}")

    def _handle_robot_action(self, event):
        action = self.event_builder.get_action_from_event(event)

        if not self.constraint_manager.can_execute(action, self.state):
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

        if self.active_queue.has_unassigned_requests():
            self._try_schedule_and_enqueue_plan(event.time)

    def _try_schedule_and_enqueue_plan(self, current_time):
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