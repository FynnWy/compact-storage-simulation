# tests/audit_harness.py
"""
Audit-Harness für die Simulation Consistency & Stress Audit (Phase 2).

WICHTIG: Dieses Modul verändert KEIN Produktionsverhalten.
Es umschließt den EventHandler mit reinen Beobachtern (Wrapper, die die
Originalmethode aufrufen und nur lesen) und prüft nach jedem Simulationsschritt
Invarianten auf dem State.

Kein `test_`-Präfix im Dateinamen: Das Modul enthält keine Tests, sondern
Werkzeuge. Es wird von Diagnose-Skripten und von `test_audit_invariants.py`
importiert.
"""

import io
import contextlib
import re
from collections import Counter, defaultdict


# ======================================================================
# Ergebnis-Container
# ======================================================================

class AuditResult:
    def __init__(self, config_label, params):
        self.config_label = config_label
        self.params = params

        # Verletzungen: Liste von (t, kategorie, beschreibung)
        self.violations = []
        self.violation_kinds = Counter()

        # Physische Aktionszähler
        self.physically_invalid_pickups = 0
        self.physically_invalid_drops = 0
        self.robot_position_collisions = 0
        self.invalid_moves = 0

        # Stale-/Duplikat-Events
        self.stale_move_events = 0
        self.stale_pickup_events = 0
        self.stale_drop_events = 0
        self.stale_events_with_state_change = 0

        # Retry / Recovery
        self.max_retry_count = 0
        self.replans = 0
        self.requeues = 0
        self.deadlock_detections = 0
        self.deadlock_recoveries = 0
        self.evades = 0
        self.manhattan_fallbacks = 0
        self.pickup_pos_replans = 0
        self.pickup_return_replans = 0
        self.drop_pos_replans = 0

        # Fortschritt
        self.max_no_progress_window = 0
        self.progress_events = 0
        self.longest_task_wait = 0
        self.longest_robot_busy_without_progress = 0
        self.longest_ps_service_wait = 0
        self.longest_return_wait = 0

        # Pickstation
        self.ps_idle_with_queue = 0
        self.ps_max_queue = 0
        self.ps_stats = {}

        # Dauerhaft blockierte Tasks (stale Restore-Einträge)
        self.stale_restore_tasks = set()
        self.stuck_task_max_duration = 0
        self._stale_restore_since = {}

        # Lauf
        self.t_end = 0
        self.steps = 0
        self.error = None
        self.summary = {}
        self.wall_seconds = 0.0

    def add(self, t, kind, detail):
        self.violation_kinds[kind] += 1
        if len(self.violations) < 40:
            self.violations.append((t, kind, detail))

    @property
    def ok(self):
        return not self.violations and self.error is None

    def counters(self):
        return {
            "physically_invalid_pickups": self.physically_invalid_pickups,
            "physically_invalid_drops": self.physically_invalid_drops,
            "robot_position_collisions": self.robot_position_collisions,
            "invalid_moves": self.invalid_moves,
            "stale_move_events": self.stale_move_events,
            "stale_pickup_events": self.stale_pickup_events,
            "stale_drop_events": self.stale_drop_events,
            "stale_events_with_state_change": self.stale_events_with_state_change,
            "max_retry_count": self.max_retry_count,
            "replans": self.replans,
            "requeues": self.requeues,
            "deadlock_detections": self.deadlock_detections,
            "deadlock_recoveries": self.deadlock_recoveries,
            "evades": self.evades,
            "manhattan_fallbacks": self.manhattan_fallbacks,
            "pickup_pos_replans": self.pickup_pos_replans,
            "pickup_return_replans": self.pickup_return_replans,
            "drop_pos_replans": self.drop_pos_replans,
            "max_no_progress_window": self.max_no_progress_window,
            "longest_task_wait": self.longest_task_wait,
            "longest_robot_busy_without_progress": self.longest_robot_busy_without_progress,
            "longest_ps_service_wait": self.longest_ps_service_wait,
            "longest_return_wait": self.longest_return_wait,
            "ps_idle_with_queue": self.ps_idle_with_queue,
            "ps_max_queue": self.ps_max_queue,
            "stale_restore_tasks": len(self.stale_restore_tasks),
            "stuck_task_max_duration": self.stuck_task_max_duration,
        }


# ======================================================================
# Hilfsfunktionen
# ======================================================================

def _resolve_stack_position(stack_id):
    if stack_id is None:
        return None
    if isinstance(stack_id, tuple):
        return stack_id
    if isinstance(stack_id, str) and stack_id.startswith("S_"):
        parts = stack_id.split("_")
        if len(parts) == 3:
            try:
                return int(parts[1]), int(parts[2])
            except ValueError:
                return stack_id
    return stack_id


def _all_known_tasks(engine):
    tasks = {}
    for task in engine.active_queue.waiting_tasks:
        tasks[id(task)] = task
    for task in engine.active_queue.pickstation_tasks.values():
        tasks[id(task)] = task
    for robot in engine.state.robots:
        if robot.current_task is not None:
            tasks[id(robot.current_task)] = robot.current_task
    for ps in engine.state.pickstations:
        for task in ps.current_tasks:
            tasks[id(task)] = task
        for task, _ in ps.queue:
            tasks[id(task)] = task
    return list(tasks.values())


# ======================================================================
# Invarianten-Prüfungen (rein lesend)
# ======================================================================

def check_bin_invariants(engine, result):
    """
    Jede Bin ist zu jedem Zeitpunkt in genau EINEM der drei Zustände:
    in genau einem Stack / an genau einer Pickstation / in Transit bei
    genau einem Roboter.
    """
    t = engine.state.t

    stack_locations = defaultdict(list)
    for stack in engine.state.grid.all_stacks():
        for bin_obj in stack.bins:
            stack_locations[bin_obj.bin_id].append(stack.stack_id)

    carriers = defaultdict(list)
    for robot in engine.state.robots:
        carried = getattr(robot, "carried_bin_id", None)
        if carried is not None:
            carriers[carried].append(robot.robot_id)

    known_ids = set()
    for bin_obj in engine.state.bins:
        bin_id = bin_obj.bin_id
        known_ids.add(bin_id)

        in_stacks = stack_locations.get(bin_id, [])
        in_transit = bool(getattr(bin_obj, "in_transit", False))
        at_ps = bin_obj.get_status() == "at_pickstation"
        carried_by = carriers.get(bin_id, [])

        # (a) niemals in zwei Stacks
        if len(in_stacks) > 1:
            result.add(t, "BIN_IN_TWO_STACKS",
                       f"bin {bin_id} in {in_stacks}")

        # (b) Stack + Transit gleichzeitig
        if in_stacks and in_transit:
            result.add(t, "BIN_STACK_AND_TRANSIT",
                       f"bin {bin_id} in {in_stacks} und in_transit")

        # (c) Pickstation + Stack
        if at_ps and in_stacks:
            result.add(t, "BIN_PS_AND_STACK",
                       f"bin {bin_id} at_pickstation und in {in_stacks}")

        # (d) nirgendwo vorhanden
        if not in_stacks and not in_transit and not at_ps:
            result.add(t, "BIN_LOST",
                       f"bin {bin_id} weder Stack noch PS noch Transit "
                       f"(status={bin_obj.get_status()})")

        # (e) von mehreren Robotern getragen
        if len(carried_by) > 1:
            result.add(t, "BIN_MULTI_CARRIER",
                       f"bin {bin_id} getragen von {carried_by}")

        # (f) Trage-Verknüpfung muss zum Transit-Zustand passen
        if carried_by and not in_transit:
            result.add(t, "CARRIED_BUT_NOT_IN_TRANSIT",
                       f"bin {bin_id} carried_by={carried_by} aber "
                       f"in_transit=False (status={bin_obj.get_status()})")

        # (g) Bin-Metadaten müssen zur physischen Lage passen
        if len(in_stacks) == 1:
            expected = _resolve_stack_position(in_stacks[0])
            if bin_obj.get_stack() != expected:
                result.add(t, "BIN_METADATA_MISMATCH",
                           f"bin {bin_id} liegt in {expected}, "
                           f"Metadaten sagen {bin_obj.get_stack()}")

    # (h) Bins in Stacks, die es im State gar nicht gibt
    for bin_id in stack_locations:
        if bin_id not in known_ids:
            result.add(t, "BIN_UNKNOWN_IN_STACK", f"bin {bin_id}")


def check_robot_invariants(engine, result):
    t = engine.state.t

    for robot in engine.state.robots:
        carried = getattr(robot, "carried_bin_id", None)
        if carried is None:
            continue

        bin_obj = engine.state.get_bin_by_id(carried)
        if bin_obj is None:
            result.add(t, "CARRIED_BIN_MISSING",
                       f"robot {robot.robot_id} trägt unbekannte bin {carried}")
            continue

        if not getattr(bin_obj, "in_transit", False):
            result.add(t, "CARRIED_BIN_NOT_IN_TRANSIT",
                       f"robot {robot.robot_id} bin {carried} "
                       f"in_transit=False")

        for stack in engine.state.grid.all_stacks():
            if bin_obj in stack.bins:
                result.add(t, "CARRIED_BIN_ALSO_IN_STACK",
                           f"robot {robot.robot_id} bin {carried} "
                           f"in {stack.stack_id}")
                break

    # Verwaiste Transit-Bins: in_transit, aber kein Träger und nicht an PS
    carried_ids = {
        getattr(r, "carried_bin_id", None) for r in engine.state.robots
    }
    for bin_obj in engine.state.bins:
        if not getattr(bin_obj, "in_transit", False):
            continue
        if bin_obj.bin_id in carried_ids:
            continue
        if bin_obj.get_status() == "at_pickstation":
            # Fachlich gültiger Übergang: Bin liegt am Port und wird dort
            # als in_transit geführt, bis ein Roboter sie abholt.
            continue
        result.add(t, "ORPHANED_TRANSIT_BIN",
                   f"bin {bin_obj.bin_id} in_transit ohne Träger "
                   f"(status={bin_obj.get_status()})")

    # Position-Kollisionen
    positions = defaultdict(list)
    for robot in engine.state.robots:
        pos = robot.get_position()
        if pos is not None:
            positions[pos].append(robot.robot_id)
    for pos, ids in positions.items():
        if len(ids) > 1:
            result.robot_position_collisions += 1
            result.add(t, "ROBOT_POSITION_COLLISION", f"{pos}: {ids}")

    # Pfad-Konsistenz
    for robot in engine.state.robots:
        if robot.path_index > len(robot.planned_path):
            result.add(t, "PATH_INDEX_OUT_OF_RANGE",
                       f"robot {robot.robot_id} index={robot.path_index} "
                       f"len={len(robot.planned_path)}")


def check_task_invariants(engine, result):
    t = engine.state.t
    queue = engine.active_queue

    waiting_ids = [task.request_id for task in queue.waiting_tasks]
    assigned_ids = set(queue.assigned.keys())

    overlap = set(waiting_ids) & assigned_ids
    if overlap:
        result.add(t, "TASK_WAITING_AND_ASSIGNED", f"{sorted(overlap)}")

    if len(waiting_ids) != len(set(waiting_ids)):
        dupes = [x for x, c in Counter(waiting_ids).items() if c > 1]
        result.add(t, "TASK_DUPLICATE_IN_WAITING", f"{dupes}")

    # Ein Task nicht bei mehreren Robotern
    per_task = defaultdict(list)
    for robot in engine.state.robots:
        if robot.current_task is not None:
            per_task[robot.current_task.request_id].append(robot.robot_id)
    for request_id, robot_ids in per_task.items():
        if len(robot_ids) > 1:
            result.add(t, "TASK_MULTI_ROBOT",
                       f"task {request_id} bei {robot_ids}")

    # Abgeschlossener Task darf nicht erneut schedulbar sein
    for task in queue.waiting_tasks:
        if getattr(task, "target_returned", False):
            result.add(t, "COMPLETED_TASK_STILL_WAITING",
                       f"task {task.request_id}")
        if getattr(task, "phase", None) == "complete":
            result.add(t, "COMPLETE_PHASE_TASK_WAITING",
                       f"task {task.request_id}")

    # temp_storage: nur offene Blocker-Restores
    for task in _all_known_tasks(engine):
        ids = [reloc["bin_id"] for reloc in task.temp_storage]
        if len(ids) != len(set(ids)):
            result.add(t, "TEMP_STORAGE_DUPLICATE",
                       f"task {task.request_id}: {ids}")

        for reloc in task.temp_storage:
            bin_obj = engine.state.get_bin_by_id(reloc["bin_id"])
            if bin_obj is None:
                result.add(t, "TEMP_STORAGE_UNKNOWN_BIN",
                           f"task {task.request_id} bin {reloc['bin_id']}")
                continue
            if getattr(bin_obj, "in_transit", False):
                continue
            buffer_pos = _resolve_stack_position(reloc["buffer_stack"])
            if bin_obj.get_stack() != buffer_pos:
                result.add(t, "TEMP_STORAGE_BIN_NOT_IN_BUFFER",
                           f"task {task.request_id} bin {reloc['bin_id']} "
                           f"@{bin_obj.get_stack()} statt {buffer_pos}")
                key = (task.request_id, reloc["bin_id"])
                since = result._stale_restore_since.setdefault(key, t)
                duration = t - since
                if duration > 50:
                    result.stale_restore_tasks.add(task.request_id)
                result.stuck_task_max_duration = max(
                    result.stuck_task_max_duration, duration
                )

    # Blocker-Ownership konsistent: jede geownte Bin gehört zu temp_storage
    ownership = getattr(queue, "_blocker_ownership", {})
    for bin_id, owning_task in ownership.items():
        known = any(
            reloc["bin_id"] == bin_id for reloc in owning_task.temp_storage
        )
        if not known:
            result.add(t, "BLOCKER_OWNERSHIP_ORPHAN",
                       f"bin {bin_id} geowned von task "
                       f"{owning_task.request_id}, nicht in temp_storage")

    # Batching: ein Request darf nicht doppelt gebatcht sein
    for task in _all_known_tasks(engine):
        batched = [r.request_id for r in task.batched_requests]
        if len(batched) != len(set(batched)):
            result.add(t, "BATCH_DUPLICATE",
                       f"task {task.request_id}: {batched}")
        if task.request_id in batched:
            result.add(t, "BATCH_CONTAINS_SELF", f"task {task.request_id}")


def check_pickstation_invariants(engine, result):
    t = engine.state.t

    serving_bins = []
    for ps in engine.state.pickstations:
        # Capacity
        if len(ps.current_tasks) > ps.capacity:
            result.add(t, "PS_CAPACITY_EXCEEDED",
                       f"{ps.station_id}: {len(ps.current_tasks)}/{ps.capacity}")
        if ps.available_slots < 0:
            result.add(t, "PS_NEGATIVE_SLOTS",
                       f"{ps.station_id}: {ps.available_slots}")
        if ps.available_slots + len(ps.current_tasks) != ps.capacity:
            result.add(t, "PS_SLOT_ACCOUNTING",
                       f"{ps.station_id}: slots={ps.available_slots} "
                       f"serving={len(ps.current_tasks)} cap={ps.capacity}")

        # Queue-Konsistenz: kein Task gleichzeitig in Queue und in Service
        queued = [task for task, _ in ps.queue]
        for task in queued:
            if task in ps.current_tasks:
                result.add(t, "PS_TASK_QUEUED_AND_SERVING",
                           f"{ps.station_id} task {task.request_id}")
        queued_ids = [task.request_id for task in queued]
        if len(queued_ids) != len(set(queued_ids)):
            result.add(t, "PS_QUEUE_DUPLICATE",
                       f"{ps.station_id}: {queued_ids}")

        serving_bins.extend(task.target_bin_id for task in ps.current_tasks)

        # Reservation / Anwesenheit
        if ps.robot_on_port is not None:
            robot = next(
                (r for r in engine.state.robots if r.robot_id == ps.robot_on_port),
                None,
            )
            if robot is None:
                result.add(t, "PS_ON_PORT_UNKNOWN_ROBOT",
                           f"{ps.station_id}: robot {ps.robot_on_port}")
            elif robot.get_position() != ps.position:
                result.add(t, "PS_ON_PORT_POSITION_MISMATCH",
                           f"{ps.station_id}: robot {ps.robot_on_port} "
                           f"@{robot.get_position()} statt {ps.position}")
            if ps.reserved_for_robot not in (None, ps.robot_on_port):
                result.add(t, "PS_RESERVED_FOR_OTHER_WHILE_OCCUPIED",
                           f"{ps.station_id}: reserved={ps.reserved_for_robot} "
                           f"on_port={ps.robot_on_port}")

        # Zwei Roboter dürfen nie gleichzeitig auf derselben Port-Zelle stehen
        on_cell = [
            r.robot_id for r in engine.state.robots
            if r.get_position() == ps.position
        ]
        if len(on_cell) > 1:
            result.add(t, "PS_MULTIPLE_ROBOTS_ON_PORT",
                       f"{ps.station_id}: {on_cell}")
        if len(on_cell) == 1 and ps.robot_on_port not in (None, on_cell[0]):
            result.add(t, "PS_ON_PORT_BOOKKEEPING",
                       f"{ps.station_id}: physisch {on_cell[0]}, "
                       f"gebucht {ps.robot_on_port}")

        # Statistik für den Report
        stats = result.ps_stats.setdefault(ps.station_id, {
            "idle_with_queue": 0, "max_queue": 0, "occupied_steps": 0,
            "reserved_without_presence": 0, "serviced_tasks": 0,
        })
        if ps.is_idle() and ps.queue_length() > 0:
            stats["idle_with_queue"] += 1
            result.ps_idle_with_queue += 1
        stats["max_queue"] = max(stats["max_queue"], ps.queue_length())
        result.ps_max_queue = max(result.ps_max_queue, ps.queue_length())
        if ps.robot_on_port is not None:
            stats["occupied_steps"] += 1
        if ps.reserved_for_robot is not None and ps.robot_on_port is None:
            stats["reserved_without_presence"] += 1

    # Kein Bin darf an zwei Stationen gleichzeitig bedient werden
    if len(serving_bins) != len(set(serving_bins)):
        dupes = [x for x, c in Counter(serving_bins).items() if c > 1]
        result.add(t, "PS_BIN_SERVED_TWICE", f"{dupes}")

    # Task darf nicht an zwei Stationen gleichzeitig in der Queue stehen
    all_queued = []
    for ps in engine.state.pickstations:
        all_queued.extend(task.request_id for task, _ in ps.queue)
        all_queued.extend(task.request_id for task in ps.current_tasks)
    if len(all_queued) != len(set(all_queued)):
        dupes = [x for x, c in Counter(all_queued).items() if c > 1]
        result.add(t, "PS_TASK_AT_TWO_STATIONS", f"{dupes}")


def check_reservation_invariants(engine, result):
    """Verwaiste Port-Reservierungen und Wait-Graph-Plausibilität."""
    t = engine.state.t

    for ps in engine.state.pickstations:
        holder_id = ps.reserved_for_robot
        if holder_id is None or ps.robot_on_port is not None:
            continue
        holder = next(
            (r for r in engine.state.robots if r.robot_id == holder_id), None
        )
        if holder is None:
            result.add(t, "PORT_RESERVED_BY_UNKNOWN_ROBOT",
                       f"{ps.station_id}: robot {holder_id}")
            continue
        if holder.get_position() == ps.position:
            continue
        remaining = holder.planned_path[holder.path_index:]
        if ps.position not in remaining:
            # Nicht sofort als Verletzung werten: kann für einen Zeitschritt
            # legitim sein (zwischen Replan und neuem Pfad). Wir zählen die
            # Dauer separat und melden nur dauerhafte Fälle.
            key = (ps.station_id, holder_id)
            engine_state = result.ps_stats.setdefault("_stale_res", {})
            engine_state[key] = engine_state.get(key, 0) + 1
            if engine_state[key] > 50:
                result.add(t, "PORT_RESERVATION_ORPHANED",
                           f"{ps.station_id} von robot {holder_id} seit "
                           f"{engine_state[key]} Schritten gehalten, "
                           f"Roboter @{holder.get_position()}, "
                           f"Restpfad {remaining[:4]}")
                engine_state[key] = 0


def check_wait_graph(engine, result):
    """Prüft, ob jede Kante eines erkannten Zyklus real ist."""
    tm = getattr(engine.state, "traffic_manager", None)
    if tm is None:
        return
    detector = tm.deadlock_detector
    cycle = detector.detect_cycle()
    if not cycle:
        return

    t = engine.state.t
    by_id = {r.robot_id: r for r in engine.state.robots}
    for robot_id in cycle:
        info = detector._wait_graph.get(robot_id)
        if info is None:
            continue
        waiting_robot = by_id.get(robot_id)
        blocker = by_id.get(info["waiting_for"])
        if waiting_robot is None or blocker is None:
            continue
        next_cell = waiting_robot.get_next_waypoint()
        blocks_cell = blocker.get_position() == next_cell
        holds_port = any(
            ps.reserved_for_robot == blocker.robot_id and ps.position == next_cell
            for ps in engine.state.pickstations
        )
        if not blocks_cell and not holds_port:
            result.add(t, "PHANTOM_WAIT_EDGE",
                       f"{robot_id}->{info['waiting_for']}: "
                       f"next={next_cell}, blocker@{blocker.get_position()}")


# ======================================================================
# Fortschrittsmessung
# ======================================================================

def progress_counter(engine):
    """
    Kumulierte fachliche Fortschrittsereignisse (monoton steigend).

    Zählt pro Task: Target an PS, Service fertig, Target zurückgelagert.
    Abgeschlossene Tasks verschwinden aus den Containern; ihr Beitrag wird
    über den Completion-Zähler bewahrt. Zusätzlich zählen wir restaurierte
    Blocker über die Gesamtzahl je Task.
    """
    live = 0
    for task in _all_known_tasks(engine):
        live += 1 if getattr(task, "target_at_pickstation", False) else 0
        live += 1 if getattr(task, "pickstation_completed", False) else 0
        live += 1 if getattr(task, "target_returned", False) else 0

    completed = engine.metrics.summary().get("requests_completed", 0) or 0
    return completed * 4 + live


# ======================================================================
# Instrumentierung (reine Beobachter)
# ======================================================================

_LOG_PATTERNS = {
    "replans": re.compile(r"\[REPLAN\]"),
    "requeues": re.compile(r"\[REQUEUE\]|\[DEADLOCK\]\[REQUEUE\]"),
    "deadlock_detections": re.compile(r"\[DEADLOCK\] Detected cycle"),
    "deadlock_recoveries": re.compile(r"\[DEADLOCK\] Resolved"),
    "evades": re.compile(r"evades to break deadlock"),
    "manhattan_fallbacks": re.compile(r"TrafficManager failed"),
    "pickup_pos_replans": re.compile(r"\[REPLAN\]\[PICKUP_POS\]"),
    "pickup_return_replans": re.compile(r"\[REPLAN\]\[PICKUP_RETURN\]"),
    "drop_pos_replans": re.compile(r"\[REPLAN\]\[DROP_POS\]"),
    "stale_pickup_events": re.compile(r"\[STALE\]\[PICKUP\]"),
    "stale_drop_events": re.compile(r"\[STALE\]\[DROP\]"),
}


def _install_observers(engine, result):
    """
    Umschließt Pickup/Drop/Move mit reinen Beobachtern.
    Das Produktionsverhalten bleibt identisch: Die Originalmethode wird
    unverändert aufgerufen, es wird nur davor/danach gelesen.
    """
    handler = engine.event_handler
    orig_pickup = handler._handle_robot_pickup
    orig_drop = handler._handle_robot_drop
    orig_move = handler._handle_robot_move

    def _snapshot():
        heights = {s.stack_id: s.height() for s in engine.state.grid.all_stacks()}
        statuses = {
            b.bin_id: (b.get_status(), getattr(b, "in_transit", False))
            for b in engine.state.bins
        }
        return heights, statuses

    def _changed(before):
        heights, statuses = before
        for s in engine.state.grid.all_stacks():
            if s.height() != heights.get(s.stack_id):
                return True
        for b in engine.state.bins:
            if (b.get_status(), getattr(b, "in_transit", False)) != statuses.get(b.bin_id):
                return True
        return False

    def observed_pickup(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action") or {}
        result.max_retry_count = max(result.max_retry_count, event.retry_count)
        before = _snapshot()
        pos_before = robot.get_position() if robot else None
        assigned_before = getattr(
            getattr(robot, "current_task", None), "assigned_pickstation", None
        )
        orig_pickup(event)
        if robot is not None and _changed(before):
            from_stack = action.get("from_stack")
            if from_stack is not None:
                expected = _resolve_stack_position(from_stack)
                if expected is not None and pos_before != expected:
                    result.physically_invalid_pickups += 1
                    result.add(engine.state.t, "INVALID_PICKUP_POSITION",
                               f"robot {robot.robot_id} @{pos_before} "
                               f"pickup from {expected}")
            else:
                # Pickup von der Pickstation: muss an der ZUGEORDNETEN
                # Station erfolgen (Phase 2B, MP-8).
                station = engine.state.find_pickstation_at(pos_before)
                assigned = assigned_before
                if station is None:
                    result.physically_invalid_pickups += 1
                    result.add(engine.state.t, "INVALID_PICKUP_FROM_PS",
                               f"robot {robot.robot_id} @{pos_before} "
                               f"nicht auf Port")
                elif assigned and station.station_id != assigned:
                    result.physically_invalid_pickups += 1
                    result.add(engine.state.t, "CROSS_STATION_PICKUP",
                               f"robot {robot.robot_id} @{station.station_id}, "
                               f"zugeordnet {assigned}")

    def observed_drop(event):
        robot = event.payload.get("robot")
        action = event.payload.get("action") or {}
        result.max_retry_count = max(result.max_retry_count, event.retry_count)
        before = _snapshot()
        pos_before = robot.get_position() if robot else None
        orig_drop(event)
        if robot is not None and _changed(before):
            target = handler._get_drop_position_for_action(action, robot=robot)
            if action.get("type") == "remove_target":
                valid = engine.state.find_pickstation_at(pos_before) is not None
            else:
                valid = target is None or pos_before == target
            if not valid:
                result.physically_invalid_drops += 1
                result.add(engine.state.t, "INVALID_DROP_POSITION",
                           f"robot {robot.robot_id} @{pos_before} "
                           f"drop to {target} ({action.get('type')})")

    def observed_move(event):
        robot = event.payload.get("robot")
        result.max_retry_count = max(result.max_retry_count, event.retry_count)
        pos_before = robot.get_position() if robot else None
        # Echt stale: Der Roboter hat gar keinen offenen Wegpunkt mehr.
        # (Blockierte Moves haben einen Wegpunkt und sind nicht stale.)
        if robot is not None and robot.get_next_waypoint() is None:
            result.stale_move_events += 1
        orig_move(event)
        if robot is None:
            return
        pos_after = robot.get_position()
        if pos_before is not None and pos_after is not None and pos_before != pos_after:
            dx = abs(pos_after[0] - pos_before[0])
            dy = abs(pos_after[1] - pos_before[1])
            if dx + dy != 1:
                result.invalid_moves += 1
                result.add(engine.state.t, "INVALID_MOVE_STEP",
                           f"robot {robot.robot_id} {pos_before} -> {pos_after}")
            gw, gd = engine.state.grid.width, engine.state.grid.depth
            if not (0 <= pos_after[0] < gw and 0 <= pos_after[1] < gd):
                result.invalid_moves += 1
                result.add(engine.state.t, "MOVE_OUT_OF_BOUNDS",
                           f"robot {robot.robot_id} -> {pos_after}")

    handler._handle_robot_pickup = observed_pickup
    handler._handle_robot_drop = observed_drop
    handler._handle_robot_move = observed_move


# ======================================================================
# Lauf-Treiber
# ======================================================================

def run_audit(config, label="", max_steps=4_000_000, check_every=1):
    """
    Führt einen Simulationslauf mit vollständiger Invariantenprüfung aus.

    Args:
        config: SimulationConfig
        label: Beschriftung für den Report
        max_steps: Sicherheitsgrenze
        check_every: Invarianten alle N Zeitschritte prüfen (1 = jeder Schritt)
    """
    import time
    from simulation.simulation_engine import SimulationEngine

    params = {
        "grid": f"{config.grid_width}x{config.grid_depth}",
        "max_height": config.max_stack_height,
        "bins": config.bin_num,
        "robots": config.num_robots,
        "pickstations": config.num_pickstations,
        "util": config.request_utilization,
        "sim_time": config.simulation_time,
        "seed": config.random_seed,
        "reordering": getattr(config, "reordering_strategy", None),
        "placement": getattr(config, "placement_strategy", None),
        "bin_prob": getattr(config, "bin_request_prob_strategy", None),
    }
    result = AuditResult(label, params)

    engine = SimulationEngine(config)
    _install_observers(engine, result)

    best_progress = 0
    last_progress_t = 0
    last_t = -1
    started = time.time()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            for _ in range(max_steps):
                if engine.step() is None:
                    break
                result.steps += 1
                t = engine.state.t
                if t == last_t:
                    continue
                last_t = t

                if t % check_every == 0:
                    check_bin_invariants(engine, result)
                    check_robot_invariants(engine, result)
                    check_task_invariants(engine, result)
                    check_pickstation_invariants(engine, result)
                    check_reservation_invariants(engine, result)
                    check_wait_graph(engine, result)

                current = progress_counter(engine)
                if current > best_progress:
                    best_progress = current
                    last_progress_t = t
                result.max_no_progress_window = max(
                    result.max_no_progress_window, t - last_progress_t
                )
        except Exception as exc:  # pragma: no cover - Diagnosepfad
            result.error = f"{type(exc).__name__}: {exc}"

    result.wall_seconds = round(time.time() - started, 1)
    result.t_end = engine.state.t
    result.progress_events = best_progress
    try:
        result.summary = engine.metrics.summary()
    except Exception as exc:
        result.summary = {}
        result.add(result.t_end, "METRICS_SUMMARY_FAILED", str(exc))

    output = buf.getvalue()
    for name, pattern in _LOG_PATTERNS.items():
        setattr(result, name, len(pattern.findall(output)))

    # Wartezeiten aus dem Endzustand
    for ps in engine.state.pickstations:
        for task, arrival in ps.queue:
            result.longest_ps_service_wait = max(
                result.longest_ps_service_wait, engine.state.t - arrival
            )

    # Längste Wartezeit eines am Ende noch offenen Tasks
    for task in _all_known_tasks(engine):
        arrival = getattr(task.request, "arrival_time", None)
        if arrival is not None:
            result.longest_task_wait = max(
                result.longest_task_wait, engine.state.t - arrival
            )

    # Längste Zeit, die ein Roboter am Ende busy ohne Abschluss war
    for robot in engine.state.robots:
        if robot.status != "idle" and robot.current_task is not None:
            arrival = getattr(robot.current_task.request, "arrival_time", None)
            if arrival is not None:
                result.longest_robot_busy_without_progress = max(
                    result.longest_robot_busy_without_progress,
                    engine.state.t - arrival,
                )

    result.engine = engine
    result.log = output
    return result
