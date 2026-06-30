# tests/test_event_handler_smart_skip.py
"""
Gezielte Tests für die Smart-Skip- und Replan-Logik im EventHandler.

Testet:
- relocate-Smart-Skip: Blocker-Bin wurde bereits verschoben → Aktion wird übersprungen.
- Retry-Limit: Nach max_action_retries_before_replan Retries wird der Task requeued,
  anstatt endlos delay_event zu erzeugen.
"""

import types

from events.event import Event
from events.event_types import EventType
from simulation.event_handler import EventHandler
from state.storage_grid import StorageGrid
from state.bin import Bin


class DummyQueue:
    """Einfache Queue mit push()-API für EventQueue-Stub."""
    def __init__(self):
        self.items = []

    def push(self, event):
        self.items.append(event)

    def is_empty(self):
        return not self.items

    def pop(self):
        return self.items.pop(0)


class DummyActiveQueue:
    """Nur die Methoden, die wir im Test brauchen."""
    def __init__(self):
        self.waiting_tasks = []

    def add(self, request):
        pass

    def add_waiting_task(self, task):
        self.waiting_tasks.append(task)


class DummyConstraintManager:
    def __init__(self, can_execute=False, reason="blocked"):
        self.can_execute = can_execute
        self.reason = reason
        self.calls = []

    def can_execute_with_reason(self, action, state):
        self.calls.append((action, state))
        return self.can_execute, self.reason


class DummyEventBuilder:
    """
    Liefert das Action-Objekt zurück und erlaubt uns,
    delay_event-Aufrufe mitzuprotokollieren.
    """
    def __init__(self):
        self.delayed_events = []

    def get_action_from_event(self, event):
        return event.payload["action"]

    def delay_event(self, event, current_time):
        # Für diese Tests reicht es, das Event einfach zu protokollieren
        self.delayed_events.append((event, current_time))
        # In der echten Implementierung würde hier ein neues Event erzeugt;
        # für den Test ist das nicht notwendig.
        return event


class DummyRobot:
    def __init__(self, robot_id=0, task=None):
        self.robot_id = robot_id
        self.current_task = task
        self.status = "busy"

    def get_position(self):
        return (0, 0)

    def set_position(self, pos):
        pass

    def clear_task(self):
        self.current_task = None
        self.status = "idle"


class DummyTask:
    def __init__(self, request_id=1):
        self.request_id = request_id


class DummyState:
    def __init__(self):
        # Minimaler Grid mit einem Stack, in dem eine Bin liegt
        self.grid = StorageGrid(width=3, depth=3)
        # Erzeuge einen Stack manuell und lege eine Bin hinein
        stack = next(iter(self.grid.all_stacks()))
        self.stack = stack
        self.t = 0

        # Eine einzelne Bin auf diesem Stack
        self.bin = Bin(bin_id=35, stack_id=stack.stack_id, level=0, status="in_storage")
        stack.bins.append(self.bin)

        # get_bin_by_id-API, falls irgendwo gebraucht
        self.bins = [self.bin]

        # Platzhalter für ReservationTable (nicht relevant für diese Tests)
        self.reservation_table = types.SimpleNamespace(
            reserve=lambda robot_id, x, y, t: True
        )

        # Zusatzattribute für Kompatibilität mit EventHandler / IdleParkingManager
        # Nutzung als Mengen, daher als set() anlegen
        self.port_positions = set()   # keine Ports nötig für Smart-Skip-Tests
        self.buffer_zone = set()      # leere Pufferzone
        self.pickstations = []        # keine Pickstations im Minimal-Setup
        self.robots = []              # leere Roboterliste

    def get_bin_by_id(self, bin_id):
        for b in self.bins:
            if b.bin_id == bin_id:
                return b
        return None


class DummyMetrics:
    def __getattr__(self, item):
        # Alle Aufrufe ins Leere laufen lassen
        def _noop(*args, **kwargs):
            return None
        return _noop


class DummyScheduler:
    pass


class DummyExecutor:
    def execute(self, event, state):
        pass


class DummyRequestHandler:
    pass


class TestEventHandlerSmartSkip:
    def test_relocate_smart_skip_when_bin_already_moved(self):
        """
        Wenn eine relocate-Action blockiert und die Bin nicht mehr auf from_stack,
        sondern auf einem anderen Stack liegt, muss der EventHandler:

        - KEIN delay_event erzeugen
        - _schedule_next_action_for_same_task() aufrufen (Smart-Skip)
        """
        # --- Setup State ---
        state = DummyState()

        # from_stack_id entspricht NICHT dem tatsächlichen Stack der Bin:
        action = {
            "type": "relocate",
            "bin_id": 35,
            "from_stack": "S_99_99",  # absichtlich falsch
            "to_stack": "S_0_1",
        }

        # --- Stubs / Dummies ---
        event_queue = DummyQueue()
        active_queue = DummyActiveQueue()
        constraint_manager = DummyConstraintManager(can_execute=False, reason="blocked")
        event_builder = DummyEventBuilder()
        metrics = DummyMetrics()
        scheduler = DummyScheduler()
        executor = DummyExecutor()
        request_handler = DummyRequestHandler()

        # Dummy-Request & -Robot
        task = DummyTask(request_id=123)
        robot = DummyRobot(robot_id=0, task=task)
        request = types.SimpleNamespace(request_id=123)

        # Event mit retry_count=0
        event = Event(
            time=0,
            event_type=EventType.ROBOT_ACTION,
            payload={"robot": robot, "request": request, "action": action},
            retry_count=0,
        )

        # Subklasse von EventHandler, um _schedule_next_action_for_same_task mitzuprotokollieren
        class TestableEventHandler(EventHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.schedule_called = False

            def _schedule_next_action_for_same_task(self, event):
                self.schedule_called = True

        handler = TestableEventHandler(
            state=state,
            active_queue=active_queue,
            event_queue=event_queue,
            request_handler=request_handler,
            metrics=metrics,
            constraint_manager=constraint_manager,
            scheduler=scheduler,
            executor=executor,
            event_builder=event_builder,
        )

        # Sicherstellen, dass unser max_action_retries_before_replan nicht stört
        handler.max_action_retries_before_replan = 20

        # --- Act ---
        handler._handle_robot_action(event)

        # --- Assert ---
        # 1) Smart-Skip: Es wurde NICHT verzögert
        assert event_builder.delayed_events == [], "delay_event should not be called for smart-skip case"

        # 2) Stattdessen wurde direkt die Planung der nächsten Aktion angestoßen
        assert handler.schedule_called is True, "_schedule_next_action_for_same_task should be called for smart-skip"

    def test_replan_after_max_retries(self):
        """
        Wenn eine Aktion nach max_action_retries_before_replan mal immer noch nicht
        ausführbar ist, soll der Task in die Waiting-Queue verschoben werden und
        kein weiteres delay_event erzeugt werden.
        """
        state = DummyState()

        action = {
            "type": "relocate",
            "bin_id": 35,
            "from_stack": state.stack.stack_id,
            "to_stack": "S_0_1",
        }

        event_queue = DummyQueue()
        active_queue = DummyActiveQueue()
        constraint_manager = DummyConstraintManager(can_execute=False, reason="blocked")
        event_builder = DummyEventBuilder()
        metrics = DummyMetrics()
        scheduler = DummyScheduler()
        executor = DummyExecutor()
        request_handler = DummyRequestHandler()

        task = DummyTask(request_id=456)
        robot = DummyRobot(robot_id=0, task=task)
        request = types.SimpleNamespace(request_id=456)

        # retry_count genau auf dem Limit
        dummy_retry_limit = 5
        event = Event(
            time=0,
            event_type=EventType.ROBOT_ACTION,
            payload={"robot": robot, "request": request, "action": action},
            retry_count=dummy_retry_limit,
        )

        class TestableEventHandler(EventHandler):
            pass

        handler = TestableEventHandler(
            state=state,
            active_queue=active_queue,
            event_queue=event_queue,
            request_handler=request_handler,
            metrics=metrics,
            constraint_manager=constraint_manager,
            scheduler=scheduler,
            executor=executor,
            event_builder=event_builder,
        )

        handler.max_action_retries_before_replan = dummy_retry_limit

        # --- Act ---
        handler._handle_robot_action(event)

        # --- Assert ---
        # 1) Task wurde in Waiting-Queue geschoben
        assert active_queue.waiting_tasks == [task], "Task should be requeued to waiting_tasks after too many retries"

        # 2) Robot hat keinen aktuellen Task mehr
        assert robot.current_task is None, "Robot.current_task should be cleared after replan"

        # 3) Für diesen Fall wurde KEIN neues delay_event erzeugt
        assert event_builder.delayed_events == [], "No delay_event should be created when we replan the task"

        # 4) EventQueue bleibt leer (kein weiteres ROBOT_ACTION-Event geplant)
        assert event_queue.items == [], "EventQueue should remain unchanged when replanning"