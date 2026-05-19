from events.event import Event
from events.event_types import EventType


class EventBuilder:
    def __init__(self, cost_model=None, delay_time=1, max_retries=100, config=None):
        self.cost_model = cost_model
        self.delay_time = delay_time
        self.max_retries = max_retries
        self.config = config

    def build_arrival_event(self, request):
        """
        Baut ein ARRIVAL-Event aus einem Request.

        Der RequestGenerator erzeugt weiterhin nur Requests.
        Diese Methode kapselt die Übersetzung Request -> Event.
        """
        return Event(
            time=request.arrival_time,
            event_type=request.event_type,
            payload=request,
            priority=self._resolve_priority(request.event_type),
        )

    def build_events_from_plan(self, plan, request, robot, start_time):
        """
        Legacy: Wandelt einen Strategy-Plan in konkrete Events um.

        Der neue Next-Step-Flow nutzt diese Methode nicht mehr.
        """
        events = []
        current_time = start_time

        for action in plan:
            event = self.build_event_from_action(
                action=action,
                request=request,
                robot=robot,
                time=current_time,
            )
            events.append(event)
            current_time += 1

        return events

    def build_event_from_action(self, action, request, robot, time):
        """
        Baut ein einzelnes Event aus einer Action.

        Wichtig:
        time ist der Zeitpunkt, zu dem die Aktion abgeschlossen ist.
        """
        event_type = self._resolve_event_type(action)

        return Event(
            time=time,
            event_type=event_type,
            payload={
                "request": request,
                "robot": robot,
                "action": action,
            },
            priority=self._resolve_priority(event_type),
        )

    def build_pickstation_complete_event(self, task, time):
        return Event(
            time=time,
            event_type=EventType.PICKSTATION_COMPLETE,
            payload={
                "task": task,
                "request": task.request,
            },
            priority=self._resolve_priority(EventType.PICKSTATION_COMPLETE),
        )

    def build_robot_move_event(self, robot, time):
        """
        Baut ein ROBOT_MOVE Event für einen einzelnen Bewegungsschritt.
        
        Args:
            robot: Robot-Instanz
            time: Zeitpunkt, zu dem die Bewegung abgeschlossen ist
        
        Returns:
            Event
        """
        return Event(
            time=time,
            event_type=EventType.ROBOT_MOVE,
            payload={
                "robot": robot,
            },
            priority=self._resolve_priority(EventType.ROBOT_MOVE),
        )
    
    def build_path_events(self, robot, path, target_action, request, start_time, state=None):
        """
        Baut eine Sequenz von ROBOT_MOVE Events für einen kompletten Pfad.
        
        NEU: Reserviert den Pfad in der ReservationTable.
        
        Args:
            robot: Robot-Instanz
            path: Liste von (x, y) Wegpunkten
            target_action: Aktion, die nach Erreichen des Ziels ausgeführt wird
            request: Request-Objekt
            start_time: Startzeitpunkt
            state: State-Objekt (für ReservationTable)
        
        Returns:
            list[Event]: Sequenz von ROBOT_MOVE + ROBOT_ACTION Events
            oder None bei Reservierungskonflikt
        """
        if not path:
            return []
        
        # NEU: Pfad reservieren
        if state is not None and state.reservation_table is not None:
            success, conflict = state.reservation_table.reserve_path(
                robot_id=robot.robot_id,
                path=path,
                start_time=start_time,
            )
            
            if not success:
                # Reservierung fehlgeschlagen
                print(
                    f"[WARNING] Cannot reserve path for robot {robot.robot_id}: "
                    f"conflict at {conflict.get('position')} at time {conflict.get('time')} "
                    f"(blocked by robot {conflict.get('blocking_robot')})"
                )
                return None
        
        events = []
        
        # Pfad im Roboter speichern
        robot.set_path(path, target_action)
        
        # ROBOT_MOVE Event für jeden Schritt
        current_time = start_time
        for i in range(len(path)):
            current_time += self.config.move_cost_per_grid_step if hasattr(self, 'config') and self.config else 1
            
            move_event = self.build_robot_move_event(
                robot=robot,
                time=current_time,
            )
            events.append(move_event)
        
        # Nach dem letzten Move: ROBOT_ACTION für die eigentliche Aktion
        if target_action is not None:
            action_duration = self.calculate_action_duration(
                action=target_action,
                state=state,
                robot=robot,
            )
            
            action_event = self.build_event_from_action(
                action=target_action,
                request=request,
                robot=robot,
                time=current_time + action_duration,
            )
            events.append(action_event)
        
        return events

    def calculate_action_duration(self, action, state, robot):
        if self.cost_model is None:
            return 1

        return self.cost_model.action_duration(action, state, robot)

    def calculate_pickstation_service_duration(self, batch_count=1):
        """
        Berechnet die Servicezeit an der Pickstation.

        batch_count: Anzahl der Requests, die an dieser Pickstation gemeinsam
                     bedient werden (primärer Request + gebatchte Requests).
                     Die Servicezeit steigt linear mit der Batch-Größe.
        """
        if self.cost_model is None:
            return max(1, batch_count)

        base_duration = self.cost_model.pickstation_service_duration()
        return base_duration * batch_count

    def get_final_robot_position(self, action):
        if self.cost_model is None:
            return None

        return self.cost_model.final_robot_position(action)

    def delay_event(self, event, current_time):
        """
        Verschiebt ein nicht ausführbares Event um delay_time nach hinten.

        Wichtig:
        Das ursprüngliche Event wird nicht mutiert, weil es bereits aus der Queue
        gepoppt und verarbeitet wurde. Stattdessen wird ein neues Event erzeugt.
        """
        next_retry_count = event.retry_count + 1

        if next_retry_count > self.max_retries:
            action = self.get_action_from_event(event)
            raise RuntimeError(
                f"Event exceeded max retries ({self.max_retries}). "
                f"action_type={action.get('type')}, "
                f"bin_id={action.get('bin_id')}, "
                f"time={current_time}"
            )

        return Event(
            time=current_time + self.delay_time,
            event_type=event.event_type,
            payload=event.payload,
            retry_count=next_retry_count,
            priority=event.priority,
        )

    def get_action_from_event(self, event):
        """
        Extrahiert die Action aus einem Action-Event.
        """
        if isinstance(event.payload, dict) and "action" in event.payload:
            return event.payload["action"]

        if isinstance(event.payload, dict):
            return event.payload

        raise ValueError(f"Event has no action payload: {event.payload}")

    def _resolve_event_type(self, action):
        if action.get("type") == "request_complete":
            return EventType.REQUEST_COMPLETE

        return EventType.ROBOT_ACTION

    # Zuerst werden REQUEST_COMPLETE-Events priorisiert,
    # damit Roboter bei gleicher ZE zuerst frei gemacht werden.
    def _resolve_priority(self, event_type):
        if event_type == EventType.REQUEST_COMPLETE:
            return 0

        if event_type == EventType.PICKSTATION_COMPLETE:
            return 1

        if event_type == EventType.ARRIVAL:
            return 2

        if event_type == EventType.ROBOT_ACTION:
            return 3
        
        # NEU: ROBOT_MOVE hat niedrigere Priorität als Actions
        if event_type == EventType.ROBOT_MOVE:
            return 4

        return 99