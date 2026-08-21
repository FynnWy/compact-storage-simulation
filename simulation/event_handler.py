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

        # Schwelle für identisch wiederholte Aktionen (gleicher Task, gleiche
        # Bin, gleiches Ziel). Wird sie erreicht, blockiert der Roboter
        # typischerweise eine Ressource, die ein anderer Task erst freigeben
        # muss → Task requeuen. Nur wirksam in Kombination mit der
        # Retry-Persistenz (`_is_same_attempt`).
        self.max_repeated_action_retries_before_requeue = 15

        # Drop-Blockaden: Ab dieser Retry-Zahl wird ein voller/gesperrter
        # Ziel-Stack durch einen Ausweich-Stack ersetzt, statt endlos zu
        # delayen (bis `max_retries` → RuntimeError).
        self.max_drop_retries_before_redirect = 5

        # Drop-Positionsfehler: Ab dieser Retry-Zahl OHNE Bewegungsfortschritt
        # wird die Bewegung zur Ablageposition neu geplant (analog zu
        # Pickup-Positionsfehlern).
        self.max_drop_position_retries_before_replan = 5
        # Letzte beobachtete Position je (Art, Roboter) beim Warten auf eine
        # Pickup-/Drop-Position – dient der Fortschrittserkennung.
        # Bewegung = echter Fortschritt = kein fehlgeschlagener Versuch.
        self._position_wait_by_robot = {}

        # Move-Blockaden: frühes Replaning und Duplikat-Schutz
        self.max_move_retries_before_replan = 1
        self.max_move_retries_before_force_replan = 2

        # PHASE 2D: Semantische MOVE-Stall-Erkennung.
        # Der ereignisbezogene `retry_count` ist als Eskalationsmaß für
        # Bewegungen strukturell unbrauchbar, weil er zurückgesetzt wird,
        # sobald ein übergeordneter Replan (z.B. `[REPLAN][PICKUP_POS]`) neue
        # MOVE-Events erzeugt. Gemessen: ein Roboter stand 157 ZE still und
        # erreichte dabei nie `retry_count > 2`.
        #
        # Maßgeblich ist stattdessen die fachliche Identität des
        # Bewegungsversuchs:
        #     gleicher Robot + gleicher Task + gleiche Taskphase
        #     + keine tatsächliche Positionsänderung
        # Sobald sich einer dieser Punkte ändert, beginnt ein neuer Versuch.
        #
        # Die Schwelle ist NICHT geraten, sondern aus zwei unabhängigen
        # Quellen abgeleitet:
        #
        # (a) Physikalisch: Der längste legitime Grund, an einer Zelle zu
        #     warten, ist eine volle Gridquerung des Blockierers
        #     (20x30 -> ~48 Manhattan-Schritte a 1 ZE) plus eine
        #     Pickstation-Bedienung (4-6 ZE je Bin). Alles jenseits des
        #     Doppelten davon ist kein Stau mehr.
        #
        # (b) Gemessen (Baseline 29c075b, 1200 ZE, LOFI/RANDOM, 8 Roboter):
        #     Dauer der Stall-Episoden je Bewegungsidentität
        #       Seed 99 (gesund):        p99=17   max=31
        #       Seed 42 (gesund):        p99=22   max=48
        #       Seed 3  (Dauerstall):    p99=29   max=404, Ausreißer ab 172
        #       Seed 4  (Dauerstall):    p99=24   max=448, Ausreißer ab 198
        #     Zwischen dem größten normalen Stau (107) und dem kleinsten
        #     pathologischen Fall (172) liegt eine deutliche Lücke.
        #
        # 120 liegt in dieser Lücke. Eine frühere Fassung mit 25 lag mitten
        # im Normalbereich und hat gesunde Seeds messbar verschlechtert
        # (Seed 42: Fortschrittsereignisse 281 -> 176, Replans 705 -> 2357),
        # weil sie normalen Stau als Stall behandelt hat.
        self.max_move_stall_before_recovery = 120
        self._move_stall_state = {}
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

        # PHASE 2D: Hängt der Roboter zu lange am selben Bewegungsversuch,
        # greift eine zustandsverändernde Recovery – unabhängig davon, welcher
        # der Blockade-Zweige unten zuschlägt.
        #
        # Zwei Auslöser, weil derselbe Portstau in zwei Ausprägungen auftritt:
        #
        #   (1) Semantischer Stall: Ein übergeordneter Replan erzeugt laufend
        #       neue MOVE-Events und setzt `retry_count` zurück. Der Roboter
        #       steht beliebig lange, ohne die Retry-Leiter je zu erreichen.
        #       Beobachtet bei LOFI/RANDOM Seed 3/4 (dauerhafter Stillstand).
        #
        #   (2) Erschöpfte Retry-Leiter: Findet kein Replan statt, läuft
        #       `retry_count` bis `max_retries` und `delay_event` wirft
        #       `RuntimeError: Event exceeded max retries`. Beobachtet bei
        #       ABC/ABC Seed 3 (harter Abbruch bei t=868).
        #
        # Beide Ausprägungen sind derselbe Konflikt. Das Ende der bestehenden
        # Retry-Leiter ist deshalb kein Abbruchgrund, sondern der letzte
        # Sprosse: erst Recovery versuchen, dann erst scheitern.
        # `max_retries` wird über `getattr` gelesen, weil der EventBuilder in
        # mehreren Tests durch ein schlankes Dummy ersetzt ist, das die
        # Retry-Leiter gar nicht kennt. Fehlt das Attribut, gibt es auch keine
        # erschöpfte Leiter – dann bleibt allein der semantische Stall übrig.
        max_retries = getattr(self.event_builder, "max_retries", None)
        retry_ladder_exhausted = (
            max_retries is not None and event.retry_count >= max_retries
        )
        stalled_for = self._note_move_stall(robot)

        if (stalled_for >= self.max_move_stall_before_recovery
                or retry_ladder_exhausted):
            if self._recover_stalled_move(
                    robot, next_waypoint, event,
                    reason="retry_ladder" if retry_ladder_exhausted
                    else "stall",
                    stalled_for=stalled_for,
            ):
                return

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

        # AUDIT-002 (Phase 2B): Der frühere Zweig „alle Zellen links vom Grid
        # (x < 0) gelten als PS-Bereich" ist entfallen. Ports liegen laut
        # `Pickstation_Logik.md` vollständig IM Grid; Positionen außerhalb sind
        # keine gültigen Modellpositionen mehr.

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

                        # HARDENING (2026-08-19): Auch im PS-Bereich muss die
                        # Wartebeziehung registriert und ein Zyklus aufgelöst
                        # werden. Vorher fehlte das hier komplett – Konflikte
                        # um die Port-Zelle blieben für den Wait-Graph
                        # unsichtbar, weil nur eine der beiden Kanten entstand.
                        if self._register_wait_and_try_resolve(
                                robot=robot,
                                other=other,
                                contested_cell=next_waypoint,
                                event=event,
                        ):
                            return

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
                    # HARDENING (2026-08-19): Verwaiste Port-Reservierung.
                    # Ein Roboter reserviert den Port beim Anfahren. Plant er
                    # danach um (z.B. weil sein Task in eine andere Phase
                    # wechselt), blieb die Reservierung für immer bestehen –
                    # alle anderen warteten unbegrenzt (kein Eskalationspfad).
                    # Die Reservierung ist verwaist, wenn ihr Halter weder auf
                    # dem Port steht noch ihn noch anfährt.
                    if self._release_stale_port_reservation(pickstation_at_next):
                        if not pickstation_at_next.reserve(robot.robot_id):
                            pass  # weiterhin blockiert → normale Behandlung

                if not pickstation_at_next.is_reserved_by(robot.robot_id):
                    # Port ist für anderen Roboter reserviert → Move verzögern
                    print(
                        f"[INFO] Robot {robot.robot_id} cannot reserve port "
                        f"{pickstation_at_next.station_id} at {next_waypoint} "
                        f"at time {self.state.t}, retrying..."
                    )

                    # HARDENING (2026-08-19): Port-Warten hatte bisher KEINE
                    # Eskalation (Architektur-Karte 5.3, Punkt 4). Hält ein
                    # Roboter die Port-Reservierung, kommt aber selbst nicht an
                    # (weil er blockiert ist), warteten alle anderen unbegrenzt.
                    # Gemessen: Reservierung 223 ZE ohne Anwesenheit.
                    # Die Wartebeziehung wird jetzt registriert, damit der
                    # vorhandene Wait-Graph den Zyklus sehen kann.
                    holder_id = pickstation_at_next.reserved_for_robot
                    holder = next(
                        (r for r in self.state.robots if r.robot_id == holder_id),
                        None,
                    )
                    if (
                            holder is not None
                            and event.retry_count >= self.max_move_retries_before_replan
                    ):
                        if self._register_wait_and_try_resolve(
                                robot=robot,
                                other=holder,
                                contested_cell=holder.get_position(),
                                event=event,
                        ):
                            return

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

                    # Deadlock-Check VOR dem Replanning
                    if self._register_wait_and_try_resolve(
                            robot=robot,
                            other=other,
                            contested_cell=next_waypoint,
                            event=event,
                    ):
                        return

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

        # HARDENING (2026-08-19): Fehlender semantischer Cleanup-Punkt.
        # Ein Roboter, der sich tatsächlich bewegt hat, wartet per Definition
        # nicht mehr. Ohne dieses Löschen überlebte die Wartekante die
        # Auflösung des Konflikts und bildete später Phantom-Zyklen
        # (reproduziert: 7x7, 2 Robots, Seed 42, t=320 – wartender Roboter
        # hatte gar keinen Pfad mehr).
        # Bewusst semantisch statt zeitbasiert (kein TTL).
        if hasattr(self.state, "traffic_manager"):
            self.state.traffic_manager.deadlock_detector.clear_wait(robot.robot_id)

        # PHASE 2D: Tatsächlicher Positionsfortschritt beendet den laufenden
        # Bewegungsversuch – das Stall-Budget beginnt neu.
        self._clear_move_stall(robot)

        # AUDIT-005 (Phase 2B): Port-Reservierung proaktiv freigeben.
        # Ein Roboter, der eine Station reserviert hat und danach umplant
        # (z.B. weil ihm eine ANDERE Station zugeordnet wurde), hielt die
        # Reservierung bis zur nächsten Kollision. Beobachtet: PS_0 51 Schritte
        # gehalten, während der Roboter PS_1 anfuhr.
        self._release_own_stale_port_reservations(robot)

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

        FIX 3 (2026-08-19), zwei Korrekturen:

        1. Ist die blockierte Zelle gleich dem Ziel des Roboters, ist ein
           Umplanen konstruktiv unmöglich (A* darf das Ziel nicht betreten).
           Statt sinnlos zu planen wird nur verzögert – die Wartekante bleibt
           bestehen, damit die Deadlock-Erkennung greifen kann.
        2. Es werden nur noch die Reservierungen freigegeben, NICHT die
           Wartekante. Vorher löschte `release_robot_reservations` über
           `clear_wait` genau die Kante, die unmittelbar davor für diesen
           Konflikt registriert worden war → der Wait-Graph enthielt nie beide
           Kanten eines Swap-Konflikts und `detect_cycle` schlug strukturell
           nie an.
        """
        # Aktuelles Ziel aus dem geplanten Pfad holen
        if not robot.planned_path:
            return

        final_destination = robot.planned_path[-1]
        current_position = robot.get_position()

        if blocked_position == final_destination:
            # Umplanen um das eigene Ziel herum kann per Definition nicht
            # gelingen. Nur warten; die Auflösung übernimmt die
            # Deadlock-Erkennung/Recovery.
            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return

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
            # Alte Reservierungen freigeben – Wartekante bleibt bewusst stehen.
            self.state.reservation_table.release_all(robot.robot_id)

            # Neuen Pfad reservieren und setzen
            success, _ = self.state.reservation_table.reserve_path(
                robot_id=robot.robot_id,
                path=new_path,
                start_time=self.state.t,
            )

            if success:
                robot.set_path(new_path, robot.path_target_action)
                # Pfad steht → Konflikt für diesen Robot aufgelöst
                self.state.traffic_manager.deadlock_detector.clear_wait(
                    robot.robot_id
                )
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

    # Felder, die einen fachlichen Versuch identifizieren.
    # Ändert sich eines davon, ist es ein NEUER Versuch und das Retry-Budget
    # beginnt wieder bei 0.
    _ATTEMPT_IDENTITY_KEYS = ("type", "return_kind", "bin_id", "from_stack", "to_stack")

    def _release_own_stale_port_reservations(self, robot):
        """
        Gibt Port-Reservierungen frei, die dieser Roboter hält, obwohl er die
        betreffende Station weder besetzt noch noch anfährt.

        Semantische Prüfung ohne Timeout: Steht der Roboter nicht auf der
        Station und enthält sein Restpfad sie nicht, kann er die Reservierung
        nicht mehr einlösen.
        """
        position = robot.get_position()
        remaining = robot.planned_path[robot.path_index:]

        for pickstation in self.state.pickstations:
            if pickstation.reserved_for_robot != robot.robot_id:
                continue
            if pickstation.robot_on_port == robot.robot_id:
                continue
            if position == pickstation.position:
                continue
            if pickstation.position in remaining:
                continue

            print(
                f"[RECOVERY][PORT] t={self.state.t} robot {robot.robot_id} "
                f"releases {pickstation.station_id} (at {position}, "
                f"not heading there)"
            )
            pickstation.release_reservation()

    def _release_stale_port_reservation(self, pickstation):
        """
        Gibt eine verwaiste Port-Reservierung frei.

        Eine Reservierung gilt als verwaist, wenn ihr Halter
        - nicht physisch auf dem Port steht UND
        - den Port auch nicht mehr in seinem Restpfad anfährt.

        Semantische Prüfung, bewusst kein Timeout: Ein Roboter, der weder da
        ist noch hinfährt, kann die Reservierung nicht mehr einlösen.

        Returns:
            bool: True, wenn eine Reservierung freigegeben wurde.
        """
        holder_id = pickstation.reserved_for_robot

        if holder_id is None or pickstation.is_occupied():
            return False

        holder = next(
            (r for r in self.state.robots if r.robot_id == holder_id),
            None,
        )

        if holder is None:
            pickstation.release_reservation()
            return True

        if holder.get_position() == pickstation.position:
            return False

        remaining_path = holder.planned_path[holder.path_index:]
        if pickstation.position in remaining_path:
            return False

        print(
            f"[RECOVERY][PORT] t={self.state.t} releasing stale reservation of "
            f"{pickstation.station_id} held by robot {holder_id} "
            f"(at {holder.get_position()}, not heading to {pickstation.position})"
        )
        pickstation.release_reservation()
        return True

    def _note_position_progress(self, kind, robot, position):
        """
        Merkt die Position eines wartenden Roboters und meldet Bewegung.

        Returns:
            bool: True, wenn sich der Roboter seit der letzten Prüfung bewegt
                  hat (= echter Fortschritt, kein fehlgeschlagener Versuch).
        """
        key = (kind, robot.robot_id)
        previous = self._position_wait_by_robot.get(key)
        self._position_wait_by_robot[key] = position
        return previous is not None and previous != position

    @classmethod
    def _is_same_attempt(cls, old_action, new_action):
        """
        Prüft, ob zwei Aktionen denselben fachlichen Versuch beschreiben.

        Retry-Semantik (Hardening 2026-08-19):
        Retry-Fortschritt darf nur erhalten bleiben, wenn wirklich derselbe
        Versuch wiederholt wird – gleiche Aktionsart, gleiche Bin, gleiche
        Quelle, gleiches Ziel. Sobald die Recovery ein anderes Ziel wählt
        (z.B. Drop-Redirect auf einen Ausweich-Stack), die Task-Phase wechselt
        oder eine andere Bin bearbeitet wird, ist es ein neuer, sinnvoller
        Versuch und darf nicht mit fast erschöpftem Budget starten.
        """
        if old_action is None or new_action is None:
            return False

        return all(
            old_action.get(key) == new_action.get(key)
            for key in cls._ATTEMPT_IDENTITY_KEYS
        )

    # ==================================================================
    # MOVE-Stall-Erkennung und -Recovery (Phase 2D)
    # ==================================================================

    def _move_attempt_identity(self, robot):
        """
        Fachliche Identität des aktuellen Bewegungsversuchs.

        Ändert sich eines dieser Merkmale, ist es ein NEUER Versuch und das
        Stall-Budget beginnt von vorn. Bewusst OHNE den geplanten Pfad: Ein
        Replan um dasselbe Hindernis ist kein neuer Versuch – genau dieses
        Zurücksetzen hat die Eskalation bisher verhindert.
        """
        task = robot.current_task
        return (
            robot.robot_id,
            getattr(task, "request_id", None),
            getattr(task, "phase", None),
            robot.get_position(),
        )

    def _note_move_stall(self, robot):
        """
        Zählt, wie lange der Roboter schon ohne Positionsfortschritt am selben
        Bewegungsversuch hängt.

        Returns:
            int: Dauer in Zeitschritten seit Beginn dieses Versuchs.
        """
        identity = self._move_attempt_identity(robot)
        state = self._move_stall_state.get(robot.robot_id)

        if state is None or state[0] != identity:
            self._move_stall_state[robot.robot_id] = (identity, self.state.t)
            return 0

        return self.state.t - state[1]

    def _clear_move_stall(self, robot):
        """Wird nach jedem tatsächlich ausgeführten Bewegungsschritt gerufen."""
        self._move_stall_state.pop(robot.robot_id, None)

    def _requeue_move_after_recovery(self, robot):
        """
        Stellt nach einer erfolgreichen Recovery einen frischen Bewegungsversuch
        zu.

        Bewusst ein NEUES Event statt `delay_event`:
        Die Recovery hat den Konflikt verändert, damit beginnt fachlich ein
        neuer Versuch. Ein fortgeschriebener `retry_count` würde denselben
        Versuch weiterzählen und im Fall der erschöpften Retry-Leiter sofort
        `RuntimeError: Event exceeded max retries` auslösen – also genau den
        Abbruch, den die Recovery verhindern soll.
        """
        fresh = self.event_builder.build_robot_move_event(
            robot, self.state.t + self.event_builder.delay_time
        )
        self.event_queue.push(fresh)

    def _recover_stalled_move(self, robot, next_waypoint, event,
                              reason="stall", stalled_for=None):
        """
        Zustandsverändernde Recovery für einen dauerhaft blockierten Roboter.

        Nutzt ausschließlich vorhandene Mechanik (`_evade_robot`,
        `_resolve_move_deadlock`). Es wird KEINE zweite Recovery-Architektur
        aufgebaut.

        Args:
            reason: "stall" (semantischer Dauerstillstand) oder
                    "retry_ladder" (bestehende Retry-Leiter erschöpft).
            stalled_for: gemessene Standzeit in ZE, nur für die Diagnose.

        Eskalationsreihenfolge:
          1. Der Steckengebliebene weicht selbst aus.
          2. Der Roboter, der ihn direkt blockiert, weicht aus
             (er ist typischerweise selbst Teil des Staus).
          3. Alle Roboter in unmittelbarer Nachbarschaft werden als Opfer
             probiert – der Blockierte ist im Stau eingekeilt, also muss
             jemand aus dem Ring Platz machen.

        Carrying Safety: `_resolve_move_deadlock` requeued einen tragenden
        Roboter nicht (Phase-2B-Invariante). Ausweichen selbst ist für
        tragende Roboter sicher – der Drop-Positions-Guard verhindert
        anschließend jede physisch unmögliche Ablage.

        Returns:
            bool: True, wenn ein zustandsverändernder Schritt erfolgt ist.
        """
        blocker = next(
            (r for r in self.state.robots
             if r.robot_id != robot.robot_id
             and r.get_position() == next_waypoint),
            None,
        )

        position = robot.get_position()
        occupies_foreign_port = False
        station_here = self.state.find_pickstation_at(position)
        if station_here is not None:
            assigned = getattr(robot.current_task, "assigned_pickstation", None)
            occupies_foreign_port = (
                assigned is not None and assigned != station_here.station_id
            )

        print(
            f"[RECOVERY][MOVE_STALL] t={self.state.t} robot={robot.robot_id} "
            f"@{position} grund={reason} standzeit={stalled_for} "
            f"retry={event.retry_count} next={next_waypoint} "
            f"blocker={blocker.robot_id if blocker else None} "
            f"belegt_fremden_port={occupies_foreign_port}"
        )

        # 1) Der Steckengebliebene selbst
        if self._resolve_move_deadlock(
                victim=robot,
                contested_cell=next_waypoint,
                waiting_robot=blocker if blocker is not None else robot,
        ):
            self._clear_move_stall(robot)
            self._requeue_move_after_recovery(robot)
            return True

        # 2) Der direkte Blockierer
        candidates = []
        if blocker is not None:
            candidates.append(blocker)

        # 3) Der Ring um den Blockierten
        x, y = position
        ring = {(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)}
        for other in self.state.robots:
            if other.robot_id == robot.robot_id:
                continue
            if other in candidates:
                continue
            if other.get_position() in ring:
                candidates.append(other)

        for candidate in candidates:
            if self._resolve_move_deadlock(
                    victim=candidate,
                    contested_cell=candidate.get_position(),
                    waiting_robot=robot,
            ):
                # Der Blockierte selbst bleibt im Stall-Zustand, bis er sich
                # wirklich bewegt – das Budget wird nicht künstlich verlängert.
                self._requeue_move_after_recovery(robot)
                return True

        print(
            f"[RECOVERY][MOVE_STALL] t={self.state.t} robot={robot.robot_id} "
            f"keine Auflösung möglich (Kandidaten: "
            f"{[c.robot_id for c in candidates]})"
        )
        return False

    def _register_wait_and_try_resolve(self, robot, other, contested_cell, event):
        """
        Registriert die Wartebeziehung `robot → other` und löst einen dadurch
        entstandenen Zyklus auf.

        Extrahiert aus `_handle_robot_move` (Verhalten unverändert), damit
        sowohl der allgemeine Blockade-Zweig als auch der PS-Bereich-Zweig
        dieselbe Erkennung nutzen.

        Returns:
            bool: True, wenn ein Deadlock aufgelöst und das Event verzögert
                  wurde (Aufrufer soll sofort zurückkehren).
        """
        if not hasattr(self.state, "traffic_manager"):
            return False

        tm = self.state.traffic_manager

        tm.deadlock_detector.register_wait(
            waiting_robot_id=robot.robot_id,
            blocking_robot_id=other.robot_id,
            reason="path_blocked",
            current_time=self.state.t,
        )

        victim_id = tm.check_and_resolve_deadlock(
            robots=self.state.robots,
            scheduler=self.scheduler,
            current_time=self.state.t,
        )

        if victim_id is None:
            return False

        # Deadlock erkannt – Victim muss tatsächlich Platz machen.
        # FIX 3 (2026-08-19): Vorher wurde hier nur verzögert (Opfer == eigener
        # Robot) bzw. gar nichts getan (`pass`, Opfer == anderer Robot).
        victim = next(
            (r for r in self.state.robots if r.robot_id == victim_id),
            None
        )

        if victim is None:
            return False

        # HARDENING (2026-08-19): Kann das vom Resolver gewählte Opfer nicht
        # auflösen (keine freie Nachbarzelle, oder es trägt eine Bin und darf
        # deshalb nicht requeued werden), werden ALLE weiteren Roboter des
        # Zyklus als Opfer probiert – zuletzt der wartende Roboter selbst.
        # Grund: Bei mehreren Robotern rund um einen einzigen Port ist der
        # „beste" Kandidat oft komplett eingekeilt, während ein anderer
        # Beteiligter problemlos Platz machen könnte. Ohne diese Erweiterung
        # würde hier nur verzögert – der Konflikt bliebe bestehen
        # (verbotenes Anti-Pattern).
        cycle = tm.deadlock_detector.detect_cycle() or []
        by_id = {r.robot_id: r for r in self.state.robots}

        candidates = [victim]
        for robot_id in sorted(cycle):
            candidate = by_id.get(robot_id)
            if candidate is not None and candidate not in candidates:
                candidates.append(candidate)
        if robot not in candidates:
            candidates.append(robot)

        resolved = False
        for candidate in candidates:
            partner = robot if candidate is not robot else victim
            if self._resolve_move_deadlock(
                    victim=candidate,
                    contested_cell=contested_cell,
                    waiting_robot=partner,
            ):
                resolved = True
                break

        if not resolved:
            # Nicht auflösbar → Aufrufer soll normal weiter umplanen/warten.
            return False

        # Der wartende Robot versucht es im nächsten Zeitschritt erneut –
        # die Zelle sollte dann frei sein.
        delayed_event = self.event_builder.delay_event(event, self.state.t)
        self.event_queue.push(delayed_event)
        return True

    def _resolve_move_deadlock(self, victim, contested_cell, waiting_robot):
        """
        Löst einen erkannten Bewegungs-Deadlock auf, sodass echter Fortschritt
        entsteht.

        Hintergrund (FIX 3, 2026-08-19):
        Beim Swap-Konflikt (A will auf B's Zelle, B will auf A's Zelle) kann
        **kein** Umplanen helfen – die Zielzelle ist genau die blockierte Zelle.
        Einer der beiden muss die Zelle physisch räumen.

        Eskalationsreihenfolge:
        1. Opfer weicht einen Schritt auf eine freie Nachbarzelle aus.
        2. Ist keine freie Nachbarzelle vorhanden: Task des Opfers requeuen
           (bereits vorhandenes Muster aus dem Engine-Deadlock-Resolver).
        """
        # Die Zelle des wartenden Roboters und die umstrittene Zelle sind für
        # das Ausweichen tabu.
        forbidden = {contested_cell}
        waiting_position = waiting_robot.get_position()
        if waiting_position is not None:
            forbidden.add(waiting_position)

        if self._evade_robot(victim, forbidden_cells=forbidden):
            print(
                f"[DEADLOCK] Robot {victim.robot_id} evades to break deadlock "
                f"with robot {waiting_robot.robot_id} at t={self.state.t}"
            )
            return True

        # HARDENING (2026-08-19): Ein Roboter, der eine Bin trägt, darf NICHT
        # requeued werden. `clear_task()` würde ihn von seinem Task trennen,
        # während die Bin weiterhin `in_transit` an ihm hängt – die Bin wäre
        # damit weder in einem Stack noch einem Task zugeordnet.
        # Beobachtet vor diesem Guard: gestrandete Bin 86 → Return-Pickups
        # mit "bin already in transit" bis `max_retries` → RuntimeError.
        if victim.is_carrying_bin():
            print(
                f"[DEADLOCK] t={self.state.t} robot={victim.robot_id} cannot "
                f"evade but carries bin {victim.get_carried_bin()} -> no "
                f"requeue (would strand the bin)"
            )
            return False

        # Keine freie Nachbarzelle → Task zurück in die Warteschlange
        task = victim.current_task
        if task is not None:
            print(
                f"[DEADLOCK][REQUEUE] t={self.state.t} robot={victim.robot_id} "
                f"cannot evade -> requeue task {task.request_id}"
            )
            self.state.traffic_manager.release_robot_reservations(victim)
            victim.clear_task()
            self.active_queue.add_waiting_task(task)
            self._handle_robot_becomes_idle(victim)
            return True

        print(
            f"[DEADLOCK] t={self.state.t} robot={victim.robot_id} cannot evade "
            f"and has no task to requeue"
        )
        return False

    def _evade_robot(self, robot, forbidden_cells):
        """
        Bewegt einen Roboter einen Schritt auf eine freie Nachbarzelle.

        Der Task bleibt erhalten; nur Position und Pfad ändern sich. Das
        anstehende Pickup-/Drop-Event des Roboters läuft danach über die
        bestehende Positions-Prüfung in `_handle_robot_pickup` in ein Replan.

        Auswahl deterministisch (sortiert), damit Szenarien reproduzierbar
        bleiben.

        Returns:
            bool: True, wenn ein Ausweichschritt eingeplant wurde.
        """
        position = robot.get_position()
        if position is None:
            return False

        x, y = position
        candidates = sorted([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])

        occupied = {
            other.get_position()
            for other in self.state.robots
            if other.robot_id != robot.robot_id
        }

        for candidate in candidates:
            cx, cy = candidate

            if not (0 <= cx < self.state.grid.width
                    and 0 <= cy < self.state.grid.depth):
                continue

            if candidate in forbidden_cells or candidate in occupied:
                continue

            # Ports werden beim Ausweichen gemieden: Sie haben eine eigene
            # Reservierungs-/Anwesenheitsbuchhaltung, die hier nicht
            # mitgeführt werden soll.
            if self.state.find_pickstation_at(candidate) is not None:
                continue

            if not self.state.reservation_table.is_free(
                    cx, cy, self.state.t + 1, exclude_robot=robot.robot_id
            ):
                continue

            # Alte Reservierungen des Opfers freigeben und Ausweichzelle belegen
            self.state.reservation_table.release_all(robot.robot_id)
            success, _ = self.state.reservation_table.reserve_path(
                robot_id=robot.robot_id,
                path=[candidate],
                start_time=self.state.t + 1,
            )

            if not success:
                continue

            robot.set_path([candidate], target_action=None)
            self.state.traffic_manager.deadlock_detector.clear_wait(robot.robot_id)

            move_event = self.event_builder.build_robot_move_event(
                robot=robot,
                time=self.state.t + 1,
            )
            self.event_queue.push(move_event)
            return True

        return False

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

        # HARDENING (2026-08-19): Stale/Duplikat-Pickup.
        # Trägt der Roboter die Ziel-Bin bereits, hat der Pickup längst
        # stattgefunden – dieses Event ist ein Duplikat. Es entsteht, wenn ein
        # Task nach dem Pickup neu geplant wird: `_schedule_next_action_for_task_new`
        # beginnt jede physische Aktion grundsätzlich mit einer Pickup-Phase.
        # Ohne diesen Guard scheitert der Pickup dauerhaft ("not on top", die
        # Bin liegt ja in der Hand des Roboters) und läuft in
        # `RuntimeError: Event exceeded max retries`.
        # Korrekte Fortsetzung ist die Drop-Phase.
        if bin_id is not None and robot.get_carried_bin() == bin_id:
            print(
                f"[STALE][PICKUP] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} already carried "
                f"-> continue with drop phase"
            )
            self._schedule_move_to_drop(
                robot=robot,
                action=action,
                request=request,
                start_time=self.state.t + 1,
            )
            return

        # ✅ Prüfe ob Roboter physisch auf dem Stack steht
        # AUDIT-004 (Phase 2B): Ein Roboter kann immer nur EINE Bin tragen.
        # Trägt er bereits eine andere Bin, darf dieser Pickup NICHT ausgeführt
        # werden – sonst wird die Trage-Verknüpfung überschrieben und die
        # erste Bin verwaist dauerhaft `in_transit` (Bin-Verlust).
        # Der Fall "dieselbe Bin" ist oben bereits idempotent behandelt.
        carried_bin_id = robot.get_carried_bin()
        if carried_bin_id is not None and carried_bin_id != bin_id:
            current_task = robot.current_task
            event_request = event.payload.get("request")
            belongs_to_current_task = (
                current_task is not None
                and event_request is not None
                and current_task.request_id == getattr(event_request, "request_id", None)
            )

            # Eskalation: Der Roboter ist nachweislich mit einer anderen Bin
            # beschäftigt. Endloses Verzögern würde in `max_retries` laufen.
            if event.retry_count >= self.max_repeated_action_retries_before_requeue:
                if belongs_to_current_task:
                    # Widerspruch innerhalb desselben Tasks → neu auswerten.
                    print(
                        f"[REPLAN][PICKUP_BUSY] t={self.state.t} "
                        f"robot={robot.robot_id} bin={bin_id} carries "
                        f"{carried_bin_id} -> re-evaluating own task"
                    )
                    self._schedule_next_action_for_task_new(
                        robot=robot,
                        task=current_task,
                        next_action=None,
                        base_time=self.state.t,
                    )
                else:
                    # Das Event gehört zu einem fremden/alten Task; der Roboter
                    # kann es nicht bedienen. Verwerfen statt endlos retrien.
                    print(
                        f"[STALE][PICKUP_BUSY] t={self.state.t} "
                        f"robot={robot.robot_id} bin={bin_id} carries "
                        f"{carried_bin_id} -> drop foreign pickup event"
                    )
                return

            print(
                f"[BLOCKED][PICKUP] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} reason=robot already "
                f"carries bin {carried_bin_id}"
            )
            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return

        # AUDIT-001/004 (Phase 2B): Ein Pickup-Event darf nur ausgeführt werden,
        # wenn es zum aktuell gehaltenen Task des Roboters gehört.
        # Ohne diese Prüfung konnte ein altes Event eines FREMDEN Tasks den
        # Roboter eine fremde Bin aufnehmen lassen; der spätere Drop lief dann
        # gegen den falschen Task
        # (`Cannot mark target returned ...: action bin X is not target bin Y`).
        event_request = event.payload.get("request")
        current_task = robot.current_task
        if (
                current_task is not None
                and event_request is not None
                and current_task.request_id
                != getattr(event_request, "request_id", None)
        ):
            print(
                f"[STALE][PICKUP_TASK] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} belongs to request "
                f"{getattr(event_request, 'request_id', None)}, robot holds task "
                f"{current_task.request_id} -> drop foreign pickup event"
            )
            return

        from_stack = self._get_stack_by_id(self.state, action.get("from_stack"))


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
            #
            # FIX SEED-1 (2026-08-19): Diese Abkürzung gilt AUSSCHLIESSLICH für
            # Target-Returns. Für Blocker-Returns ist `stored` der NORMALE
            # Zustand – die Blocker-Bin liegt planmäßig im Buffer-Stack und
            # wartet auf ihre Rücklagerung. Vorher griff der Zweig auch dort
            # und deutete „Bin liegt im Buffer, aber nicht obenauf" fälschlich
            # als „bereits erledigt" um. `next_action` lieferte daraufhin
            # exakt dieselbe Aktion → Endlosschleife (Seed 1: 457 Wiederholungen).
            if (
                    action_type == "return"
                    and action.get("return_kind") == "target"
                    and task is not None
                    and bin_id is not None
            ):
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
                        # Retry-Semantik (Hardening 2026-08-19):
                        # Liefert die Strategie exakt dieselbe Aktion, ist das
                        # ein weiterer fehlgeschlagener Versuch DESSELBEN
                        # Vorhabens. Dieser Zweig verzögert nicht, also muss der
                        # Zähler hier explizit wachsen – sonst bleibt er ewig 0
                        # und keine Eskalationsschwelle wird je erreicht
                        # (Seed-1-Endlosschleife: 457 identische Wiederholungen).
                        same_attempt = self._is_same_attempt(action, new_action)
                        next_retry = event.retry_count + 1 if same_attempt else 0

                        # Eskalation: Wiederholt sich derselbe Versuch dauerhaft,
                        # blockiert der Roboter meist eine Ressource, die ein
                        # anderer Task erst freigeben muss. Dann Task requeuen
                        # und Roboter freigeben.
                        if (
                                same_attempt
                                and next_retry >= self.max_repeated_action_retries_before_requeue
                                and not robot.is_carrying_bin()
                        ):
                            print(
                                f"[REQUEUE][PICKUP_REPEAT] t={self.state.t} "
                                f"robot={robot.robot_id} action={action_type} "
                                f"bin={bin_id} retry={next_retry} -> requeue "
                                f"task {task.request_id}"
                            )
                            self.state.traffic_manager.release_robot_reservations(robot)
                            robot.clear_task()
                            self.active_queue.add_waiting_task(task)

                            # Der Task allein freizugeben reicht NICHT: Der
                            # Roboter steht weiterhin auf der Zelle, die der
                            # andere Task braucht – und bekommt denselben Task
                            # sofort wieder zugeteilt. Die umstrittene Ressource
                            # ist die Zelle, also muss sie geräumt werden.
                            if not self._evade_robot(robot, forbidden_cells=set()):
                                self._handle_robot_becomes_idle(robot)
                            return

                        print(
                            f"[REPLAN][PICKUP] t={self.state.t} robot={robot.robot_id} "
                            f"task replanning due to stale stack state "
                            f"(same_attempt={same_attempt}, retry={next_retry})"
                        )
                        self._schedule_next_action_for_task_new(
                            robot=robot,
                            task=task,
                            next_action=new_action,
                            base_time=self.state.t,
                            inherited_retry_count=next_retry,
                        )
                        return

            # HARDENING (2026-08-19): Generische Eskalation für den Fallback.
            # Hierher fallen alle Blockade-Gründe, für die es oben keinen
            # Spezialpfad gibt – z.B. „not on top", wenn die Strategie gar
            # keine Anschlussaktion liefert. Ohne Eskalation läuft dieses
            # Event bis `max_retries` und bricht die Simulation ab.
            # Der Roboter trägt an dieser Stelle nichts (der Pickup ist ja
            # gerade fehlgeschlagen), der Requeue ist also zustandssicher.
            if (
                    task is not None
                    and event.retry_count >= self.max_repeated_action_retries_before_requeue
                    and not robot.is_carrying_bin()
            ):
                print(
                    f"[REQUEUE][PICKUP_STUCK] t={self.state.t} robot={robot.robot_id} "
                    f"action={action_type} bin={bin_id} reason={reason} "
                    f"retry={event.retry_count} -> requeue task {task.request_id}"
                )
                self.state.traffic_manager.release_robot_reservations(robot)
                robot.clear_task()
                self.active_queue.add_waiting_task(task)
                if not self._evade_robot(robot, forbidden_cells=set()):
                    self._handle_robot_becomes_idle(robot)
                return

            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return


        # AUDIT-001 (Phase 2B): Positionsprüfung für ALLE Pickups.
        # Vorher galt sie nur für Stack-Pickups (`from_stack is not None`);
        # Pickups an der Pickstation liefen völlig ungeprüft. Die erwartete
        # Position kommt jetzt aus derselben Quelle, die auch die Anfahrt
        # plant – inklusive der verbindlich zugeordneten Station (MP-8).
        expected_pickup_position = self._get_target_position_for_action(
            action, robot=robot
        )

        if expected_pickup_position is not None:
            stack_position = expected_pickup_position
            robot_position = robot.get_position()

            if robot_position != stack_position:
                task = robot.current_task

                # Retry-Semantik (Hardening 2026-08-19): Bewegt sich der
                # Roboter noch Richtung Stack, ist das kein fehlgeschlagener
                # Versuch – Budget zurücksetzen. Nur echtes Feststecken soll
                # die Eskalationsschwellen erreichen.
                if self._note_position_progress("pickup", robot, robot_position):
                    event.retry_count = 0

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
                    # Identische Aktion → derselbe Versuch → Budget mitnehmen,
                    # damit die Requeue-Schwelle (15) erreichbar bleibt.
                    self._schedule_next_action_for_task_new(
                        robot=robot,
                        task=task,
                        next_action=action,
                        base_time=self.state.t,
                        inherited_retry_count=event.retry_count,
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

        # HARDENING (2026-08-19): Roboter trägt die Bin ab jetzt physisch.
        robot.set_carried_bin(bin_id)

        # AUDIT-003 (Phase 2B): Blocker-Restore-Verpflichtung auflösen.
        # Eine Restore-Verpflichtung besteht nur so lange, wie die Bin wegen
        # DIESES Tasks im Buffer liegt. Nimmt ein anderer Task die Bin regulär
        # heraus (weil sie sein Target ist), ist die Verpflichtung
        # gegenstandslos – sonst bliebe sie für immer offen und der
        # Blocker-Task könnte nie abschließen.
        self._release_foreign_blocker_obligation(robot, bin_id)

        # AUDIT-005 (Phase 2B): Genau hier – unmittelbar nach dem erfolgreichen
        # Target-Pickup aus dem Storage – wird die Pickstation für diesen
        # Zyklus EINMAL ausgewählt und verbindlich am Task gespeichert.
        # Danach wird sie nicht mehr neu berechnet (MP-5).
        if action_type == "remove_target":
            task = robot.current_task
            if task is not None:
                station = self._select_pickstation_for_target(robot)
                if station is not None:
                    task.assigned_pickstation = station.station_id
                    print(
                        f"[TRACE][PS_ASSIGN] t={self.state.t} "
                        f"robot={robot.robot_id} bin={bin_id} "
                        f"task={task.request_id} -> {station.station_id} "
                        f"(dist="
                        f"{abs(robot.get_position()[0] - station.position[0]) + abs(robot.get_position()[1] - station.position[1])}"
                        f", load={self._effective_pickstation_load(station)})"
                    )

        print(
            f"[TRACE][PICKUP] t={self.state.t} robot={robot.robot_id} "
            f"bin={bin_id} from={action.get('from_stack')}"
        )

        # Pickup-Dauer (Arm runter, greifen, Arm hoch)
        pickup_duration = self._calculate_pickup_duration(action, self.state)

        self._schedule_move_to_drop(
            robot=robot,
            action=action,
            request=request,
            start_time=self.state.t + pickup_duration,
        )

    def _schedule_move_to_drop(self, robot, action, request, start_time):
        """
        Plant die Bewegung zur Ablageposition und das anschließende Drop-Event.

        Extrahiert aus `_handle_robot_pickup` (Verhalten unverändert), damit die
        Drop-Recovery (`_redirect_blocked_drop`) dieselbe Planung wiederverwenden
        kann, wenn der Ziel-Stack gewechselt werden muss.

        Args:
            robot: Robot, der die Bin trägt
            action: Aktions-Dict (nutzt `to_stack` für die Zielbestimmung)
            request: Request des Tasks
            start_time: Zeitpunkt, ab dem sich der Robot bewegen darf
                        (bei Pickup: t + pickup_duration)
        """
        action_type = action.get("type")

        # Zielposition bestimmen (Pickstation-Zuordnung über den Task)
        target_position = self._get_drop_position_for_action(action, robot=robot)

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

        if not path:
            # Roboter ist bereits am Ziel - direkt Drop
            drop_event = self.event_builder.build_robot_drop_event(
                robot=robot,
                action=action,
                request=request,
                time=start_time,
            )
            self.event_queue.push(drop_event)
            return

        # Pfad-Events erzeugen
        robot.set_path(path, target_action=None)

        current_time = start_time
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

        # HARDENING (2026-08-19): Stale/Duplikat-Drop.
        # Eine Bin, die nicht (mehr) im Transit ist, wurde bereits abgelegt –
        # dieses Event ist ein Duplikat. Duplikate entstehen, weil mehrere
        # Recovery-Pfade (`_handle_drop_position_mismatch`,
        # `_redirect_blocked_drop`, Stale-Pickup) ein neues Drop-Event
        # einplanen, ohne das alte aus der Queue entfernen zu können.
        # Ohne diesen Guard lief der Drop ein zweites Mal durch und
        # `_start_pickstation_service_and_release_robot` fand keinen Task mehr
        # (`RuntimeError: Cannot start pickstation service: robot has no task`).
        if bin_id is not None:
            existing_bin = self.state.get_bin_by_id(bin_id)
            carried = robot.get_carried_bin()

            not_in_transit = (
                existing_bin is not None
                and not getattr(existing_bin, "in_transit", False)
            )
            # Ein Roboter kann immer nur EINE Bin tragen. Zeigt die
            # Trage-Verknüpfung auf eine andere Bin, gehört dieses Drop-Event
            # zu einem längst abgeschlossenen oder abgebrochenen Vorgang.
            # (Beobachtet: zwei DROP_TARGET-Events desselben Roboters im
            # selben Zeitschritt für verschiedene Bins.)
            wrong_bin = carried is not None and carried != bin_id

            # AUDIT-001/004 (Phase 2B): Ein Target-Return darf nur die Ziel-Bin
            # des aktuell gehaltenen Tasks ablegen. Passt sie nicht, gehört das
            # Event zu einem fremden/alten Task und ist stale.
            foreign_target = (
                action_type == "return"
                and action.get("return_kind") == "target"
                and robot.current_task is not None
                and robot.current_task.target_bin_id != bin_id
            )

            if not_in_transit or wrong_bin or foreign_target:
                print(
                    f"[STALE][DROP] t={self.state.t} robot={robot.robot_id} "
                    f"action={action_type} bin={bin_id} "
                    f"(in_transit={not not_in_transit}, carried={carried}) "
                    f"-> skip duplicate drop"
                )
                if action_type == "return" and robot.current_task is not None:
                    # Bestehendes Verhalten: Task weiter auswerten.
                    self._schedule_next_action_for_same_task_new(event)
                return

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

            # Recovery für dauerhaft blockierte Ablagen:
            # Ein voller/gesperrter Ziel-Stack wird nicht von allein frei. Ohne
            # Ausweichen läuft das Event bis `max_retries` und bricht die
            # Simulation mit RuntimeError ab (auch in der Baseline reproduzierbar).
            if (
                    action_type in ("relocate", "return")
                    and reason in ("to_stack is full", "to_stack is locked")
                    and getattr(event, "retry_count", 0)
                    >= self.max_drop_retries_before_redirect
            ):
                if self._redirect_blocked_drop(event, robot, action, request, reason):
                    return

            print(
                f"[BLOCKED][DROP] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} reason={reason}"
            )
            delayed_event = self.event_builder.delay_event(event, self.state.t)
            self.event_queue.push(delayed_event)
            return

        # HARDENING (2026-08-19): Physische Positions-Invariante für Drops.
        # Symmetrisch zur bereits vorhandenen Prüfung in `_handle_robot_pickup`.
        # Ohne sie kann ein Drop-Event den Bin-State verändern, während der
        # Roboter ganz woanders steht – z.B. nach `_evade_robot` oder wenn
        # Move-Events verzögert wurden und das zeitgesteuerte Drop-Event
        # trotzdem fällig wird.
        #
        # Bewusst NACH `_can_drop`: Stack-Constraints (voll/gesperrt/stale)
        # sollen weiterhin unabhängig von der Roboterposition ausgewertet
        # werden – der Redirect auf einen Ausweich-Stack plant die Bewegung
        # ohnehin neu. Der Positions-Guard schützt nur die eigentliche
        # Zustandsänderung.
        if not self._is_robot_at_drop_position(robot, action):
            self._handle_drop_position_mismatch(event, robot, action)
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

        # HARDENING (2026-08-19): Bin ist abgelegt – Roboter trägt nichts mehr.
        if robot.get_carried_bin() == bin_id:
            robot.clear_carried_bin()

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


    def _is_robot_at_drop_position(self, robot, action):
        """
        Prüft, ob der Roboter physisch an der Ablageposition der Aktion steht.

        Layer-Entscheidung (Hardening 2026-08-19):
        Die Invariante gehört in den EventHandler und nicht in `_can_drop`
        oder den ConstraintManager – beide sehen den Roboter gar nicht.
        `_handle_robot_pickup` besitzt die spiegelbildliche Prüfung für die
        Pickup-Hälfte der Zwei-Phasen-Aktion bereits; der Drop-Handler ist
        damit der konsistente Ort.

        Sonderfall `remove_target`: Maßgeblich ist, dass der Roboter auf einer
        Port-Zelle steht (bei mehreren Pickstations ist nicht zwingend die
        erste gemeint).
        """
        if robot is None:
            return True

        robot_position = robot.get_position()
        if robot_position is None:
            return True

        if action.get("type") == "remove_target":
            return self.state.find_pickstation_at(robot_position) is not None

        target_position = self._get_drop_position_for_action(action, robot=robot)
        if target_position is None:
            return True

        return robot_position == target_position

    def _handle_drop_position_mismatch(self, event, robot, action):
        """
        Recovery, wenn der Roboter beim Drop nicht an der Ablageposition steht.

        Eskalation (bewusst ohne Requeue): Der Roboter trägt die Bin bereits.
        Ein Requeue würde sie im Nirgendwo zurücklassen. Die fachlich korrekte
        Auflösung ist immer „Bewegung zum Ablageziel neu planen".

        - unterhalb der Schwelle: verzögern (Roboter ist ggf. noch unterwegs)
        - ab der Schwelle: Bewegung zum Ablageziel neu planen
        """
        action_type = action.get("type")
        bin_id = action.get("bin_id")
        robot_position = robot.get_position() if robot is not None else None
        target_position = self._get_drop_position_for_action(action, robot=robot)

        # Retry-Semantik: Ein Roboter, der sich seit der letzten Prüfung bewegt
        # hat, macht echten Fortschritt Richtung Ablageziel. Das ist KEIN
        # fehlgeschlagener Versuch – das Retry-Budget wird zurückgesetzt.
        # Ohne diese Unterscheidung würde ein normal (aber verzögert)
        # anfahrender Roboter nach 5 Zeitschritten unnötig seinen kompletten
        # Pfad neu planen und dabei seinen Bewegungsfortschritt verlieren.
        if self._note_position_progress("drop", robot, robot_position):
            event.retry_count = 0

        if event.retry_count >= self.max_drop_position_retries_before_replan:
            self._position_wait_by_robot.pop(("drop", robot.robot_id), None)
            print(
                f"[REPLAN][DROP_POS] t={self.state.t} robot={robot.robot_id} "
                f"action={action_type} bin={bin_id} "
                f"(robot at {robot_position}, target {target_position}) "
                f"retry={event.retry_count} -> reschedule movement to drop"
            )
            self._schedule_move_to_drop(
                robot=robot,
                action=action,
                request=event.payload.get("request"),
                start_time=self.state.t,
            )
            return

        print(
            f"[BLOCKED][DROP_POS] t={self.state.t} robot={robot.robot_id} "
            f"action={action_type} bin={bin_id} "
            f"(robot at {robot_position}, target {target_position}) "
            f"- retrying ({event.retry_count + 1}/"
            f"{self.max_drop_position_retries_before_replan})"
        )
        delayed_event = self.event_builder.delay_event(event, self.state.t)
        self.event_queue.push(delayed_event)

    def _redirect_blocked_drop(self, event, robot, action, request, reason):
        """
        Leitet einen dauerhaft blockierten Drop auf einen Ausweich-Stack um.

        Hintergrund:
        `to_stack` wird zum Planungszeitpunkt gewählt. Bis der Robot dort
        ankommt, kann ein anderer Robot den Stack gefüllt oder gesperrt haben.
        Diese Zustände lösen sich nicht von allein auf; ohne Umleitung endet
        das Drop-Event in `max_retries` → RuntimeError.

        Die Auswahl des Ausweich-Stacks delegiert an die bestehende
        Relocation-Selection (gleiche Kriterien wie bei R-D2).

        Returns:
            True, wenn ein Ausweich-Stack gefunden und die Bewegung dorthin
            neu geplant wurde. False, wenn der Aufrufer normal weiter delayen
            soll.
        """
        blocked_stack_id = action.get("to_stack")
        blocked_stack = self._get_stack_by_id(self.state, blocked_stack_id)

        if blocked_stack is None:
            return False

        try:
            alternative = self.scheduler.strategy._select_relocation_stack(
                state=self.state,
                exclude_stack=blocked_stack,
            )
        except RuntimeError as exc:
            print(
                f"[BLOCKED][DROP_REDIRECT] t={self.state.t} robot={robot.robot_id} "
                f"bin={action.get('bin_id')} no alternative stack: {exc}"
            )
            return False

        if alternative is None or alternative.stack_id == blocked_stack_id:
            return False

        # Task-Buchhaltung konsistent halten:
        # Blocker-Returns validieren beim Erfolg gegen temp_storage.
        task = robot.current_task
        if (
                task is not None
                and action.get("type") == "return"
                and action.get("return_kind") == "blocker"
        ):
            bin_id = action.get("bin_id")
            known = any(
                reloc["bin_id"] == bin_id for reloc in task.temp_storage
            )
            if known:
                task.update_return_stack_for_blocker(
                    bin_id=bin_id,
                    new_to_stack=alternative.stack_id,
                )
            else:
                # Ohne temp_storage-Eintrag würde der Erfolgspfad die Umleitung
                # nicht nachvollziehen können → lieber normal weiter delayen.
                return False

        action["to_stack"] = alternative.stack_id

        print(
            f"[REPLAN][DROP_REDIRECT] t={self.state.t} robot={robot.robot_id} "
            f"action={action.get('type')} bin={action.get('bin_id')} "
            f"reason={reason} {blocked_stack_id} -> {alternative.stack_id}"
        )

        # Relocate-Ziele sind auch der Buffer-Stack des Tasks; er wird erst beim
        # erfolgreichen Drop aus der Action übernommen, daher genügt hier das
        # Umplanen der Bewegung.
        self._schedule_move_to_drop(
            robot=robot,
            action=action,
            request=request,
            start_time=self.state.t,
        )
        return True

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


    def _release_foreign_blocker_obligation(self, robot, bin_id):
        """
        Löst die Blocker-Restore-Verpflichtung eines FREMDEN Tasks auf.

        Contract (Phase 2B, AUDIT-003):
        `temp_storage` darf nur Blocker enthalten, deren Restore fachlich noch
        offen ist. Sobald ein anderer Task die Bin regulär aus dem Buffer nimmt
        (sie ist sein Target), ist der Restore-Schritt des Blocker-Tasks
        gegenstandslos: Die Bin wird vom übernehmenden Task ohnehin wieder in
        einem gültigen Stack abgelegt.

        Bewusst NICHT gewählt: ein Verbot, eine fremde Target-Bin als Blocker
        zu bewegen. Blocker ergeben sich physisch aus dem Stapelinhalt; ein
        solches Verbot wäre nicht erfüllbar, ohne Retrievals zu blockieren.
        """
        if bin_id is None:
            return

        owner_task = self.active_queue.get_blocker_owner(bin_id)
        if owner_task is None:
            return

        current_task = robot.current_task
        if current_task is not None and owner_task is current_task:
            # Eigener Blocker-Restore – Verpflichtung bleibt bis zum Drop.
            return

        still_open = any(
            reloc["bin_id"] == bin_id for reloc in owner_task.temp_storage
        )
        if still_open:
            owner_task.release_blocker_ownership(bin_id)

        self.active_queue.release_blocker_ownership(bin_id)

        print(
            f"[OWNERSHIP][RELEASE] t={self.state.t} robot={robot.robot_id} "
            f"bin={bin_id} taken by task "
            f"{current_task.request_id if current_task else None}; "
            f"blocker obligation of task {owner_task.request_id} resolved"
        )

    # ==================================================================
    # Multi-Pickstation-Semantik (Phase 2B, AUDIT-005)
    # ==================================================================

    def _effective_pickstation_load(self, pickstation):
        """
        Effektive Last einer Pickstation.

            effective_load = inbound + waiting_for_service + in_service

        - `in_service`         : Tasks, die aktuell Servicekapazität belegen
                                 (`pickstation.current_tasks`)
        - `waiting_for_service`: Tasks in der Service-Queue der Station
                                 (`pickstation.queue`)
        - `inbound`            : Target-Bins, die dieser Station bereits
                                 verbindlich zugeordnet wurden, sie aber noch
                                 nicht erreicht haben.

        `inbound` wird ohne Schattenbuchhaltung aus vorhandenem Zustand
        abgeleitet: Eine Bin ist genau dann unterwegs, wenn ein Roboter einen
        Task dieser Station trägt, dessen Target die Station noch nicht
        erreicht hat (`target_at_pickstation is False`).

        Doppelzählung ist damit ausgeschlossen: Sobald der Target-Drop erfolgt,
        setzt `mark_waiting_at_pickstation()` das Flag und der Task wandert in
        die Queue der Station. Tasks, deren Service bereits beendet ist
        (`pickstation_completed`), belegen weder Queue noch Kapazität und
        zählen daher nicht mehr als Last.
        """
        inbound = 0
        for robot in self.state.robots:
            task = robot.current_task
            if task is None:
                continue
            if getattr(task, "assigned_pickstation", None) != pickstation.station_id:
                continue
            if getattr(task, "target_at_pickstation", False):
                continue
            inbound += 1

        return inbound + pickstation.queue_length() + len(pickstation.current_tasks)

    def _select_pickstation_for_target(self, robot):
        """
        Wählt die Pickstation für einen gerade aufgenommenen Target-Transport.

        Hierarchische Regel:
          1. minimale Manhattan-Distanz zur aktuellen Roboterposition
          2. bei Distanzgleichstand: minimale `effective_load`
          3. bei vollständigem Gleichstand: stabiler Stationsindex

        Die Auslastung darf eine eindeutig nähere Station NICHT verdrängen.
        """
        stations = self.state.pickstations
        if not stations:
            return None

        position = robot.get_position()
        if position is None:
            return stations[0]

        def sort_key(indexed):
            index, station = indexed
            distance = (
                abs(position[0] - station.position[0])
                + abs(position[1] - station.position[1])
            )
            return (distance, self._effective_pickstation_load(station), index)

        return min(enumerate(stations), key=sort_key)[1]

    def _resolve_assigned_pickstation(self, robot=None, task=None):
        """
        Liefert die für diesen Pickstation-Zyklus verbindlich zugeordnete
        Station.

        Source of Truth ist ausschließlich `RobotTask.assigned_pickstation`.
        Fällt keine Zuordnung auf (z.B. Alt-Pfade ohne Task), wird auf die
        erste Station zurückgefallen – das entspricht dem Verhalten vor
        Phase 2B und ist bei genau einer Station identisch.
        """
        if task is None and robot is not None:
            task = robot.current_task

        station_id = getattr(task, "assigned_pickstation", None)
        if station_id:
            station = self.state.get_pickstation(station_id)
            if station is not None:
                return station

        return self.state.pickstations[0] if self.state.pickstations else None

    def _get_drop_position_for_action(self, action, robot=None, task=None):
        """Bestimmt die Zielposition für den Drop."""
        action_type = action.get("type")

        if action_type == "relocate":
            return self._resolve_position(action.get("to_stack"))

        if action_type == "remove_target":
            # AUDIT-005: Ziel ist die für diesen Zyklus zugeordnete Station,
            # nicht mehr hart `pickstations[0]`.
            station = self._resolve_assigned_pickstation(robot=robot, task=task)
            if station is not None:
                return station.position
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

    def _schedule_next_action_for_task_new(
            self,
            robot,
            task,
            next_action=None,
            base_time=None,
            inherited_retry_count=0,
    ):
        """
        Plant nächste Aktion als Zwei-Phasen-Aktion (task-basierter Helper).

        Args:
            inherited_retry_count:
                Retry-Fortschritt, der auf das neue Pickup-Event übertragen
                wird. Darf nur > 0 sein, wenn es sich fachlich um denselben
                fehlgeschlagenen Versuch handelt (s. `_is_same_attempt`).
        """
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
            pickup_position = self._get_target_position_for_action(next_action, robot=robot, task=task)

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
                    retry_count=inherited_retry_count,
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
                retry_count=inherited_retry_count,
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

        # AUDIT-001 (Phase 2B): Positionsprüfung auch für den Executor-Pfad.
        # Sie wird bewusst als normaler „nicht ausführbar"-Grund behandelt,
        # damit die bereits vorhandene Eskalationsleiter (Delay → Requeue bei
        # `max_action_retries_before_replan`) greift und kein eigener,
        # eskalationsloser Delay-Pfad entsteht.
        if can_execute and action.get("type") == "pickup_from_pickstation":
            exec_robot = event.payload.get("robot")
            exec_station = self.state.get_pickstation(action.get("pickstation_id"))
            if (
                    exec_robot is not None
                    and exec_station is not None
                    and exec_robot.get_position() != exec_station.position
            ):
                can_execute = False
                reason = (
                    f"robot at {exec_robot.get_position()}, "
                    f"{exec_station.station_id} at {exec_station.position}"
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

        # AUDIT-001/004 (Phase 2B): Absicherung des zweiten, noch aktiven
        # Ablaufpfads (`pickup_from_pickstation` über den Executor).
        # Beobachtet: Dieser Pfad feuerte als DUPLIKAT auf Bins, die bereits
        # von der Zwei-Phasen-Pipeline abgeholt wurden (`in_transit=True`),
        # und setzte deren Transit-Flag zurück.
        # Hinweis: Dieser Pfad pflegt bewusst KEIN `carried_bin_id` – siehe
        # dokumentierter Designentscheid in
        # SIMULATION_CONSISTENCY_AUDIT_2026-08-20.md (Phase 2B, AUDIT-001).
        if action.get("type") == "pickup_from_pickstation":
            guard_robot = event.payload.get("robot")
            guard_bin_id = action.get("bin_id")
            guard_bin = self.state.get_bin_by_id(guard_bin_id)
            station = self.state.get_pickstation(action.get("pickstation_id"))

            if guard_bin is not None and getattr(guard_bin, "in_transit", False):
                print(
                    f"[STALE][PICKUP_PS] t={self.state.t} "
                    f"robot={getattr(guard_robot, 'robot_id', None)} "
                    f"bin={guard_bin_id} already in transit -> skip duplicate"
                )
                return

            if guard_robot is not None and guard_robot.is_carrying_bin():
                print(
                    f"[STALE][PICKUP_PS] t={self.state.t} "
                    f"robot={guard_robot.robot_id} bin={guard_bin_id} "
                    f"robot already carries {guard_robot.get_carried_bin()} "
                    f"-> skip"
                )
                return

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

        # AUDIT-005 (Phase 2B): Die Station wurde beim Target-Pickup verbindlich
        # gewählt. Hier wird sie NICHT neu bestimmt – sonst könnte die Bin an
        # einer anderen Station als der geplanten eingereiht werden
        # (Cross-Station-Verwechslung).
        pickstation = self._resolve_assigned_pickstation(task=task)
        if pickstation is None:
            raise RuntimeError(
                f"Cannot start pickstation service: no pickstation available "
                f"for robot {robot.robot_id}"
            )

        # Der Roboter muss physisch an genau dieser Station stehen.
        if robot_position != pickstation.position:
            raise RuntimeError(
                f"Cannot start pickstation service: robot {robot.robot_id} is at "
                f"{robot_position}, but task {task.request_id} is assigned to "
                f"{pickstation.station_id} at {pickstation.position}"
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

        # FIX 1 (2026-08-19): Der Pickstation-Service braucht KEINEN Roboter.
        # Der Start des nächsten Service muss daher unmittelbar nach dem
        # Freiwerden der Kapazität erfolgen und darf nicht hinter den unten
        # folgenden Early Returns (v.a. "No robot available") hängen.
        # Vorher stand dieser Aufruf am Ende der Methode und wurde unter Last
        # praktisch nie erreicht → Pickstation blieb idle trotz voller Queue.
        self._try_start_pickstation_service(pickstation)

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

        # Hinweis: Der nächste Pickstation-Service wurde bereits oben gestartet,
        # direkt nachdem `complete_service` die Kapazität freigegeben hat.

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
        target_position = self._get_target_position_for_action(
            next_action, robot=robot, task=task
        )

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
    
    def _get_target_position_for_action(self, action, robot=None, task=None):
        """
        Bestimmt Zielposition für eine Aktion.

        Args:
            action: Action-Dict
            robot/task: Kontext zur Auflösung der zugeordneten Pickstation

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
                # AUDIT-005: Der Abhol-Roboter fährt zu GENAU der Station, an
                # der die Bin tatsächlich liegt – nicht zur nächstgelegenen.
                station = self._resolve_assigned_pickstation(robot=robot, task=task)
                if station is not None:
                    return station.position
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
                pickup_position = self._get_target_position_for_action(action, robot=robot)
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
            target_position = self._get_target_position_for_action(action, robot=robot)
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