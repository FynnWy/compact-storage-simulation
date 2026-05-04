from events.event import Event
from events.event_types import EventType


class EventBuilder:
    def __init__(self, action_duration=1, delay_time=1, max_retries=100):
        self.action_duration = action_duration
        self.delay_time = delay_time
        self.max_retries = max_retries

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
        Wandelt einen Strategy-Plan in konkrete Events um.
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
            current_time += self.action_duration

        return events

    def build_event_from_action(self, action, request, robot, time):
        """
        Baut ein einzelnes Event aus einer Plan-Action.
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

    # Zuerst werden alle REQUEST_COMPLETE-Events priorisiert,
    # damit Roboter bei gleicher ZE zuerst frei gemacht werden.
    def _resolve_priority(self, event_type):
        if event_type == EventType.REQUEST_COMPLETE:
            return 0

        if event_type == EventType.ARRIVAL:
            return 1

        if event_type == EventType.ROBOT_ACTION:
            return 2

        return 99