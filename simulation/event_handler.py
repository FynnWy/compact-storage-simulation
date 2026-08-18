from events.event_types import EventType
from traffic.port_prioritizer import PortPrioritizer, RobotCandidate
from traffic.idle_parking import IdleParkingManager

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
        # Maximale Anzahl Blockierungs-Retries für dieselbe Aktion,
        # bevor der Task als „veraltet“ gilt und neu verplant wird.
        self.max_action_retries_before_replan = 20

        # NEU: Spezifische Schutzschwellen für Pickup-Positionsfehler
        self.max_pickup_position_retries_before_replan = 5
        self.max_pickup_position_retries_before_requeue = 15

        # Move-Blockaden: frühes Replaning und Duplikat-Schutz
        self.max_move_retries_before_replan = 1
        self.max_move_retries_before_force_replan = 2
        self._last_move_handled_time_by_robot = {}

        # Intelligente Port-Priorisierung (WP4)
        move_cost = getattr(
            getattr(self.state, "config", None),
            "port_move_cost_per_cell",
            1,
        )
        self.port_prioritizer = PortPrioritizer(move_cost_per_cell=move_cost)

        # Idle-ParkingManager (WP5 – Idle-Roboter-Regeln)
        self.idle_parking = IdleParkingManager(
            grid_width=self.state.grid.width,
            grid_depth=self.state.grid.depth,
            port_positions=self.state.port_positions,
            buffer_zone=self.state.buffer_zone,
        )

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

    """Neuer Code"""

    def handle(self, event):
        if event.event_type == EventType.ARRIVAL:
            request = event.payload
            self.active_queue.add(request)

        elif event.event_type == EventType.ROBOT_ACTION:
            self._handle_robot_action(event)

        elif event.event_type == EventType.ROBOT_MOVE:
            self._handle_robot_move(event)

        # NEU: Zwei-Phasen-Aktionen
        elif event.event_type == EventType.ROBOT_PICKUP:
            self._handle_robot_pickup(event)

        elif event.event_type == EventType.ROBOT_DROP:
            self._handle_robot_drop(event)

        elif event.event_type == EventType.PICKSTATION_COMPLETE:
            self._handle_pickstation_complete(event)

        elif event.event_type == EventType.REQUEST_COMPLETE:
            self._handle_request_complete(event)

        else:
            raise ValueError(f"Unknown event_type: {event.event_type}")
    """
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
    """
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

        # Duplikat-Schutz: pro Roboter nur ein Move-Handling pro Zeitschritt.
        # Verhindert mehrfache Retry-Schleifen im selben t durch stale Events.
        if self._last_move_handled_time_by_robot.get(robot.robot_id) == self.state.t:
            return
        self._last_move_handled_time_by_robot[robot.robot_id] = self.state.t

        next_waypoint = robot.get_next_waypoint()

        if next_waypoint is None:
            # Pfad bereits abgeschlossen
            return

        # Debug: geplanter Move
        print(
            f"[DEBUG][MOVE] t={self.state.t} robot={robot.robot_id} "
            f"current_pos={robot.get_position()} next_waypoint={next_waypoint}"
        )

        # Kollisionen an Pickstations und im „PS-Bereich“ (x < 0) verhindern
        # Wir behandeln:
        # - alle echten Pickstation-Positionen
        # - sowie alle Zellen mit x < 0 (außerhalb des Grids)
        is_pickstation_cell = False

        # 1) Echte Pickstations
        for ps in self.state.pickstations:
            if next_waypoint == ps.position:
                is_pickstation_cell = True
                break

        # 2) Generischer PS-Bereich: alle Zellen links vom Grid
        if next_waypoint[0] < 0:
            is_pickstation_cell = True

        if is_pickstation_cell:
            # Prüfen ob dort bereits ein anderer Roboter steht
            for other in self.state.robots:
                if (
                        other.robot_id != robot.robot_id
                        and other.get_position() == next_waypoint
                ):
                    if event.retry_count >= self.max_move_retries_before_replan:
                        if event.retry_count >= self.max_move_retries_before_force_replan:
                            # Blockierenden Roboter möglichst früh aus dem Port-Bereich lösen.
                            if (
                                    other.current_task is None
                                    and other.status == "idle"
                            ):
                                self._handle_robot_becomes_idle(other)
                            elif self._force_stale_robot_to_replan(other):
                                delayed_event = self.event_builder.delay_event(
                                    event=event,
                                    current_time=self.state.t,
                                )
                                self.event_queue.push(delayed_event)
                                return

                        print(
                            f"[REPLAN] Robot {robot.robot_id} replanning path to avoid "
                            f"robot {other.robot_id} at {next_waypoint}"
                        )
                        self._replan_path_around_obstacle(robot, next_waypoint, event)
                        return

                    print(
                        f"[WARNING] Robot {robot.robot_id} blocked at PS-area cell "
                        f"{next_waypoint} (occupied by robot {other.robot_id}) "
                        f"at time {self.state.t}, retrying... "
                        f"(attempt {event.retry_count + 1}/{self.max_move_retries_before_replan + 1})"
                    )
                    delayed_event = self.event_builder.delay_event(
                        event=event,
                        current_time=self.state.t,
                    )
                    self.event_queue.push(delayed_event)
                    return

        # ✅ NEU: Port-Reservierung für nächsten Wegpunkt (falls Pickstation)
        pickstation_at_next = self.state.find_pickstation_at(next_waypoint)
        if pickstation_at_next is not None:
            # Wenn Port noch nicht für diesen Roboter reserviert ist, versuchen zu reservieren
            if not pickstation_at_next.is_reserved_by(robot.robot_id):
                if not pickstation_at_next.reserve(robot.robot_id):
                    # Port ist für anderen Roboter reserviert → Move verzögern
                    print(
                        f"[INFO] Robot {robot.robot_id} cannot reserve port "
                        f"{pickstation_at_next.station_id} at {next_waypoint} "
                        f"at time {self.state.t}, retrying..."
                    )
                    delayed_event = self.event_builder.delay_event(
                        event=event,
                        current_time=self.state.t,
                    )
                    self.event_queue.push(delayed_event)
                    return

        # Reservierung prüfen (Sicherheitsprüfung)
        if not self.state.reservation_table.is_free(
                *next_waypoint, self.state.t, exclude_robot=robot.robot_id
        ):
            # Blockiert - Event verzögern
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

        # ✅ NEU: Harte Laufzeit-Kollisionsvermeidung für ALLE Zellen
        for other in self.state.robots:
            if other.robot_id == robot.robot_id:
                continue
            if other.get_position() == next_waypoint:
                # NEU: Sofortiges Replanning nach wenigen Retries
                if event.retry_count >= self.max_move_retries_before_replan:
                    # NEU: Prüfe ob der blockierende Roboter selbst feststeckt
                    if event.retry_count >= self.max_move_retries_before_force_replan:
                        # Versuche den blockierenden Roboter zur Neuplanung zu zwingen
                        if self._force_stale_robot_to_replan(other):
                            # Blockierender Robot plant neu → kurz warten und erneut versuchen
                            delayed_event = self.event_builder.delay_event(event, self.state.t)
                            self.event_queue.push(delayed_event)
                            return

                        # Idle-Blocker ohne Task frühzeitig aus dem Weg bewegen.
                        if other.current_task is None and other.status == "idle":
                            self._handle_robot_becomes_idle(other)

                    # Neuen Pfad berechnen, der die Blockade umgeht
                    print(
                        f"[REPLAN] Robot {robot.robot_id} replanning path to avoid "
                        f"robot {other.robot_id} at {next_waypoint}"
                    )

                    # NEU: Deadlock-Check VOR dem Replanning
                    if hasattr(self.state, 'traffic_manager'):
                        tm = self.state.traffic_manager
                        # Wartebeziehung registrieren
                        tm.deadlock_detector.register_wait(
                            waiting_robot_id=robot.robot_id,
                            blocking_robot_id=other.robot_id,
                            reason="path_blocked",
                            current_time=self.state.t,
                        )

                        # Prüfen ob Deadlock entstanden ist
                        victim_id = tm.check_and_resolve_deadlock(
                            robots=self.state.robots,
                            scheduler=self.scheduler,
                            current_time=self.state.t,
                        )

                        if victim_id is not None:
                            # Deadlock erkannt – Victim muss ausweichen
                            victim = next(
                                (r for r in self.state.robots if r.robot_id == victim_id),
                                None
                            )
                            if victim is not None and victim.robot_id == robot.robot_id:
                                # Dieser Robot soll ausweichen – warte kurz und versuche erneut
                                print(
                                    f"[DEADLOCK] Robot {robot.robot_id} yielding to resolve deadlock"
                                )
                                delayed_event = self.event_builder.delay_event(event, self.state.t)
                                self.event_queue.push(delayed_event)
                                return
                            elif victim is not None:
                                # Anderer Robot soll ausweichen – normal fortfahren
                                pass

                    self._replan_path_around_obstacle(robot, next_waypoint, event)
                    return

                # Erste Retries: Kurz warten
                print(
                    f"[WARNING] Robot {robot.robot_id} blocked at occupied cell "
                    f"{next_waypoint} by robot {other.robot_id} at time {self.state.t}, "
                    f"retrying... (attempt {event.retry_count + 1}/{self.max_move_retries_before_replan + 1})"
                )
                delayed_event = self.event_builder.delay_event(
                    event=event,
                    current_time=self.state.t,
                )
                self.event_queue.push(delayed_event)
                return

        # Alte Position freigeben
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

        # NEU: Bounds-Check nach dem Move
        gx, gy = new_position
        gw, gd = self.state.grid.width, self.state.grid.depth
        if not (0 <= gx < gw and 0 <= gy < gd):
            print(
                f"[ILLEGAL_POS][MOVE] t={self.state.t} robot={robot.robot_id} "
                f"moved to out-of-bounds position {new_position} "
                f"(grid={gw}x{gd})"
            )

        # NEU: Kollisions-Check nach dem Move
        pos_to_robot = {}
        for r in self.state.robots:
            pos = r.get_position()
            if pos is None:
                continue
            if pos in pos_to_robot:
                other_id = pos_to_robot[pos]
                print(
                    f"[COLLISION][MOVE] t={self.state.t} pos={pos} "
                    f"robots={other_id},{r.robot_id}"
                )
            else:
                pos_to_robot[pos] = r.robot_id

        # ✅ NEU: Port-Enter/Leave-Logik
        # Roboter fährt AUF eine Pickstation-Position
        pickstation_at_new = self.state.find_pickstation_at(new_position)
        if pickstation_at_new is not None:
            # Roboter betritt Port (prüft Reservierung intern)
            pickstation_at_new.robot_enters(robot.robot_id)

        # Roboter verlässt eine Pickstation-Position
        if old_position is not None:
            pickstation_at_old = self.state.find_pickstation_at(old_position)
            if pickstation_at_old is not None and old_position != new_position:
                # Verlassen des Ports gibt Reservierung automatisch frei
                pickstation_at_old.robot_leaves()

        # Prüfen ob Ziel erreicht
        if robot.has_reached_destination():
            self._cleanup_past_reservations(robot)

            # ✅ NEU: Wenn Robot keinen Task hat (nach Pickstation-Exit)
            # wird er automatisch idle und verfügbar für neue Tasks
            if robot.current_task is None:
                robot.set_status("idle")
                # Idle-Roboter dürfen NICHT in Pufferzone/Port parken
                self._handle_robot_becomes_idle(robot)

            return

        # Noch nicht am Ziel - nächstes ROBOT_MOVE Event erzeugen
        move_cost = self.event_builder.cost_model.config.move_cost_per_grid_step
        next_move_event = self.event_builder.build_robot_move_event(
            robot=robot,
            time=self.state.t + move_cost,
        )
        self.event_queue.push(next_move_event)

    def _replan_path_around_obstacle(self, robot, blocked_position, event):
        """
        Berechnet einen neuen Pfad für den Roboter, der die blockierte Position umgeht.
        """
        # Aktuelles Ziel aus dem geplanten Pfad holen
        if not robot.planned_path:
            return

        final_destination = robot.planned_path[-1]
        current_position = robot.get_position()

        # Blockierte Zellen für Pathfinding markieren
        blocked_cells = {blocked_position}

        # Neuen Pfad berechnen
        new_path = self.event_builder.cost_model.calculate_path(
            from_position=current_position,
            to_position=final_destination,
            robot=robot,
            state=self.state,
            current_time=self.state.t,
            blocked_cells=blocked_cells,  # NEU: Zusätzliche Blockaden
        )

        if new_path and len(new_path) > 0:
            # Alte Reservierungen freigeben
            self.state.traffic_manager.release_robot_reservations(robot)

            # Neuen Pfad reservieren und setzen
            success, _ = self.state.reservation_table.reserve_path(
                robot_id=robot.robot_id,
                path=new_path,
                start_time=self.state.t,
            )

            if success:
                robot.set_path(new_path, robot.path_target_action)
                # Neues Move-Event erzeugen
                move_event = self.event_builder.build_robot_move_event(
                    robot=robot,
                    time=self.state.t + 1,
                )
                self.event_queue.push(move_event)
                return

        # Fallback: Wenn kein Alternativpfad gefunden, weiter warten
        delayed_event = self.event_builder.delay_event(event, self.state.t)
        self.event_queue.push(delayed_event)

    def _handle_robot_pickup(self, event):
        """
        Verarbeitet Phase 1 einer Zwei-Phasen-Aktion: Roboter nimmt Bin auf.

        Nach erfolgreichem Pickup:
        1. Bin wird aus dem Stack entfernt (bei relocate/remove_target)
        2. Bin wird als "carried by robot" markiert
        3. Pfad zum Ziel wird geplant
        4. ROBOT_MOVE Events werden erzeugt
        5. Am Ende: ROBOT_DROP Event
        """
        robot = event.payload.get("robot")
        action = event.payload.get("action")
        request = event.payload.get("request")

        if robot is None:
            raise RuntimeError("Cannot handle robot pickup: event has no robot")

        action_type = action.get("type")
        bin_id = action.get("bin_id")

        # ✅ Prüfe ob Roboter physisch auf dem Stack steht
        from_stack = self._get_stack_by_id(self.state, action.get("from_stack"))

        if from_stack is not None:
            stack_position = self._parse_stack_position(from_stack)
            robot_position = robot.get_position()

            if robot_position != stack_position:
                task = robot.current_task

                # 2. Schutzschwelle: Task hart zurück in waiting, um Livelock zu brechen
                if (
                    task is not None
                    and event.retry_count >= self.max_pickup_position_retries_before_requeue
                ):
                    print(
                        f"[REQUEUE][PICKUP_POS] t={self.state.t} robot={robot.robot_id} "
                        f"action={action_type} bin={bin_id} "
                        f"retry={event.retry_count} -> requeue task {task.request_id}"
                    )
                    robot.clear_task()
                    self.active_queue.add_waiting_task(task)
                    return

                # 1. Schutzschwelle: früher Bewegungspfad zum Pickup neu planen
                if (
                    task is not None
                    and event.retry_count >= self.max_pickup_position_retries_before_replan
                ):
                    print(
                        f"[REPLAN][PICKUP_POS] t={self.state.t} robot={robot.robot_id} "
                        f"action={action_type} bin={bin_id} "
                        f"(robot at {robot_position}, stack at {stack_position}) "
                        f"retry={event.retry_count} -> reschedule movement to pickup"
                    )
                    self._schedule_next_action_for_task_new(
                        robot=robot,
                        task=task,
                        next_action=action,
                        base_time=self.state.t,
                    )
                    return

                # Vor Replan-Schwelle: normal verzögern
                print(
                    f"[BLOCKED][PICKUP] t={self.state.t} robot={robot.robot_id} "
                    f"not at stack {action.get('from_stack')} "
                    f"(robot at {robot_position}, stack at {stack_position}) "
                    f"- retrying ({event.retry_count + 1}/{self.max_pickup_position_retries_before_replan})"
                )
                delayed_event = self.event_builder.delay_event(event, self.state.t)
                self.event_queue.push(delayed_event)
                return

        # Constraint-Prüfung für Pickup
        can_pickup, reason = self._can_pickup(action, self.state)

        if not can_pickup:
            print(
                f"[BLOCKED][PICKUP] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} reason={reason}"
            )

            task = robot.current_task if robot is not None else None

            # Defensiv: veraltete remove_target-Pickups nicht endlos retrien.
            # Diese können auftreten, wenn der Task zwischenzeitlich in eine
            # spätere Phase gewechselt ist oder bereits auf eine andere Ziel-Bin zeigt.
            if action_type == "remove_target" and task is not None:
                stale_phase = task.phase != task.PHASE_RETRIEVE_TARGET
                stale_target = bin_id is not None and task.target_bin_id != bin_id

                if stale_phase or stale_target:
                    print(
                        f"[REPLAN][PICKUP_REMOVE_TARGET] t={self.state.t} "
                        f"robot={robot.robot_id} bin={bin_id} "
                        f"task={task.request_id} phase={task.phase} "
                        f"target={task.target_bin_id} -> drop stale pickup event"
                    )
                    self._schedule_next_action_for_task_new(
                        robot=robot,
                        task=task,
                        next_action=None,
                        base_time=self.state.t,
                    )
                    return

            # Defensiv: veraltete Return-Pickups können auftreten, wenn die
            # Target-Bin bereits zurückgelegt wurde (status='stored').
            # In diesem Fall nicht endlos retrien, sondern Task neu auswerten.
            if action_type == "return" and task is not None and bin_id is not None:
                bin_obj = self.state.get_bin_by_id(bin_id)
                if bin_obj is not None and bin_obj.get_status() == "stored":
                    print(
                        f"[REPLAN][PICKUP_RETURN] t={self.state.t} robot={robot.robot_id} "
                        f"bin={bin_id} already stored -> re-evaluating next action"
                    )
                    self._schedule_next_action_for_task_new(
                        robot=robot,
                        task=task,
                        next_action=None,
                        base_time=self.state.t,
                    )
                    return

            if reason and "not on top" in reason:
                if task is not None:
                    new_action = self.scheduler.strategy.next_action(self.state, task)
                    if new_action is not None:
                        print(
                            f"[REPLAN][PICKUP] t={self.state.t} robot={robot.robot_id} "
                            f"task replanning due to stale stack state"
                        )
                        self._schedule_next_action_for_task_new(
                            robot=robot,
                            task=task,
                            next_action=new_action,
                            base_time=self.state.t,
                        )
                        return

            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return

        # Bin aufnehmen: entweder aus Stack oder von Pickstation
        if from_stack is not None:
            bin_obj = from_stack.pop()

            if bin_obj.bin_id != bin_id:
                raise RuntimeError(
                    f"Pickup mismatch: expected bin {bin_id}, got {bin_obj.bin_id}"
                )

            # Bin als "in transit" / "carried" markieren
            bin_obj.mark_in_transit()
            bin_obj.set_stack(None)
            bin_obj.set_level(None)

            # Sync Stack-Metadata
            self._sync_stack_bin_metadata(from_stack)
        else:
            bin_obj = self.state.get_bin_by_id(bin_id)

            if bin_obj is None:
                raise RuntimeError(f"Cannot pickup: bin {bin_id} not found")

            # Return von Pickstation: Bin exklusiv „in transit“ markieren,
            # damit kein zweiter Roboter dieselbe Bin parallel aufnehmen kann.
            if action_type == "return" and action.get("from_stack") is None:
                bin_obj.mark_in_transit()
                bin_obj.set_stack(None)
                bin_obj.set_level(None)

        print(
            f"[TRACE][PICKUP] t={self.state.t} robot={robot.robot_id} "
            f"bin={bin_id} from={action.get('from_stack')}"
        )

        # Zielposition bestimmen
        target_position = self._get_drop_position_for_action(action)

        if target_position is None:
            raise RuntimeError(
                f"Cannot determine drop position for action {action_type}"
            )

        current_position = robot.get_position()

        # Pfad zum Ziel berechnen
        path = self.event_builder.cost_model.calculate_path(
            from_position=current_position,
            to_position=target_position,
            robot=robot,
            state=self.state,
            current_time=self.state.t,
        )

        # Pickup-Dauer (Arm runter, greifen, Arm hoch)
        pickup_duration = self._calculate_pickup_duration(action, self.state)
        drop_time = self.state.t + pickup_duration

        if not path:
            # Roboter ist bereits am Ziel - direkt Drop
            drop_event = self.event_builder.build_robot_drop_event(
                robot=robot,
                action=action,
                request=request,
                time=drop_time,
            )
            self.event_queue.push(drop_event)
            return

        # Pfad-Events erzeugen
        robot.set_path(path, target_action=None)

        current_time = drop_time
        move_cost = self.event_builder.cost_model.config.move_cost_per_grid_step

        for _ in range(len(path)):
            current_time += move_cost
            move_event = self.event_builder.build_robot_move_event(
                robot=robot,
                time=current_time,
            )
            self.event_queue.push(move_event)

        # Nach allen Moves: Drop-Event
        drop_duration = self._calculate_drop_duration(action, self.state)
        drop_event = self.event_builder.build_robot_drop_event(
            robot=robot,
            action=action,
            request=request,
            time=current_time + drop_duration,
        )
        self.event_queue.push(drop_event)


    def _handle_robot_drop(self, event):
        """
        Verarbeitet Phase 2 einer Zwei-Phasen-Aktion: Roboter legt Bin ab.

        Nach erfolgreichem Drop:
        1. Bin wird in den Ziel-Stack eingefügt
        2. Bin-Status wird aktualisiert
        3. Task-Status wird aktualisiert
        4. Nächste Aktion wird geplant
        """
        robot = event.payload.get("robot")
        action = event.payload.get("action")
        request = event.payload.get("request")

        if robot is None:
            raise RuntimeError("Cannot handle robot drop: event has no robot")

        action_type = action.get("type")
        bin_id = action.get("bin_id")

        # Constraint-Prüfung für Drop
        can_drop, reason = self._can_drop(action, self.state)

        if not can_drop:
            # Defensiv: Veraltetes Return-Drop-Event kann auftreten,
            # wenn ein älteres Retry-Event nach erfolgreicher Rückgabe
            # noch in der Queue steht.
            if action_type == "return" and reason == "bin not in transit":
                print(
                    f"[STALE][DROP_RETURN] t={self.state.t} robot={robot.robot_id} "
                    f"bin={bin_id} reason={reason} -> skip stale event"
                )
                self._schedule_next_action_for_same_task_new(event)
                return

            print(
                f"[BLOCKED][DROP] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} reason={reason}"
            )
            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return

        bin_obj = self.state.get_bin_by_id(bin_id)

        if bin_obj is None:
            raise RuntimeError(f"Cannot drop: bin {bin_id} not found")

        if action_type == "relocate":
            # Bin auf Buffer-Stack ablegen
            to_stack = self._get_stack_by_id(self.state, action.get("to_stack"))

            if to_stack is None:
                raise RuntimeError(f"Cannot drop: to_stack not found")

            to_stack.push(bin_obj)
            bin_obj.mark_transit_done()
            self._sync_stack_bin_metadata(to_stack)

            print(
                f"[TRACE][DROP_RELOCATE] t={self.state.t} robot={robot.robot_id} "
                f"bin={bin_id} to={action.get('to_stack')}"
            )


        elif action_type == "remove_target":
            # Bin an Pickstation abgeben
            bin_obj.set_status("at_pickstation")
            bin_obj.mark_transit_done()
            print(
                f"[TRACE][DROP_TARGET] t={self.state.t} robot={robot.robot_id} "
                f"bin={bin_id} to=pickstation"
            )
            # NEU: Metrik für Pickstation-Ankunft erfassen
            task = robot.current_task
            if task is not None:
                digging_depth = self._resolve_digging_depth_for_task(task)
                self.metrics.record_digging_depth(digging_depth)
                self.metrics.record_target_bin_at_pickstation(
                    self.state,
                    action,
                    request=task.request
                )

        elif action_type == "return":
            # Bin zurück in Stack legen
            to_stack = self._get_stack_by_id(self.state, action.get("to_stack"))

            if to_stack is None:
                raise RuntimeError(f"Cannot return: to_stack not found")

            to_stack.push(bin_obj)
            bin_obj.mark_transit_done()
            self._sync_stack_bin_metadata(to_stack)

            print(
                f"[TRACE][DROP_RETURN] t={self.state.t} robot={robot.robot_id} "
                f"bin={bin_id} to={action.get('to_stack')}"
            )

        # Task-Update
        self._update_task_after_successful_action_new(event)

        # Spezialfall: remove_target -> Pickstation-Service starten
        if action_type == "remove_target":
            self._attach_batched_requests_to_task(event)
            self._start_pickstation_service_and_release_robot(event)
            return

        # Spezialfall: Target-Return -> Request abschließen
        if action_type == "return" and action.get("return_kind") == "target":
            return

        # Nächste Aktion planen
        self._schedule_next_action_for_same_task_new(event)


    def _can_pickup(self, action, state):
        """Prüft ob Pickup möglich ist."""
        action_type = action.get("type")

        if action_type in ("relocate", "remove_target"):
            from_stack = self._get_stack_by_id(state, action.get("from_stack"))
            bin_id = action.get("bin_id")

            if from_stack is None:
                return False, "from_stack not found"

            if from_stack.is_locked():
                return False, "from_stack is locked"

            top_bin = from_stack.peek()
            if top_bin is None or top_bin.bin_id != bin_id:
                return False, f"expected bin {bin_id} not on top"

            return True, None

        if action_type == "return":
            from_stack_id = action.get("from_stack")
            bin_id = action.get("bin_id")

            if from_stack_id is None:
                # Return von Pickstation
                bin_obj = state.get_bin_by_id(bin_id)
                if bin_obj is None:
                    return False, "bin not found"
                if bin_obj.get_status() != "at_pickstation":
                    return False, "bin not at pickstation"
                if getattr(bin_obj, "in_transit", False):
                    return False, "bin already in transit"
                if bin_obj.get_stack() is not None:
                    return False, "bin still assigned to stack"
                return True, None

            # Return von Buffer
            from_stack = self._get_stack_by_id(state, from_stack_id)
            if from_stack is None:
                return False, "from_stack not found"

            top_bin = from_stack.peek()
            if top_bin is None or top_bin.bin_id != bin_id:
                return False, f"expected bin {bin_id} not on top"

            return True, None

        return False, f"unknown action type: {action_type}"


    def _can_drop(self, action, state):
        """Prüft ob Drop möglich ist."""
        action_type = action.get("type")

        if action_type == "remove_target":
            # Drop an Pickstation - immer möglich
            return True, None

        if action_type in ("relocate", "return"):
            to_stack = self._get_stack_by_id(state, action.get("to_stack"))

            if to_stack is None:
                return False, "to_stack not found"

            if to_stack.is_locked():
                return False, "to_stack is locked"

            # Kapazitätsprüfung
            max_height = getattr(state.config, "max_stack_height", None)
            if max_height is not None and to_stack.height() >= max_height:
                return False, "to_stack is full"

            bin_id = action.get("bin_id")
            bin_obj = state.get_bin_by_id(bin_id)
            if bin_obj is None:
                return False, "bin not found"
            if not getattr(bin_obj, "in_transit", False):
                return False, "bin not in transit"

            return True, None

        return False, f"unknown action type: {action_type}"


    def _get_drop_position_for_action(self, action):
        """Bestimmt die Zielposition für den Drop."""
        action_type = action.get("type")

        if action_type == "relocate":
            return self._resolve_position(action.get("to_stack"))

        if action_type == "remove_target":
            # Zur Pickstation
            if self.state.pickstations:
                return self.state.pickstations[0].position
            return self.event_builder.cost_model.config.pickstation_position

        if action_type == "return":
            return self._resolve_position(action.get("to_stack"))

        return None


    def _calculate_pickup_duration(self, action, state):
        """Berechnet Dauer für Pickup (Arm runter, greifen, Arm hoch)."""
        config = self.event_builder.cost_model.config

        from_stack = self._get_stack_by_id(state, action.get("from_stack"))
        access_depth = 0
        if from_stack is not None:
            access_depth = max(0, from_stack.height() - 1)

        arm_cost = 2 * access_depth * config.arm_move_cost_per_level
        grip_cost = config.grip_cost

        return arm_cost + grip_cost


    def _calculate_drop_duration(self, action, state):
        """Berechnet Dauer für Drop (Arm runter, loslassen, Arm hoch)."""
        config = self.event_builder.cost_model.config

        action_type = action.get("type")

        if action_type == "remove_target":
            # Drop an Pickstation - kein Stack-Tiefenzugang
            return config.drop_cost

        to_stack = self._get_stack_by_id(state, action.get("to_stack"))
        access_depth = 0
        if to_stack is not None:
            access_depth = max(0, to_stack.height())

        arm_cost = 2 * access_depth * config.arm_move_cost_per_level
        drop_cost = config.drop_cost

        return arm_cost + drop_cost


    def _sync_stack_bin_metadata(self, stack):
        """Synchronisiert Bin-Metadaten nach Stack-Änderung."""
        stack_position = self._parse_stack_position(stack)

        for level, bin_obj in enumerate(stack.bins):
            bin_obj.set_stack(stack_position)
            bin_obj.set_level(level)
            bin_obj.set_status("stored")


    def _parse_stack_position(self, stack):
        """Wandelt Stack-ID in (x, y) um."""
        stack_id = stack.stack_id

        if isinstance(stack_id, tuple):
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")
            if len(parts) == 3:
                return int(parts[1]), int(parts[2])

        return stack_id


    def _update_task_after_successful_action_new(self, event):
        """Task-Update nach erfolgreichem Drop."""
        robot = event.payload.get("robot")
        if robot is None:
            return

        task = robot.current_task
        if task is None:
            return

        action = event.payload.get("action")
        action_type = action.get("type")

        if action_type == "relocate":
            bin_id = action.get("bin_id")
            task.remember_relocation(
                bin_id=bin_id,
                from_stack=action.get("from_stack"),
                buffer_stack=action.get("to_stack"),
            )
            self.active_queue.register_blocker_ownership(bin_id, task)

        elif action_type == "remove_target":
            task.target_removed = True

        elif action_type == "return":
            self._update_task_after_successful_return(task, action, robot)

    def _update_task_after_successful_action_new(self, event):
        """Task-Update nach erfolgreichem Drop."""
        robot = event.payload.get("robot")
        if robot is None:
            return

        task = robot.current_task
        if task is None:
            return

        action = event.payload.get("action")
        action_type = action.get("type")

        if action_type == "relocate":
            bin_id = action.get("bin_id")
            task.remember_relocation(
                bin_id=bin_id,
                from_stack=action.get("from_stack"),
                buffer_stack=action.get("to_stack"),
            )
            self.active_queue.register_blocker_ownership(bin_id, task)

        elif action_type == "remove_target":
            task.target_removed = True

        elif action_type == "return":
            self._update_task_after_successful_return(task, action, robot)

    def _schedule_next_action_for_same_task_new(self, event):
        """Plant nächste Aktion als Zwei-Phasen-Aktion (event-basierter Entry-Point)."""
        robot = event.payload.get("robot")
        if robot is None:
            return

        task = robot.current_task
        if task is None:
            return

        self._schedule_next_action_for_task_new(
            robot=robot,
            task=task,
            next_action=None,
            base_time=self.state.t,
        )

    def _schedule_next_action_for_task_new(self, robot, task, next_action=None, base_time=None):
        """Plant nächste Aktion als Zwei-Phasen-Aktion (task-basierter Helper)."""
        if robot is None or task is None:
            return

        if base_time is None:
            base_time = self.state.t

        if next_action is None:
            next_action = self.scheduler.strategy.next_action(self.state, task)

        if next_action is None:
            self.active_queue.add_waiting_task(task)
            robot.clear_task()
            return

        action_type = next_action.get("type")

        # Physische Aktionen: Zwei-Phasen-System
        if action_type in ("relocate", "remove_target", "return"):
            pickup_position = self._get_target_position_for_action(next_action)

            if pickup_position is None:
                raise RuntimeError(
                    f"Cannot determine pickup position for action {action_type}"
                )

            current_position = robot.get_position()

            path = self.event_builder.cost_model.calculate_path(
                from_position=current_position,
                to_position=pickup_position,
                robot=robot,
                state=self.state,
                current_time=base_time,
            )

            if not path:
                pickup_event = self.event_builder.build_robot_pickup_event(
                    robot=robot,
                    action=next_action,
                    request=task.request,
                    time=base_time + 1,
                )
                self.event_queue.push(pickup_event)
                return

            robot.set_path(path, target_action=None)

            current_time = base_time
            move_cost = self.event_builder.cost_model.config.move_cost_per_grid_step

            for _ in range(len(path)):
                current_time += move_cost
                move_event = self.event_builder.build_robot_move_event(
                    robot=robot,
                    time=current_time,
                )
                self.event_queue.push(move_event)

            pickup_event = self.event_builder.build_robot_pickup_event(
                robot=robot,
                action=next_action,
                request=task.request,
                time=current_time + 1,
            )
            self.event_queue.push(pickup_event)
            return

        # Nicht-physische Aktionen (request_complete etc.)
        duration = self.event_builder.calculate_action_duration(
            action=next_action,
            state=self.state,
            robot=robot,
        )

        next_event = self.event_builder.build_event_from_action(
            action=next_action,
            request=task.request,
            robot=robot,
            time=base_time + duration,
        )

        self.event_queue.push(next_event)


    def _handle_robot_becomes_idle(self, robot):
        """
        Behandelt Roboter der idle wird.

        Wenn Roboter in Pufferzone oder auf einem Port steht: Muss diese verlassen.
        """
        current_pos = robot.get_position()

        if current_pos is None:
            return

        if self.idle_parking.must_leave_current_position(current_pos):
            # Finde nächste Parkposition
            occupied = {
                r.get_position()
                for r in self.state.robots
                if r is not robot and r.get_position() is not None
            }
            target = self.idle_parking.find_nearest_parking_position(
                current_pos, occupied
            )

            if target is not None:
                # Plane Pfad zur Parkposition (niedrige Priorität, kein Task)
                self._plan_idle_move(robot, target)
            else:
                # Keine Parkposition frei (sollte selten sein)
                print(f"[WARNING] No parking position for robot {robot.robot_id}")


    ###############
    def _force_stale_robot_to_replan(self, robot):
        """
        Zwingt einen blockierten Roboter, dessen Task veraltet ist, zur Neuplanung.

        Wird aufgerufen, wenn ein anderer Roboter durch diesen Robot blockiert wird
        und festgestellt wird, dass der blockierende Robot selbst nicht vorankommt.
        """
        task = robot.current_task
        if task is None:
            return False

        # Prüfe ob der Task noch gültig ist
        new_action = self.scheduler.strategy.next_action(self.state, task)

        if new_action is None:
            # Task ist in einem Wartezustand (z.B. WAIT_FOR_PICKSTATION)
            return False

        # Prüfe ob die aktuelle Aktion noch durchführbar ist
        can_execute, reason = self.constraint_manager.can_execute_with_reason(
            new_action, self.state
        )

        if not can_execute and reason and "not on top" in reason:
            # Task hat veralteten State → Neuplanung
            print(
                f"[FORCE_REPLAN] t={self.state.t} robot={robot.robot_id} "
                f"forced to replan due to stale state: {reason}"
            )
            self._schedule_next_action_for_task_new(
                robot=robot,
                task=task,
                next_action=new_action,
                base_time=self.state.t,
            )
            return True

        return False


    def _plan_idle_move(self, robot, target_position):
        """
        Plant einen reinen Idle-Move zu einer Parkposition.

        - Keine Request- oder Task-Bindung
        - target_action=None → Roboter bleibt danach idle
        - Pfad-Reservierung weiterhin über TrafficManager/ReservationTable
        """
        current_position = robot.get_position()
        if current_position is None:
            return

        path = self.event_builder.cost_model.calculate_path(
            from_position=current_position,
            to_position=target_position,
            robot=robot,
            state=self.state,
            current_time=self.state.t,
        )

        if not path:
            # Bereits an Ziel oder kein Pfad → nichts tun
            return

        path_events = self.event_builder.build_path_events(
            robot=robot,
            path=path,
            target_action=None,
            request=None,
            start_time=self.state.t,
            state=self.state,
        )

        if path_events is None:
            # Pfad-Reservierung fehlgeschlagen → wir geben auf,
            # da dies nur ein weicher Komfort-Move ist.
            print(
                f"[INFO] Idle move for robot {robot.robot_id} to {target_position} "
                f"could not be reserved"
            )
            return

        for ev in path_events:
            self.event_queue.push(ev)

    def _cleanup_past_reservations(self, robot):
        """
        Räumt vergangene Reservierungen eines Roboters auf, behält aber die aktuelle Position.
        """
        current_time = self.state.t
        current_position = robot.get_position()

        reservations = self.state.reservation_table.get_reservations_for_robot(robot.robot_id)

        for (x, y, t) in reservations:
            # Vergangene Reservierungen freigeben
            if t < current_time:
                self.state.reservation_table.release(robot.robot_id, x, y, t)
            # Aktuelle Position behalten (falls reserviert)
            elif (x, y) == current_position and t == current_time:
                # Behalte diese Reservierung
                pass

    def _cleanup_robot_reservations_except_current(self, robot_id, current_pos, current_time):
        """
        Gibt alle Reservierungen eines Roboters frei, AUSSER die aktuelle Position zur aktuellen Zeit.

        Verwendung:
        - Wenn Roboter an Pickstation "andockt"
        - Roboter steht physisch auf Position (z.B. (-1, y))
        - Diese Position muss reserviert bleiben, um Kollisionen zu verhindern
        - Erst beim Verlassen (neuer Pfad) wird die alte Reservierung durch neue ersetzt

        Args:
            robot_id: ID des Roboters
            current_pos: (x, y) - Aktuelle Position des Roboters
            current_time: Aktueller Simulationszeitpunkt
        """
        if current_pos is None:
            # Roboter hat keine Position (sollte nicht passieren, aber zur Sicherheit)
            self.state.reservation_table.release_all(robot_id)
            return

        x, y = current_pos

        # Hole alle Reservierungen dieses Roboters
        reservations = self.state.reservation_table.get_reservations_for_robot(robot_id)

        # Kopie erstellen, da wir während Iteration löschen
        reservations_copy = list(reservations)

        for res_x, res_y, res_t in reservations_copy:
            # Behalte nur die aktuelle Position zur aktuellen Zeit
            if res_x == x and res_y == y and res_t == current_time:
                continue  # Diese Reservierung NICHT freigeben - Roboter steht dort!

            # Alle anderen Reservierungen freigeben
            self.state.reservation_table.release(robot_id, res_x, res_y, res_t)

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

            # ----------------------------------------------------------
            # 1) INTELLIGENTER SKIP NUR FÜR RELOCATE-AKTIONEN (BLOCKER)
            # ----------------------------------------------------------
            action_type = action.get("type")
            if action_type == "relocate" and robot is not None:
                bin_id = action.get("bin_id")
                from_stack_id = action.get("from_stack")

                if bin_id is not None and from_stack_id is not None:
                    actual_stack, actual_level = self._find_bin_location(bin_id)

                    if actual_stack is None:
                        # Die Bin liegt auf KEINEM Stack mehr.
                        # Für eine Blocker-Relocate bedeutet das:
                        # - Sie blockiert den ursprünglichen Stack nicht mehr.
                        # - Jemand hat sie bereits entfernt (in Transit, Pickstation
                        #   oder Rücklagerung).
                        # → Sicher zu skippen, da das ursprüngliche Ziel
                        #   (Blocker weg) bereits erreicht ist.
                        print(
                            f"[SKIP] t={self.state.t}, robot={robot.robot_id}, "
                            f"request={request.request_id if request is not None else None}, "
                            f"relocate for bin {bin_id} skipped: "
                            f"bin not on any stack anymore (already moved or processed)"
                        )
                        self._schedule_next_action_for_same_task_new(event)
                        return

                    if actual_stack.stack_id != from_stack_id:
                        # SICHERER FALL:
                        # Die Blocker-Bin wurde bereits von einem anderen Roboter
                        # wegbewegt und steht nicht mehr auf dem ursprünglichen Stack.
                        # → Unser Task-Ziel (freie Sicht auf die Target-Bin) ist
                        #   bereits erreicht, diese Relocation können wir überspringen.
                        print(
                            f"[SKIP] t={self.state.t}, robot={robot.robot_id}, "
                            f"request={request.request_id if request is not None else None}, "
                            f"relocate for bin {bin_id} skipped: "
                            f"bin already moved off {from_stack_id} "
                            f"to {actual_stack.stack_id}"
                        )

                        # Wichtig: Wir führen KEINE Aktion aus, aktualisieren den Task
                        # nicht künstlich, sondern fragen einfach die nächste Aktion
                        # aus der Strategie ab. Die Strategie sieht den aktuellen
                        # echten Zustand (Bin steht woanders) und plant entsprechend neu.
                        self._schedule_next_action_for_same_task_new(event)
                        return

            # ✅ NEU: REVALIDIERUNG bei remove_target
            if action_type == "remove_target" and robot is not None:
                task = robot.current_task
                if task is not None and event.retry_count >= 5:
                    # Nach 5 Retries: Prüfe ob Stack sich verändert hat
                    if self._stack_state_changed(task):
                        print(
                            f"[REVALIDATE] t={self.state.t}, robot={robot.robot_id}, "
                            f"task={task.request_id}, stack changed → replanning relocations"
                        )

                        # Lösche alte Relocation-Plan
                        task.temp_storage.clear()

                        # Frage Strategie nach neuer Relocation-Sequenz
                        # (wird beim nächsten next_action() neu berechnet)
                        self._schedule_next_action_for_same_task_new(event)
                        return

            # ----------------------------------------------------------
            # 2) RETRY-LIMIT + REPLAN FÜR HOFFNUNGSLOSE FÄLLE
            # ----------------------------------------------------------
            if (
                    robot is not None
                    and event.retry_count >= self.max_action_retries_before_replan
            ):
                task = getattr(robot, "current_task", None)

                if task is not None:
                    print(
                        f"[REPLAN] t={self.state.t}, robot={robot.robot_id}, "
                        f"task={task.request_id}, action={action}, "
                        f"stuck after {event.retry_count} retries → requeue task"
                    )

                    # Task vom Roboter lösen und zurück in die Warteschlange geben.
                    robot.clear_task()
                    self.active_queue.add_waiting_task(task)

                # KEIN weiteres delay_event für diese Aktion
                return

            # ----------------------------------------------------------
            # 3) STANDARD-VERHALTEN: VERZÖGERN UND SPÄTER NOCHMAL VERSUCHEN
            # ----------------------------------------------------------
            delayed_event = self.event_builder.delay_event(
                event=event,
                current_time=self.state.t,
            )
            self.event_queue.push(delayed_event)
            return

        # NEU: Aktuelle Position für die Aktionsdauer reserviert halten
        robot = event.payload.get("robot")
        if robot is not None:
            current_pos = robot.get_position()
            if current_pos is not None:
                # Reserviere Position für aktuelle Zeit
                self.state.reservation_table.reserve(
                    robot.robot_id, *current_pos, self.state.t
                )

        # in_transit setzen VOR Ausführung
        self._mark_bin_in_transit(action, state=self.state, in_transit=True)

        if action.get("type") == "remove_target":
            # WP5/RQ3: Digging-Depth pro Retrieval erfassen
            robot = event.payload.get("robot")
            task = getattr(robot, "current_task", None)
            digging_depth = self._resolve_digging_depth_for_task(task)
            self.metrics.record_digging_depth(digging_depth)

            request = event.payload.get("request")
            self.metrics.record_target_bin_at_pickstation(self.state, action, request)

            # Access-Count Tracking: Jeder erfolgreiche Retrieval zählt
            bin_id = action.get("bin_id")
            if bin_id is not None:
                bin_obj = self.state.get_bin_by_id(bin_id)
                if bin_obj is not None:
                    bin_obj.increment_access_count()

        self.executor.execute(event, self.state)

        action_type = action.get("type")
        bin_id = action.get("bin_id")
        request = event.payload.get("request")
        robot = event.payload.get("robot")
        task = getattr(robot, "current_task", None) if robot is not None else None

        if bin_id == 102:
            print(
                f"[TRACE][POST_ACTION] t={self.state.t} type={action_type} bin={bin_id} "
                f"req={request.request_id if request else None} "
                f"task={task.request_id if task else None} "
                f"task_phase={getattr(task, 'phase', None)} "
                f"target_stack_id={getattr(task, 'target_stack_id', None)} "
                f"actual_return_stack_id={getattr(task, 'actual_return_stack_id', None)} "
            )

        # in_transit zurücksetzen NACH erfolgreicher Ausführung
        self._mark_bin_in_transit(action, state=self.state, in_transit=False)

        self._update_robot_position_after_action(event)
        self._update_task_after_successful_action(event)

        if action.get("type") == "remove_target":
            self._attach_batched_requests_to_task(event)
            self._start_pickstation_service_and_release_robot(event)
            return

        # NEU: Bei einem erfolgreichen Target-Return wurde oben bereits
        # im selben Zeitschritt ein REQUEST_COMPLETE-Event erzeugt.
        # Wir planen daher KEINE weitere Aktion mehr für diesen Task.
        if action.get("type") == "return" and action.get("return_kind") == "target":
            return

        self._schedule_next_action_for_same_task_new(event)

    def _stack_state_changed(self, task):
        """
        Prüft ob der Zustand des Target-Stacks sich seit Task-Planung verändert hat.

        Returns:
            bool: True wenn Stack-Struktur sich geändert hat
        """
        if task.target_stack_id is None:
            return False

        # Hole aktuellen Stack-Zustand
        stack = self._get_stack_by_id(self.state, task.target_stack_id)
        if stack is None:
            return True  # Stack nicht gefunden = definitiv verändert

        # Prüfe ob Target-Bin noch am selben Ort ist
        target_bin_id = task.target_bin_id
        target_stack, target_level = self._find_bin_location(target_bin_id)

        if target_stack is None:
            return True  # Bin verschwunden

        if target_stack.stack_id != task.target_stack_id:
            return True  # Bin auf anderem Stack

        # Prüfe ob die Anzahl der Blocker sich geändert hat
        # (initial_blocker_count wird beim Task-Erstellen gesetzt)
        if hasattr(task, 'initial_blocker_count'):
            current_blocker_count = target_level
            if current_blocker_count != task.initial_blocker_count:
                return True

        return False

    def _resolve_digging_depth_for_task(self, task):
        """
        Liefert die Anzahl initialer Blocking-Bins für die Metrik-Erfassung.
        """
        if task is None:
            return 0

        initial_blocker_count = getattr(task, "initial_blocker_count", None)
        if initial_blocker_count is not None:
            try:
                return max(0, int(initial_blocker_count))
            except (TypeError, ValueError):
                pass

        temp_storage = getattr(task, "temp_storage", None)
        if temp_storage is None:
            return 0

        try:
            return max(0, len(temp_storage))
        except TypeError:
            return 0

    def _get_stack_by_id(self, state, stack_id):
        """
        Hilfsmethode: Findet Stack anhand ID (unterstützt Tuple und String).
        """
        if stack_id is None:
            return None

        if isinstance(stack_id, tuple):
            x, y = stack_id
            return state.grid.get_stack(x, y)

        for stack in state.grid.all_stacks():
            if stack.stack_id == stack_id:
                return stack

        return None

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
            # NEU: Robot an Return-Update übergeben, damit dort direkt
            # ein REQUEST_COMPLETE-Event eingeplant werden kann.
            self._update_task_after_successful_return(task, action, robot)
            return

    def _update_task_after_successful_return(self, task, action, robot):
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

            # NEU: Wir vertrauen dem tatsächlich verwendeten Rückgabe-Stack.
            # PlacementSelector kann über die Zeit neu entscheiden (z.B. nach Replan),
            # daher darf expected_stack nicht hart vorgegeben sein.
            to_stack_id = action.get("to_stack")

            # Merke den tatsächlich genutzten Rückgabe-Stack im Task
            task.actual_return_stack_id = to_stack_id

            # Target-Bin ist jetzt endgültig zurückgelegt
            task.mark_target_returned()

            # Direkt im selben Zeitschritt ein REQUEST_COMPLETE-Event einplanen.
            complete_action = {
                "type": "request_complete",
                "request_id": task.request_id,
                "bin_id": task.target_bin_id,
            }

            complete_event = self.event_builder.build_event_from_action(
                action=complete_action,
                request=task.request,
                robot=robot,
                time=self.state.t,  # gleiche Simulationszeit wie die Return-Action
            )

            self.event_queue.push(complete_event)
            return

        raise RuntimeError(
            f"Return action for task {task.request_id} has unknown return_kind: {return_kind}"
        )

    def _start_pickstation_service_and_release_robot(self, event):
        """
        Robot gibt Bin an Pickstation ab und MUSS diese sofort verlassen.

        Workflow:
        1. Robot kommt an Pickstation an
        2. Bin wird in Pickstation-Queue eingereiht
        3. Robot bekommt ROBOT_MOVE Event zum Verlassen der Pickstation
        4. Nach Exit wird Robot idle und für neue Tasks verfügbar
        """
        robot = event.payload.get("robot")

        if robot is None:
            raise RuntimeError("Cannot start pickstation service: event has no robot")

        task = robot.current_task

        if task is None:
            raise RuntimeError("Cannot start pickstation service: robot has no task")

        task.mark_waiting_at_pickstation()

        # Pickstation aus State ermitteln
        robot_position = robot.get_position()
        if robot_position is None:
            raise RuntimeError(
                f"Cannot start pickstation service: robot {robot.robot_id} has no position"
            )

        pickstation = self.state.get_nearest_pickstation(robot_position)
        if pickstation is None:
            raise RuntimeError(
                f"Cannot start pickstation service: no pickstation available "
                f"for robot {robot.robot_id}"
            )

        # Task zur Pickstation-Queue hinzufügen
        pickstation.enqueue(task, self.state.t)
        self.active_queue.add_pickstation_task(task)

        # ✅ Robot MUSS Pickstation verlassen
        exit_position = self._find_pickstation_exit_position(
            pickstation.position, robot.robot_id
        )

        if exit_position is None:
            # Keine freie Exit-Position → Robot bleibt blockiert
            print(
                f"[WARNING] Robot {robot.robot_id} cannot exit pickstation "
                f"{pickstation.station_id} - no free adjacent cell"
            )
            robot.clear_task()
            return

        # Reserviere Exit-Position
        success = self.state.reservation_table.reserve(
            robot_id=robot.robot_id,
            x=exit_position[0],
            y=exit_position[1],
            t=self.state.t + 1
        )

        if not success:
            print(
                f"[WARNING] Robot {robot.robot_id} cannot reserve exit position "
                f"{exit_position}"
            )
            robot.clear_task()
            return

        # Gebe Pickstation-Position frei (für nächsten Robot)
        self.state.reservation_table.release(
            robot.robot_id,
            robot_position[0],
            robot_position[1],
            self.state.t
        )

        # Setze Pfad für Exit-Bewegung
        robot.set_path([exit_position], target_action=None)

        # Task vom Robot entfernen (wird nach Exit idle)
        robot.clear_task()

        # Erzeuge ROBOT_MOVE Event für Exit
        exit_event = self.event_builder.build_robot_move_event(
            robot=robot,
            time=self.state.t + 1,
        )
        self.event_queue.push(exit_event)

        # Prüfen ob Pickstation sofort Service starten kann
        self._try_start_pickstation_service(pickstation)

    def _find_pickstation_exit_position(self, pickstation_pos, robot_id):
        """
        Findet eine freie Nachbarzelle zur Pickstation zum "Ausparken".

        Priorität: rechts (ins Grid) > oben/unten > links (weiter raus)

        Args:
            pickstation_pos: (x, y) Position der Pickstation
            robot_id: ID des Roboters

        Returns:
            (x, y) freie Position oder None
        """
        x, y = pickstation_pos
        current_time = self.state.t

        # Mögliche Exit-Positionen (Priorität: ins Grid rein)
        candidates = [
            (x + 1, y),  # Rechts (ins Grid)
            (x, y - 1),  # Oben
            (x, y + 1),  # Unten
            (x - 1, y),  # Links (falls Pickstation nicht am Rand)
        ]

        for candidate in candidates:
            # Prüfe ob Position im Grid liegt
            if not (0 <= candidate[0] < self.state.grid.width and
                    0 <= candidate[1] < self.state.grid.depth):
                continue

            # Prüfe ob Position zur Zeit t+1 frei ist
            if self.state.reservation_table.is_free(
                    candidate[0], candidate[1], current_time + 1, exclude_robot=robot_id
            ):
                return candidate

        return None
    
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
        """
        Behandelt Abschluss des Pickstation-Service.

        Workflow:
        1. Service ist abgeschlossen (Bin wurde bearbeitet)
        2. Finde verfügbaren Robot zum Abholen der Bin
        3. Robot fährt zur Pickstation
        4. Robot nimmt Bin mit und bringt sie zurück ins Grid
        """
        task = event.payload.get("task")

        if task is None:
            raise RuntimeError("Cannot handle pickstation completion: event has no task")

        task.mark_pickstation_completed()

        if task.target_bin_id == 102:
            print(f"[TRACE][PS_COMPLETE] t={self.state.t} task={task.request_id} "
                  f"bin={task.target_bin_id}")

        # Finde Pickstation, an der dieser Task war
        pickstation = None
        if hasattr(task, 'assigned_pickstation') and task.assigned_pickstation:
            pickstation = self.state.get_pickstation(task.assigned_pickstation)

        if pickstation is None:
            # Fallback: Suche Pickstation, die diesen Task bearbeitet
            for ps in self.state.pickstations:
                if task in ps.current_tasks:
                    pickstation = ps
                    break

        if pickstation is None:
            raise RuntimeError(
                f"Cannot find pickstation for task {task.request_id}"
            )

        # Service beenden (macht Kapazität frei)
        pickstation.complete_service(task)

        # Task in "wartet auf Abholung" markieren
        self.active_queue.mark_pickstation_task_completed(task)

        # ✅ Finde verfügbaren Robot zum Abholen – jetzt mit PortPrioritizer
        available_robot = self._select_robot_for_pickstation_pickup(
            pickstation=pickstation,
            task=task,
        )

        if available_robot is None:
            # Kein Robot verfügbar → Task bleibt in Warteschlange
            # Wird später beim nächsten schedule_available_robots() versucht
            print(
                f"[INFO] No robot available to pick up task {task.request_id} "
                f"from pickstation {pickstation.station_id}"
            )
            return

        # Reserviere Port VOR dem Losfahren
        success = pickstation.reserve(available_robot.robot_id)
        if not success:
            # Port nicht verfügbar, Task in Warteschlange
            print(
                f"[INFO] Cannot reserve port {pickstation.station_id} "
                f"for robot {available_robot.robot_id} - task {task.request_id} "
                f"stays waiting"
            )
            self.active_queue.add_waiting_task(task)
            return

        # Robot bekommt Task zum Abholen der Bin
        available_robot.assign_task(task)

        # ✅ NEU: Wenn bereits ein Robot physisch auf der Pickstation steht,
        # schicken wir keinen zweiten dorthin.
        for robot in self.state.robots:
            if (
                    robot.robot_id != available_robot.robot_id
                    and robot.get_position() == pickstation.position
            ):
                print(
                    f"[INFO] Cannot send robot {available_robot.robot_id} to "
                    f"pickstation {pickstation.station_id}: currently occupied "
                    f"by robot {robot.robot_id}"
                )
                available_robot.clear_task()
                # Port-Reservierung wieder freigeben
                pickstation.release_reservation()
                # Task bleibt als wartender Task; er wird später erneut versucht
                self.active_queue.add_waiting_task(task)
                return

        self.active_queue.assign_task_to_robot(task, available_robot)

        # Plane Pfad zur Pickstation
        robot_position = available_robot.get_position()
        pickstation_position = pickstation.position

        path = self.event_builder.cost_model.calculate_path(
            from_position=robot_position,
            to_position=pickstation_position,
            robot=available_robot,
            state=self.state,
            current_time=self.state.t,
        )

        if not path:
            # Robot ist bereits an Pickstation (sollte nicht vorkommen)
            print(
                f"[WARNING] Robot {available_robot.robot_id} already at pickstation"
            )
            return

        # Erzeuge ROBOT_MOVE Events zur Pickstation
        # Target-Action: Bin von Pickstation nehmen
        pickup_action = {
            "type": "pickup_from_pickstation",
            "pickstation_id": pickstation.station_id,
            "bin_id": task.target_bin_id,
        }

        path_events = self.event_builder.build_path_events(
            robot=available_robot,
            path=path,
            target_action=pickup_action,
            request=task.request,
            start_time=self.state.t,
            state=self.state,
        )

        if path_events is None:
            # Pfad kann nicht reserviert werden
            print(
                f"[BLOCKED] Cannot reserve path for robot {available_robot.robot_id} "
                f"to pickstation {pickstation.station_id}"
            )
            available_robot.clear_task()
            # Port-Reservierung wieder freigeben
            pickstation.release_reservation()
            self.active_queue.add_waiting_task(task)
            return

        for path_event in path_events:
            self.event_queue.push(path_event)

        # Nächsten wartenden Task aus Pickstation-Queue starten
        self._try_start_pickstation_service(pickstation)

    def _select_robot_for_pickstation_pickup(self, pickstation, task):
        """
        Wählt den besten idle Robot zum Abholen einer Bin von der Pickstation.

        Nutzt PortPrioritizer:
        - Machbarkeit bzgl. Deadline
        - Minimale Port-Leerlaufzeit (früheste Ankunft)
        - Tiebreaker: niedrigere Robot-ID
        """
        candidates = []

        for robot in self.state.robots:
            # Nur wirklich freie Roboter betrachten
            if robot.status != "idle":
                continue
            if robot.current_task is not None:
                continue

            pos = robot.get_position()
            if pos is None:
                continue

            # Roboter, die bereits auf der Pickstation stehen, sind hier nicht sinnvoll
            if pos == pickstation.position:
                continue

            # Deadline aus Request – Fallbacks für ältere Felder
            request = task.request
            deadline = getattr(
                request,
                "deadline",
                getattr(request, "latest_time", self.state.t + 10**9),
            )

            candidates.append(
                RobotCandidate(
                    robot_id=robot.robot_id,
                    position=pos,
                    deadline=deadline,
                    task_id=task.request_id,
                )
            )

        if not candidates:
            return None

        result = self.port_prioritizer.select_robot(
            candidates=candidates,
            port_position=pickstation.position,
            current_time=self.state.t,
        )

        if result is None:
            return None

        return self.state.get_robot(result.selected_robot_id)

    def _find_available_robot_for_pickup(self):
        """
        Findet einen idle Robot, der NICHT auf einer Pickstation steht.

        Returns:
            Robot oder None
        """
        for robot in self.state.robots:
            if robot.status != "idle":
                continue

            if robot.current_task is not None:
                continue

            # Prüfe ob Robot auf Pickstation steht
            robot_pos = robot.get_position()
            if robot_pos is None:
                continue

            on_pickstation = False
            for ps in self.state.pickstations:
                if robot_pos == ps.position:
                    on_pickstation = True
                    break

            if not on_pickstation:
                return robot

        return None

    def _update_robot_position_after_action(self, event):
        """
        Aktualisiert Roboter-Position nach erfolgreicher Aktion.

        NEU:
        Im aktuellen Modell werden alle physischen Bewegungen ausschließlich
        über ROBOT_MOVE-Events und Pfadplanung (ReservationTable) abgebildet.

        Aktionen wie relocate/remove_target/return verändern nur den
        Lagerzustand (Stacks/Bins) und den Taskzustand, nicht die physische
        Roboterposition. Zusätzliche "Teleports" nach einer Aktion führen
        zu Mehrfachbelegung derselben Zelle und stören die Kollisionslogik.

        Deshalb ist diese Methode jetzt bewusst ein No-Op.
        """
        return

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

        # Sicherstellen, dass der Task wirklich vollständig und konsistent ist
        task.require_consistently_completed(self.state)

        completion_time = self.state.t

        # Hauptrequest abschließen (Metrik 3)
        self.metrics.record_full_completion(completion_time, task.request)

        # Gebatchte Requests erhalten denselben Vollständigkeitszeitpunkt
        for batched_request in task.batched_requests:
            self.metrics.record_full_completion(completion_time, batched_request)

        self.active_queue.mark_completed(request)

        # NEU: Jetzt alle Reservierungen des Roboters freigeben
        self.state.reservation_table.release_all(robot.robot_id)

        robot.clear_task()
        # Roboter wird wirklich idle
        robot.set_status("idle")
        # Idle-Roboter-Regel: Port/Pufferzone verlassen
        self._handle_robot_becomes_idle(robot)

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
            # Mit der neuen Robot-Initialisierung sollte das nicht mehr vorkommen.
            # Falls doch, behandeln wir es als Fehler, denn jede Bewegung
            # muss eine definierte Startposition haben.
            raise RuntimeError(
                f"Robot {robot.robot_id} has no position when scheduling next action"
            )

        path = self.event_builder.cost_model.calculate_path(
            from_position=current_position,
            to_position=target_position,
            robot=robot,
            state=self.state,
            current_time=self.state.t,
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
            state=self.state,
        )

        if path_events is None:
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

    """Hier neuer Code"""
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

            action_type = action.get("type")

            # NEU: Zwei-Phasen-Aktionen für physische Bewegungen
            if action_type in ("relocate", "remove_target", "return"):
                # Pickup-Position bestimmen (= from_stack Position)
                pickup_position = self._get_target_position_for_action(action)
                current_position = robot.get_position()

                if current_position is None:
                    raise RuntimeError(
                        f"Robot {robot.robot_id} has no position when scheduling"
                    )

                path = self.event_builder.cost_model.calculate_path(
                    from_position=current_position,
                    to_position=pickup_position,
                    robot=robot,
                    state=self.state,
                    current_time=current_time,
                )

                if not path:
                    # Bereits am Pickup-Ort - direkt Pickup-Event
                    pickup_event = self.event_builder.build_robot_pickup_event(
                        robot=robot,
                        action=action,
                        request=request,
                        time=current_time + 1,
                    )
                    self.event_queue.push(pickup_event)
                    continue

                # Pfad-Events zum Pickup-Ort (OHNE target_action!)
                robot.set_path(path, target_action=None)

                move_time = current_time
                move_cost = self.event_builder.cost_model.config.move_cost_per_grid_step

                for _ in range(len(path)):
                    move_time += move_cost
                    move_event = self.event_builder.build_robot_move_event(
                        robot=robot,
                        time=move_time,
                    )
                    self.event_queue.push(move_event)

                # Nach allen Moves: Pickup-Event (nicht Action-Event!)
                pickup_event = self.event_builder.build_robot_pickup_event(
                    robot=robot,
                    action=action,
                    request=request,
                    time=move_time + 1,
                )
                self.event_queue.push(pickup_event)
                continue

            # Nicht-physische Aktionen (request_complete etc.) - alte Logik
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

    """
    def schedule_available_robots(self, current_time):
        """"""
        Scheduled so viele Requests oder wartende Tasks, wie freie Roboter vorhanden sind.
        """"""
        while True:
            scheduling_result = self.scheduler.try_schedule(self.state, current_time)

            if scheduling_result is None:
                return

            action = scheduling_result["action"]

            if action is None:
                return

            robot = scheduling_result["robot"]
            request = scheduling_result["request"]

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
                # Mit der neuen Robot-Initialisierung sollte das nicht mehr vorkommen.
                # Wenn doch, ist das ein Modelldefekt.
                raise RuntimeError(
                    f"Robot {robot.robot_id} has no position when scheduling new request"
                )

            path = self.event_builder.cost_model.calculate_path(
                from_position=current_position,
                to_position=target_position,
                robot=robot,
                state=self.state,
                current_time=self.state.t,
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
                state=self.state,
            )

            if path_events is None:
                print(
                    f"[BLOCKED] Cannot reserve path for robot {robot.robot_id}, "
                    f"request {request.request_id} stays pending"
                )
                robot.clear_task()
                self.active_queue.pending.appendleft(request)
                continue

            for path_event in path_events:
                self.event_queue.push(path_event)
    """

    def _find_bin_location(self, bin_id):
        """
        Sucht die aktuelle Stack-Position einer Bin.

        Rückgabe:
            (stack, level) oder (None, None), falls Bin in keinem Stack liegt.

        Wird genutzt für:
        - Smart Skip bei blockierten Relocate-Aktionen:
          Wenn die Blocker-Bin nicht mehr auf dem erwarteten Stack liegt,
          wurde sie bereits „aus dem Weg geräumt“.
        """
        if bin_id is None:
            return None, None

        for stack in self.state.grid.all_stacks():
            for level, bin_obj in enumerate(stack.bins):
                if bin_obj.bin_id == bin_id:
                    return stack, level

        return None, None