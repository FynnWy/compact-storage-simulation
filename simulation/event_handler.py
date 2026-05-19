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
        if self.event_queue.is_empty():
            return None

        event = self.event_queue.pop()
        self.handle(event)
        return event

    def _advance_time_until(self, target_time):
        raise RuntimeError(
            "EventHandler._advance_time_until should not be used. "
            "Time advancement is handled by SimulationEngine."
        )

    def handle(self, event):
        if event.event_type == EventType.ARRIVAL:
            request = event.payload
            self.active_queue.add(request)

        elif event.event_type == EventType.ROBOT_ACTION:
            self._handle_robot_action(event)

        elif event.event_type == EventType.PICKSTATION_COMPLETE:
            self._handle_pickstation_complete(event)

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

        # in_transit setzen VOR Ausführung
        self._mark_bin_in_transit(action, state=self.state, in_transit=True)

        if action.get("type") == "remove_target":
            request = event.payload.get("request")
            self.metrics.record_target_bin_at_pickstation(self.state, action, request)

        self.executor.execute(event, self.state)

        # in_transit zurücksetzen NACH erfolgreicher Ausführung
        self._mark_bin_in_transit(action, state=self.state, in_transit=False)

        self._update_robot_position_after_action(event)
        self._update_task_after_successful_action(event)

        if action.get("type") == "remove_target":
            self._attach_batched_requests_to_task(event)
            self._start_pickstation_service_and_release_robot(event)
            return

        self._schedule_next_action_for_same_task(event)

    def _mark_bin_in_transit(self, action, state, in_transit):
        """
        Markiert die betroffene Bin als in_transit (vor Ausführung)
        bzw. hebt die Markierung auf (nach Ausführung).

        INV-2: Eine Bin ist entweder physisch zugänglich ODER in_transit.
        """
        bin_id = action.get("bin_id")
        if bin_id is None:
            return

        bin_obj = state.get_bin_by_id(bin_id)
        if bin_obj is None:
            return

        if in_transit:
            bin_obj.mark_in_transit()
        else:
            bin_obj.mark_transit_done()

    def _attach_batched_requests_to_task(self, event):
        """
        Stufe 3 – Batching (R-A2 / R-E2):

        Wenn die Target-Bin gerade zur Pickstation gebracht wird, prüfen wir,
        ob andere Requests auf dieselbe Bin gewartet haben (Batch-Warteliste).

        Falls ja: Diese Requests werden dem Task als batched_requests hinzugefügt.
        Sie werden an der Pickstation gemeinsam abgearbeitet.
        Die Pickstation-Servicezeit wird entsprechend verlängert.
        Jeder Request erhält seinen eigenen Completion-Zeitpunkt in den Metriken.
        """
        robot = event.payload.get("robot")
        if robot is None:
            return

        task = robot.current_task
        if task is None:
            return

        bin_id = task.target_bin_id
        batched = self.active_queue.pop_batch_waitlist_for_bin(bin_id)

        for request in batched:
            task.add_batched_request(request)
            # Sofort als "an Pickstation" metrisch erfassen
            self.metrics.record_target_bin_at_pickstation(
                self.state,
                {"type": "remove_target", "bin_id": bin_id},
                request,
            )

    def _update_task_after_successful_action(self, event):
        robot = event.payload.get("robot")

        if robot is None:
            return

        task = robot.current_task

        if task is None:
            return

        action = self.event_builder.get_action_from_event(event)
        action_type = action.get("type")

        if action_type == "relocate":
            bin_id = action.get("bin_id")
            task.remember_relocation(
                bin_id=bin_id,
                from_stack=action.get("from_stack"),
                buffer_stack=action.get("to_stack"),
            )
            # Blocker-Ownership registrieren, damit andere Tasks diese Bin nicht anfordern
            self.active_queue.register_blocker_ownership(bin_id, task)
            return

        if action_type == "remove_target":
            task.target_removed = True
            return

        if action_type == "return":
            self._update_task_after_successful_return(task, action)
            return

    def _update_task_after_successful_return(self, task, action):
        return_kind = action.get("return_kind")

        if return_kind == "blocker":
            task.mark_last_relocation_restored(
                bin_id=action.get("bin_id"),
                from_stack=action.get("from_stack"),
                to_stack=action.get("to_stack"),
            )
            # Blocker-Ownership freigeben, jetzt darf die Bin wieder angefragt werden
            self.active_queue.release_blocker_ownership(action.get("bin_id"))
            return

        if return_kind == "target":
            if action.get("bin_id") != task.target_bin_id:
                raise RuntimeError(
                    f"Cannot mark target returned for task {task.request_id}: "
                    f"action bin {action.get('bin_id')} is not target bin {task.target_bin_id}"
                )

            if action.get("to_stack") != task.target_stack_id:
                raise RuntimeError(
                    f"Cannot mark target returned for task {task.request_id}: "
                    f"action to_stack {action.get('to_stack')} is not target stack "
                    f"{task.target_stack_id}"
                )

            task.mark_target_returned()
            return

        raise RuntimeError(
            f"Return action for task {task.request_id} has unknown return_kind: {return_kind}"
        )

    def _start_pickstation_service_and_release_robot(self, event):
        robot = event.payload.get("robot")

        if robot is None:
            raise RuntimeError("Cannot start pickstation service: event has no robot")

        task = robot.current_task

        if task is None:
            raise RuntimeError("Cannot start pickstation service: robot has no task")

        task.mark_waiting_at_pickstation()

        # Servicezeit skaliert mit der Anzahl gebatchter Requests
        batch_count = len(task.batched_requests) + 1  # +1 für den primären Request
        service_duration = self.event_builder.calculate_pickstation_service_duration(
            batch_count=batch_count,
        )

        pickstation_complete_event = self.event_builder.build_pickstation_complete_event(
            task=task,
            time=self.state.t + service_duration,
        )
        self.event_queue.push(pickstation_complete_event)

        self.active_queue.add_pickstation_task(task)
        robot.clear_task()

    def _handle_pickstation_complete(self, event):
        task = event.payload.get("task")

        if task is None:
            raise RuntimeError("Cannot handle pickstation completion: event has no task")

        task.mark_pickstation_completed()
        self.active_queue.mark_pickstation_task_completed(task)

        # WICHTIG:
        # Hier KEINE vollständige Fertigstellung mehr zählen.
        # Die vollständige Completion erfolgt erst, wenn der Task
        # alle Bins zurückgelagert hat und konsistent abgeschlossen ist
        # (siehe _handle_request_complete).
        # Metrik 1 (Arrival → Pickstation) wurde bereits bei remove_target
        # bzw. beim Batching erfasst.

    def _schedule_next_action_for_same_task(self, event):
        robot = event.payload.get("robot")

        if robot is None:
            raise RuntimeError("Cannot schedule next action: event has no robot")

        task = robot.current_task

        if task is None:
            return

        next_action = self.scheduler.strategy.next_action(self.state, task)

        if next_action is None:
            self.active_queue.add_waiting_task(task)
            robot.clear_task()
            return

        duration = self.event_builder.calculate_action_duration(
            action=next_action,
            state=self.state,
            robot=robot,
        )

        next_event = self.event_builder.build_event_from_action(
            action=next_action,
            request=task.request,
            robot=robot,
            time=self.state.t + duration,
        )

        self.event_queue.push(next_event)

    def _update_robot_position_after_action(self, event):
        robot = event.payload.get("robot")

        if robot is None:
            return

        action = self.event_builder.get_action_from_event(event)
        final_position = self.event_builder.get_final_robot_position(action)

        if final_position is not None:
            robot.set_position(final_position)

    def _handle_request_complete(self, event):
        payload = event.payload
        robot = payload["robot"]
        request = payload["request"]

        task = robot.current_task

        if task is None:
            raise RuntimeError(
                f"Cannot complete request {request.request_id}: robot has no current task"
            )

        if task.request_id != request.request_id:
            raise RuntimeError(
                f"Cannot complete request {request.request_id}: "
                f"robot task belongs to request {task.request_id}"
            )

        # Sicherstellen, dass der Task wirklich vollständig und konsistent ist:
        # - Target-Bin zurückgelegt
        # - alle Blocker-Bins zurückgelegt
        # - Lagerzustand konsistent
        task.require_consistently_completed(self.state)

        completion_time = self.state.t

        # Hauptrequest abschließen (Metrik 3)
        self.metrics.record_full_completion(completion_time, task.request)

        # Gebatchte Requests erhalten denselben Vollständigkeitszeitpunkt.
        # Sie wurden alle an derselben Bin bedient, und die physische
        # Rücklagerung wird vom gemeinsamen Task getragen.
        for batched_request in task.batched_requests:
            self.metrics.record_full_completion(completion_time, batched_request)

        self.active_queue.mark_completed(request)
        robot.clear_task()

    def schedule_available_robots(self, current_time):
        """
        Scheduled so viele Requests oder wartende Tasks, wie freie Roboter vorhanden sind.
        """
        while True:
            scheduling_result = self.scheduler.try_schedule(self.state, current_time)

            if scheduling_result is None:
                return

            action = scheduling_result["action"]

            if action is None:
                return

            robot = scheduling_result["robot"]

            duration = self.event_builder.calculate_action_duration(
                action=action,
                state=self.state,
                robot=robot,
            )

            event = self.event_builder.build_event_from_action(
                action=action,
                request=scheduling_result["request"],
                robot=robot,
                time=scheduling_result["start_time"] + duration,
            )

            self.event_queue.push(event)