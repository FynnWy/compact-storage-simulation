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
        
        elif event.event_type == EventType.ROBOT_MOVE:
            self._handle_robot_move(event)

        elif event.event_type == EventType.PICKSTATION_COMPLETE:
            self._handle_pickstation_complete(event)

        elif event.event_type == EventType.REQUEST_COMPLETE:
            self._handle_request_complete(event)

        else:
            raise ValueError(f"Unknown event_type: {event.event_type}")

    def _handle_robot_move(self, event):
        """
        Verarbeitet einen einzelnen Bewegungsschritt eines Roboters.
        
        Flow:
        1. Prüfen ob Zielposition verfügbar ist (Reservierung)
        2. Roboter bewegt sich zum nächsten Wegpunkt
        3. Alte Reservierung freigeben
        4. Prüfen ob Ziel erreicht
        5. Falls nein: Nächstes ROBOT_MOVE Event erzeugen
        """
        robot = event.payload.get("robot")
        
        if robot is None:
            raise RuntimeError("Cannot handle robot move: event has no robot")
        
        # NEU: Prüfen ob nächste Position noch reserviert ist
        next_waypoint = robot.get_next_waypoint()
        
        if next_waypoint is None:
            # Pfad bereits abgeschlossen
            return
        
        # Reservierung prüfen (Sicherheitsprüfung)
        if not self.state.reservation_table.is_free(
            *next_waypoint, self.state.t, exclude_robot=robot.robot_id
        ):
            # Blockiert - Event verzögern und neu versuchen
            print(
                f"[WARNING] Robot {robot.robot_id} blocked at {next_waypoint} "
                f"at time {self.state.t}, retrying..."
            )
            
            delayed_event = self.event_builder.delay_event(
                event=event,
                current_time=self.state.t,
            )
            self.event_queue.push(delayed_event)
            return
        
        # Alte Position freigeben (falls vorhanden)
        old_position = robot.get_position()
        if old_position is not None:
            self.state.reservation_table.release(
                robot.robot_id, *old_position, self.state.t - 1
            )
        
        # Roboter zum nächsten Wegpunkt bewegen
        try:
            new_position = robot.advance_to_next_waypoint()
        except RuntimeError as e:
            print(f"[WARNING] Robot {robot.robot_id} move failed: {e}")
            return
        
        # Prüfen ob Ziel erreicht
        if robot.has_reached_destination():
            # Ziel erreicht - Pfad-Reservierungen freigeben
            self.state.reservation_table.release_all(robot.robot_id)
            return
        
        # Noch nicht am Ziel - nächstes ROBOT_MOVE Event erzeugen
        move_cost = self.event_builder.cost_model.config.move_cost_per_grid_step
        next_move_event = self.event_builder.build_robot_move_event(
            robot=robot,
            time=self.state.t + move_cost,
        )
        self.event_queue.push(next_move_event)

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

            # Access-Count Tracking: Jeder erfolgreiche Retrieval zählt
            bin_id = action.get("bin_id")
            if bin_id is not None:
                bin_obj = self.state.get_bin_by_id(bin_id)
                if bin_obj is not None:
                    bin_obj.increment_access_count()

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
        
        # NEU: Pickstation aus State ermitteln
        robot_position = robot.get_position()
        if robot_position is None:
            robot_position = (0, 0)
        
        pickstation = self.state.get_nearest_pickstation(robot_position)
        if pickstation is None:
            raise RuntimeError(
                f"Cannot start pickstation service: no pickstation available "
                f"for robot {robot.robot_id}"
            )
        
        # Task zur Pickstation-Queue hinzufügen
        pickstation.enqueue(task, self.state.t)
        
        # Task aus assigned entfernen (wird später wieder zugewiesen)
        self.active_queue.add_pickstation_task(task)
        
        # Roboter freigeben
        robot.clear_task()
        
        # Prüfen ob Pickstation sofort Service starten kann
        self._try_start_pickstation_service(pickstation)
    
    def _try_start_pickstation_service(self, pickstation):
        """
        Versucht, nächsten Task an der Pickstation zu starten.
        
        Wird aufgerufen:
        - Wenn ein neuer Task zur Queue hinzugefügt wird
        - Wenn ein Service abgeschlossen wurde
        """
        if not pickstation.has_capacity():
            return  # Pickstation ist voll
        
        if pickstation.queue_length() == 0:
            return  # Keine wartenden Tasks
        
        # Nächsten Task aus Queue holen
        queue_strategy = self.state.config.pickstation_queue_strategy
        result = pickstation.dequeue(
            strategy=queue_strategy,
            scheduler=self.scheduler if queue_strategy == "PRIORITY" else None,
        )
        
        if result is None:
            return
        
        task, arrival_time = result
        
        # Wartezeit tracken
        wait_time = self.state.t - arrival_time
        pickstation.record_wait_time(wait_time)
        
        # Service starten
        pickstation.start_service(task)
        
        # Task in der Pickstation speichern (für spätere Referenz)
        task.assigned_pickstation = pickstation.station_id
        
        # Servicezeit berechnen (skaliert mit Batch-Größe)
        batch_count = len(task.batched_requests) + 1
        service_duration = self.event_builder.calculate_pickstation_service_duration(
            batch_count=batch_count,
        )
        
        # Servicezeit tracken
        pickstation.record_service_time(service_duration)
        
        # PICKSTATION_COMPLETE Event erstellen
        pickstation_complete_event = self.event_builder.build_pickstation_complete_event(
            task=task,
            time=self.state.t + service_duration,
        )
        self.event_queue.push(pickstation_complete_event)

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
        
    def _update_robot_position_after_action(self, event):
        """
        Aktualisiert Roboter-Position nach erfolgreicher Aktion.
        
        Wird nach relocate/remove_target/return aufgerufen.
        """
        robot = event.payload.get("robot")

        if robot is None:
            return

        action = self.event_builder.get_action_from_event(event)
        final_position = self.event_builder.get_final_robot_position(action)

        if final_position is not None:
            robot.set_position(final_position)

    def _handle_request_complete(self, event):
        """
        Behandelt vollständigen Abschluss eines Requests.
        
        Wird aufgerufen, wenn:
        - Target-Bin zurückgelegt wurde
        - Alle Blocker-Bins zurückgelegt wurden
        - Lagerzustand konsistent ist
        """
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

        # Pfad berechnen und Bewegungs-Events erzeugen
        target_position = self._get_target_position_for_action(next_action)
        
        if target_position is None:
            # Keine Bewegung erforderlich
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
            return
        
        # Pfad berechnen
        current_position = robot.get_position()
        if current_position is None:
            current_position = target_position
            robot.set_position(current_position)

        path = self.event_builder.cost_model.calculate_path(
            from_position=current_position,
            to_position=target_position,
            robot=robot,  # NEU
            state=self.state,  # NEU
            current_time=self.state.t,  # NEU
        )
        
        if not path:
            # Roboter ist bereits am Ziel
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
            return
        
        # Pfad-Events erzeugen (mit state für Reservierung)
        path_events = self.event_builder.build_path_events(
            robot=robot,
            path=path,
            target_action=next_action,
            request=task.request,
            start_time=self.state.t,
            state=self.state,  # NEU: state übergeben
        )
        
        # NEU: Prüfen ob Pfad reserviert werden konnte
        if path_events is None:
            # Reservierung fehlgeschlagen - Task in Warteschlange
            print(
                f"[BLOCKED] Cannot reserve path for robot {robot.robot_id}, "
                f"task {task.request_id} moved to waiting queue"
            )
            self.active_queue.add_waiting_task(task)
            robot.clear_task()
            return
        
        for path_event in path_events:
            self.event_queue.push(path_event)
    
    def _get_target_position_for_action(self, action):
        """
        Bestimmt Zielposition für eine Aktion.
        
        Args:
            action: Action-Dict
        
        Returns:
            (x, y) | None
        """
        action_type = action.get("type")
        
        if action_type in ("relocate", "remove_target"):
            stack_id = action.get("from_stack")
            return self._resolve_position(stack_id)
        
        if action_type == "return":
            # Bei Return: entweder from_stack oder Pickstation
            from_stack_id = action.get("from_stack")
            if from_stack_id is None:
                # Von Pickstation - Roboter muss zur Pickstation
                if self.state.pickstations:
                    return self.state.pickstations[0].position
                return self.event_builder.cost_model.config.pickstation_position
            
            return self._resolve_position(from_stack_id)
        
        if action_type == "request_complete":
            # Keine Bewegung erforderlich
            return None
        
        return None
    
    def _resolve_position(self, stack_id):
        """Wandelt stack_id in (x, y) Position um."""
        if stack_id is None:
            return None
        
        if isinstance(stack_id, tuple) and len(stack_id) == 2:
            return stack_id
        
        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")
            if len(parts) == 3:
                try:
                    return (int(parts[1]), int(parts[2]))
                except ValueError:
                    return None
        
        return None

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
            request = scheduling_result["request"]
            
            # NEU: Prüfen ob Bewegung erforderlich
            requires_movement = scheduling_result.get("requires_movement", False)
            
            if not requires_movement:
                # Keine Bewegung - direkt Action ausführen
                duration = self.event_builder.calculate_action_duration(
                    action=action,
                    state=self.state,
                    robot=robot,
                )

                event = self.event_builder.build_event_from_action(
                    action=action,
                    request=request,
                    robot=robot,
                    time=scheduling_result["start_time"] + duration,
                )

                self.event_queue.push(event)
                continue
            
            # Bewegung erforderlich - Pfad berechnen
            target_position = self._get_target_position_for_action(action)
            current_position = robot.get_position()
            
            if current_position is None:
                # Roboter hat noch keine Position - setze auf Ziel
                current_position = target_position
                robot.set_position(current_position)
            
            path = self.event_builder.cost_model.calculate_path(
                from_position=current_position,
                to_position=target_position,
                robot=robot,  # NEU
                state=self.state,  # NEU
                current_time=self.state.t,  # NEU
            )
            
            if not path:
                # Roboter ist bereits am Ziel - direkt Action ausführen
                duration = self.event_builder.calculate_action_duration(
                    action=action,
                    state=self.state,
                    robot=robot,
                )

                event = self.event_builder.build_event_from_action(
                    action=action,
                    request=request,
                    robot=robot,
                    time=scheduling_result["start_time"] + duration,
                )

                self.event_queue.push(event)
                continue
            
            # Pfad-Events erzeugen und zur Queue hinzufügen
            path_events = self.event_builder.build_path_events(
                robot=robot,
                path=path,
                target_action=action,
                request=request,
                start_time=scheduling_result["start_time"],
                state=self.state,  # NEU: state übergeben
            )
            
            # NEU: Prüfen ob Pfad reserviert werden konnte
            if path_events is None:
                # Reservierung fehlgeschlagen - Request bleibt pending
                print(
                    f"[BLOCKED] Cannot reserve path for robot {robot.robot_id}, "
                    f"request {request.request_id} stays pending"
                )
                robot.clear_task()
                self.active_queue.pending.appendleft(request)
                continue
            
            for path_event in path_events:
                self.event_queue.push(path_event)