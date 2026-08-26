from simulation.robot_task import RobotTask


class Scheduler:
    # NEU: Prioritätsdefinitionen
    PRIORITY_PICKSTATION_DELIVERY = 1  # Höchste: Bin zur Pickstation bringen
    PRIORITY_DIGGING = 2               # Mittel: Blocker räumen
    PRIORITY_RETURN_STORAGE = 3        # Niedrig: Zurücklagerung
    PRIORITY_IDLE = 4                  # Niedrigste: Idle
    
    def __init__(self, active_queue, strategy, scheduler_strategy="FIFO"):
        self.active_queue = active_queue
        self.strategy = strategy
        self.scheduler_strategy = scheduler_strategy.upper()

    def try_schedule(self, state, current_time):
        """
        Versucht, genau einen Task oder Request einem freien Roboter zuzuordnen.

        Reihenfolge:
        1. Wartende aktive Tasks fortsetzen (bereits begonnene physische
           Vorgänge und Rücklagerungen bleiben geschützt).
        2. Neuen Request nach Scheduler-Strategie (FIFO/EDF).

        FREEZE-AUDIT: Die frühere Zwischenstufe „opportunistisch: Requests,
        deren Bin bereits oben zugänglich ist" ist entfallen.

        Sie war ein lageabhängiger Bypass vor der eigentlichen
        Auswahlstrategie: Unter Backlog wurden bevorzugt Requests bedient,
        deren Target ohnehin obenauf lag. Damit war eine versteckte
        depth-aware Retrieval-Policy aktiv, die genau die Größen verzerrt, die
        das Experiment messen soll.

        Gemessen (20x30, Seed 42, 800 ZE, baseline_reference):

            mit Bypass:  39 von 47 Zuweisungen opportunistisch,
                         β = 0,73, Retrievals aus den obersten 20 % = 84 %
            ohne Bypass: β = 2,70, Retrievals aus den obersten 20 % = 33 %

        Der Bypass hätte Mellers 80/20-Behauptung (RQ3) also scheinbar
        bestätigt, obwohl der Effekt aus der Request-Auswahl stammte und
        nicht aus Natural Slotting.

        Der zweite Zweck des alten Zweigs – der opportunistische
        Ownership-Transfer einer bereits ausgelagerten Blocker-Bin – ist
        entbehrlich: Blocker-owned Bins sind über
        `get_all_reserved_bin_ids()` ohnehin von der Auswahl ausgeschlossen
        und werden frei, sobald der Eigentümer sie zurücklegt
        (`return_blocking_bins=True`) oder seine Verpflichtung verwirft
        (`False`, seit Phase 3B inklusive Ownership-Freigabe). Es entsteht
        Wartezeit, kein Deadlock.
        """
        robot = self._find_idle_robot(state)

        if robot is None:
            return None

        waiting_task_result = self._try_schedule_waiting_task(
            state=state,
            robot=robot,
            current_time=current_time,
        )

        if waiting_task_result is not None:
            return waiting_task_result

        if not self.active_queue.has_unassigned_requests():
            return None

        request = self._select_next_request(state)

        if request is None:
            return None

        task = RobotTask(request)

        robot.assign_task(task)
        self.active_queue.mark_assigned(request, robot)

        action = self.strategy.next_action(state, task)

        # NEU: Prüfen ob Bewegung erforderlich ist
        # Dies wird im EventHandler genauer behandelt, hier nur Metadaten sammeln
        return {
            "request": request,
            "robot": robot,
            "task": task,
            "action": action,
            "start_time": current_time,
            "requires_movement": self._action_requires_movement(action),
        }
    
    def _action_requires_movement(self, action):
        """Prüft ob Aktion Roboter-Bewegung erfordert."""
        if action is None:
            return False
        
        action_type = action.get("type")
        return action_type in ("relocate", "remove_target", "return")

    def _try_schedule_waiting_task(self, state, robot, current_time):
        if not self.active_queue.has_waiting_tasks():
            return None

        # Defensiv: veraltete/abgeschlossene Tasks aus der Waiting-Queue überspringen.
        # Kann auftreten, wenn alte Events einen Task noch einmal in waiting schieben,
        # obwohl er fachlich bereits abgeschlossen ist.
        task = None
        while self.active_queue.has_waiting_tasks():
            candidate = self.active_queue.pop_waiting_task()
            if candidate is None:
                break

            if getattr(candidate, "target_returned", False):
                continue

            if getattr(candidate, "phase", None) == RobotTask.PHASE_COMPLETE:
                continue

            task = candidate
            break

        if task is None:
            return None

        robot.assign_task(task)
        self.active_queue.mark_task_assigned(task, robot)

        action = self.strategy.next_action(state, task)

        if action is None:
            robot.clear_task()
            self.active_queue.add_waiting_task(task)
            return None

        return {
            "request": task.request,
            "robot": robot,
            "task": task,
            "action": action,
            "start_time": current_time,
        }

    def _try_schedule_opportunistic(self, state, robot, current_time):
        """
        Prüft, ob ein pending Request eine Target-Bin hat, die bereits oben
        auf ihrem Stack liegt und frei (nicht reserviert) ist.

        Falls ja: Dieser Request wird bevorzugt, weil kein Relocation-Aufwand entsteht.
        Spart Blocker-Räumen, wenn die Bin bereits zugänglich ist (R-E1).

        Erweitert um: Blocker-Bins, die im Buffer liegen und deren
        eigentlicher Owner sie zurücklegen müsste, können übernommen werden.
        """
        reserved = self.active_queue.get_all_reserved_bin_ids()

        for request in list(self.active_queue.pending):
            bin_id = request.target_box_id

            if bin_id in reserved:
                # Prüfen: Ist die Bin als Blocker reserviert und im Buffer zugänglich?
                owner_task = self.active_queue.get_blocker_owner(bin_id)
                if owner_task is not None:
                    # Opportunistischer Transfer: Request B übernimmt Blocker-Bin von Task A
                    bin_obj = state.get_bin_by_id(bin_id)
                    if bin_obj is not None:
                        stack = self._get_stack_for_bin(state, bin_obj)
                        if stack is not None:
                            top_bin = stack.peek()
                            if top_bin is not None and top_bin.bin_id == bin_id:
                                # Bin liegt oben im Buffer → Transfer durchführen
                                self.active_queue.pending.remove(request)
                                task = RobotTask(request)
                                robot.assign_task(task)
                                self.active_queue.mark_assigned(request, robot)

                                # Ownership-Transfer.
                                #
                                # PHASE 3B (P3-02, Absicherung): Die frühere
                                # Fassung rief `release_blocker_ownership()`
                                # ungeprüft und wertete den Rückgabewert aus.
                                # Die Methode liefert aber nie None – sie
                                # liefert den Eintrag oder wirft. Stand die
                                # Bin nicht mehr in `temp_storage`, brach die
                                # Simulation daher mit
                                # `RuntimeError: ... bin not found in
                                # temp_storage` ab.
                                #
                                # Hier gilt jetzt dasselbe Muster wie in
                                # `EventHandler._release_foreign_blocker_ownership`:
                                # erst prüfen, ob die Verpflichtung überhaupt
                                # noch offen ist, dann die globale Sperre
                                # in jedem Fall lösen.
                                still_open = any(
                                    reloc["bin_id"] == bin_id
                                    for reloc in owner_task.temp_storage
                                )
                                if still_open:
                                    owner_task.release_blocker_ownership(bin_id)

                                self.active_queue.release_blocker_ownership(bin_id)

                                action = self.strategy.next_action(state, task)
                                return {
                                    "request": request,
                                    "robot": robot,
                                    "task": task,
                                    "action": action,
                                    "start_time": current_time,
                                }
                continue

            # Normale opportunistische Bedienung: Bin liegt oben und ist frei
            bin_obj = state.get_bin_by_id(bin_id)
            if bin_obj is None:
                continue

            stack = self._get_stack_for_bin(state, bin_obj)
            if stack is None:
                continue

            top_bin = stack.peek()
            if top_bin is not None and top_bin.bin_id == bin_id:
                # Bin liegt bereits oben – opportunistisch vorziehen
                self.active_queue.pending.remove(request)
                task = RobotTask(request)
                robot.assign_task(task)
                self.active_queue.mark_assigned(request, robot)
                action = self.strategy.next_action(state, task)
                return {
                    "request": request,
                    "robot": robot,
                    "task": task,
                    "action": action,
                    "start_time": current_time,
                }

        return None

    def _get_accessible_bin_ids(self, state):
        """
        Gibt Bin-IDs zurück, die aktuell oben auf einem Stack liegen
        und keinen Eigentümer haben (also sofort bedienbar sind).
        """
        accessible = set()
        for stack in state.grid.all_stacks():
            top_bin = stack.peek()
            if top_bin is not None and not top_bin.in_transit:
                accessible.add(top_bin.bin_id)
        return accessible

    def _select_next_request(self, state):
        blocked_bin_ids = self.active_queue.get_all_reserved_bin_ids()

        if self.scheduler_strategy == "FIFO":
            return self._pop_next_fifo_excluding(blocked_bin_ids)

        if self.scheduler_strategy == "EDF":
            return self._pop_next_edf_excluding(blocked_bin_ids)

        raise ValueError(f"Unknown scheduler_strategy: {self.scheduler_strategy}")

    def _pop_next_fifo_excluding(self, blocked_bin_ids):
        """Erster nicht blockierter Request in Ankunftsreihenfolge."""
        for request in list(self.active_queue.pending):
            if request.target_box_id not in blocked_bin_ids:
                self.active_queue.pending.remove(request)
                return request

        return None

    def _pop_next_edf_excluding(self, blocked_bin_ids):
        candidates = [
            request
            for request in self.active_queue.pending
            if request.target_box_id not in blocked_bin_ids
        ]

        if not candidates:
            return None

        # Deterministischer Tie-Break (FREEZE-AUDIT):
        #     Deadline -> Ankunftszeit -> request_id
        #
        # Vorher entschied allein `min(..., key=latest_time)`; bei
        # Deadlinegleichstand gewann die Iterationsreihenfolge von `pending`.
        # Das war zwar faktisch stabil, aber nicht zugesichert. Bei konstantem
        # Slack D haben alle Requests desselben Ankunftszeitpunkts dieselbe
        # Deadline, der Fall tritt also regelmäßig auf.
        #
        # Bewusst KEIN Kriterium, das von Lagerposition, Digging-Tiefe,
        # ABC-Klasse oder Popularität abhängt – das wäre eine versteckte
        # Priorisierung.
        best_request = min(
            candidates,
            key=lambda request: (request.latest_time,
                                 request.arrival_time,
                                 request.request_id),
        )
        self.active_queue.pending.remove(best_request)
        return best_request

    def _find_idle_robot(self, state):
        for robot in state.robots:
            if robot.status == "idle":
                return robot

        return None

    def _get_task_priority(self, task):
        """
        Bestimmt Priorität eines Tasks für Queue-Scheduling.
        
        Wird verwendet für:
        - Pickstation-Queue (wenn PRIORITY-Strategie aktiv)
        - Deadlock-Resolution (später in Phase 5)
        
        Returns:
            int: Prioritätswert (niedriger = höhere Priorität)
        """
        from simulation.robot_task import RobotTask
        
        if task.phase == RobotTask.PHASE_RETRIEVE_TARGET:
            if task.target_removed:
                return self.PRIORITY_PICKSTATION_DELIVERY
            return self.PRIORITY_DIGGING
        
        if task.phase in (RobotTask.PHASE_RESTORE_BLOCKERS, RobotTask.PHASE_RETURN_TARGET):
            return self.PRIORITY_RETURN_STORAGE
        
        return self.PRIORITY_IDLE
    
    def _get_stack_for_bin(self, state, bin_obj):
        stack_id = bin_obj.get_stack()
        if stack_id is None:
            return None

        if isinstance(stack_id, tuple):
            x, y = stack_id
            return state.grid.get_stack(x, y)

        for stack in state.grid.all_stacks():
            if stack.stack_id == stack_id:
                return stack

        return None

    def _get_available_robot(self, state):
        """
        Findet einen idle Robot, der für neue Tasks verfügbar ist.

        Ein Robot ist verfügbar, wenn:
        - status == "idle"
        - current_task == None
        - NICHT auf einer Pickstation steht

        Returns:
            Robot oder None
        """
        for robot in state.robots:
            # Status muss idle sein
            if robot.status != "idle":
                continue

            # Kein aktiver Task
            if robot.current_task is not None:
                continue

            # ✅ Prüfe ob Robot auf Pickstation steht
            robot_pos = robot.get_position()
            if robot_pos is None:
                # Robot ohne Position → nicht verfügbar
                continue

            # Prüfe alle Pickstations
            on_pickstation = False
            for ps in state.pickstations:
                if robot_pos == ps.position:
                    on_pickstation = True
                    break

            if on_pickstation:
                # Robot steht auf Pickstation → nicht verfügbar
                continue

            # Robot ist verfügbar
            return robot

        return None