from collections import deque


class ActiveQueue:
    def __init__(self):
        self.pending = deque()
        self.assigned = {}
        self.waiting_tasks = deque()
        self.pickstation_tasks = {}
        
        # Batching: Requests, die auf eine bereits reservierte Bin warten
        self._batch_waitlist = {}
        
        # Blocker-Ownership: bin_id → Task (für temp_storage-Reservierung)
        self._blocker_ownership = {}

    def add(self, request):
        """
        Fügt einen neu angekommenen Request hinzu.

        Falls die Ziel-Bin bereits aktiv reserviert ist, wird der Request direkt
        in die Batch-Warteliste eingetragen, statt als normaler pending Request.
        Dadurch kann nach Abschluss des aktiven Tasks gebatcht werden.
        """
        reserved = self.get_all_reserved_bin_ids()

        if request.target_box_id in reserved:
            bin_id = request.target_box_id
            if bin_id not in self._batch_waitlist:
                self._batch_waitlist[bin_id] = []
            self._batch_waitlist[bin_id].append(request)
        else:
            self.pending.append(request)

    def has_unassigned_requests(self):
        return len(self.pending) > 0

    def has_waiting_tasks(self):
        return len(self.waiting_tasks) > 0

    def add_waiting_task(self, task):
        """
        Merkt einen aktiven Task, der aktuell keinem Roboter zugewiesen ist,
        aber fachlich fortsetzbar ist.

        Invariante (FIX 2, 2026-08-19): Gegenstück zu `mark_task_assigned`.
        Ein Task, der wieder wartend wird, darf nicht weiterhin als zugewiesen
        gelten – sonst zeigt `assigned` auf einen Roboter, der den Task gar
        nicht mehr bearbeitet (u.a. nach Deadlock-Requeue und
        `[REQUEUE][PICKUP_POS]`).
        """
        self.assigned.pop(task.request_id, None)

        if task not in self.waiting_tasks:
            self.waiting_tasks.append(task)

    def add_pickstation_task(self, task):
        """
        Merkt einen aktiven Task, dessen Target-Bin gerade an der Pickstation
        bearbeitet wird.

        Der Task bleibt aktiv, ist aber noch nicht fortsetzbar.
        """
        self.assigned.pop(task.request_id, None)
        self.pickstation_tasks[task.request_id] = task

    def mark_pickstation_task_completed(self, task):
        """
        Macht einen Pickstation-Task nach Serviceende wieder fortsetzbar.
        """
        self.pickstation_tasks.pop(task.request_id, None)
        self.add_waiting_task(task)

    def pop_waiting_task(self):
        if not self.waiting_tasks:
            return None

        return self.waiting_tasks.popleft()

    def mark_assigned(self, request, robot):
        """
        Markiert einen Request als einem Roboter zugewiesen.
        """
        self.assigned[request.request_id] = {
            "request": request,
            "robot": robot,
        }

    def mark_task_assigned(self, task, robot):
        """
        Markiert einen bereits existierenden Task wieder als einem Roboter zugewiesen.

        Invariante (FIX 2, 2026-08-19):
        Ein Task darf nicht gleichzeitig als wartend (`waiting_tasks`) und als
        zugewiesen (`assigned`) gelten. Sonst bietet der nächste Scheduler-Lauf
        über `pop_waiting_task()` denselben Task einem zweiten Roboter an.

        `mark_task_assigned` ist der zentrale Zuweisungspfad für bereits
        existierende Tasks (Scheduler `_try_schedule_waiting_task` und
        EventHandler `_handle_pickstation_complete` über
        `assign_task_to_robot`). Die Bereinigung gehört daher hierher und
        nicht in die einzelnen Aufrufer.
        """
        self.pickstation_tasks.pop(task.request_id, None)

        # Task ist ab jetzt zugewiesen → darf nicht mehr wartend sein.
        self.remove_waiting_task(task)

        self.assigned[task.request_id] = {
            "request": task.request,
            "robot": robot,
        }

    def remove_waiting_task(self, task):
        """
        Entfernt einen Task aus `waiting_tasks` (idempotent).

        Vergleicht über `request_id`, damit auch ein logisch identischer, aber
        mehrfach eingetragener Task zuverlässig verschwindet.
        """
        if not self.waiting_tasks:
            return

        self.waiting_tasks = deque(
            waiting
            for waiting in self.waiting_tasks
            if waiting.request_id != task.request_id
        )

    def mark_completed(self, request):
        """
        Entfernt einen abgeschlossenen Request aus allen aktiven Verwaltungen
        und gibt Batch-Warteliste für dieselbe Bin frei.
        """
        self.assigned.pop(request.request_id, None)
        self.pickstation_tasks.pop(request.request_id, None)

        self.waiting_tasks = deque(
            task for task in self.waiting_tasks
            if task.request_id != request.request_id
        )

        # Batch-Warteliste: wartende Requests für dieselbe Bin jetzt freigeben
        bin_id = request.target_box_id
        if bin_id in self._batch_waitlist:
            for waiting_request in self._batch_waitlist.pop(bin_id):
                self.pending.append(waiting_request)

        # Blocker-Ownerships dieses Tasks freigeben.
        self._blocker_ownership = {
            bin_id: owning_task
            for bin_id, owning_task in self._blocker_ownership.items()
            if owning_task.request_id != request.request_id
        }

    # ------------------------------------------------------------------
    # Blocker-Ownership-Verwaltung
    # ------------------------------------------------------------------

    def register_blocker_ownership(self, bin_id, task):
        """
        Registriert, dass eine Blocker-Bin exklusiv zu diesem Task gehört.

        Wird aufgerufen, sobald eine Bin als Blocker in task.temp_storage landet.
        Damit ist sie für alle anderen Tasks gesperrt.
        """
        self._blocker_ownership[bin_id] = task

    def release_blocker_ownership(self, bin_id):
        """
        Gibt die Ownership einer blockierenden Bin auf (Ownership-Transfer, R-B3).

        Wird aufgerufen, wenn der übernehmende Task die Ownership aus task.temp_storage
        entfernt hat. Hier wird nur noch die globale Sperre aufgehoben.

        ✅ DEFENSIV: Wenn keine Ownership existiert, nur Warnung ausgeben.
        """
        if bin_id in self._blocker_ownership:
            self._blocker_ownership.pop(bin_id, None)
            return

        print(
            f"[WARNING] Cannot release blocker ownership for bin {bin_id}: "
            f"no owner registered in ActiveQueue (might be already released)"
        )

    def transfer_blocker_ownership(self, bin_id, from_task, to_task):
        """
        Überträgt die Ownership einer Blocker-Bin von einem Task auf einen anderen.

        Wird für opportunistischen Ownership-Transfer (Stufe 3) genutzt:
        Task B übernimmt Bin Y als Target, Task A muss sie nicht mehr zurücklegen.

        Invariante:
        from_task muss aktueller Eigentümer von bin_id sein.
        """
        current_owner = self._blocker_ownership.get(bin_id)

        if current_owner is None or current_owner.request_id != from_task.request_id:
            raise RuntimeError(
                f"Cannot transfer ownership of bin {bin_id}: "
                f"current owner is {current_owner}, expected task {from_task.request_id}"
            )

        self._blocker_ownership[bin_id] = to_task

    def get_blocker_owner(self, bin_id):
        """
        Gibt den Task zurück, der aktuell Eigentümer der Bin ist, oder None.
        """
        return self._blocker_ownership.get(bin_id)

    def is_bin_blocker_owned(self, bin_id):
        return bin_id in self._blocker_ownership

    def get_blocker_owned_bin_ids(self):
        """
        Nur die Bins mit AKTIVER Blocker-Ownership – ohne Target-Bins.

        Abgrenzung zu `get_all_reserved_bin_ids()`: dort geht es um die Frage
        „auf welche Bin darf kein NEUER Task starten", hier um die engere
        Frage „welche Bin muss ein laufender Task noch genau dort abholen, wo
        sie liegt". Nur diese Bins dürfen nicht verschüttet werden; eine
        Target-Bin wird beim Retrieval ohnehin freigegraben.

        Lesender Zugriff auf dieselbe Struktur, keine zweite Ownership-Quelle.
        """
        return frozenset(self._blocker_ownership.keys())

    def get_pending_restore_stack_ids(self):
        """
        Stacks, auf die ein laufender Task seine ausgelagerten Blocker noch
        zurücklegen wird (`from_stack` der offenen `temp_storage`-Einträge).

        Warum das gebraucht wird: Der Ordered Return legt Blocker per
        Definition auf ihren URSPRUNGSSTACK zurück – dieses Ziel ist Teil der
        untersuchten Strategie und darf nicht umgelenkt werden. Parkt ein
        FREMDER Task in der Zwischenzeit eine Bin auf genau diesem Stack, so
        verschüttet der spätere Ordered Return sie, und der fremde Task
        scheitert dauerhaft mit `expected bin X not on top`.

        Belegt im 7x7-Arbeitsfall: Roboter 3 parkt Blocker 124 bei t=1001 auf
        S_1_4; Roboter 0 legt bei t=1007..1078 vier eigene Blocker auf S_1_4
        zurück – das ist sein Originalstack. Danach kommt Roboter 3 nie mehr
        an seine Bin.

        Die Lösung liegt deshalb auf der PARK-Seite: nicht dort parken, wo ein
        anderer Task noch zurücklegen muss.

        Lesender Zugriff auf `_blocker_ownership`, keine zweite Struktur.
        """
        stacks = set()
        for task in set(self._blocker_ownership.values()):
            for eintrag in (getattr(task, "temp_storage", None) or []):
                if not isinstance(eintrag, dict):
                    continue
                ziel = eintrag.get("from_stack")
                if ziel is not None:
                    stacks.add(ziel)
        return frozenset(stacks)

    # ------------------------------------------------------------------
    # Hilfsmethode für EventHandler (Pickstation-Pickup)
    # ------------------------------------------------------------------

    def assign_task_to_robot(self, task, robot):
        """
        Backwards-kompatibler Wrapper:
        Weist einen bestehenden Task einem Robot zu.
        """
        self.mark_task_assigned(task, robot)

    # ------------------------------------------------------------------
    # Reservierungsabfragen (Stufe 1 – Kernlogik)
    # ------------------------------------------------------------------

    def get_all_reserved_bin_ids(self):
        """
        Gibt alle Bin-IDs zurück, auf die kein neuer Task starten darf.

        Enthält:
        - Target-Bins aller zugewiesenen Tasks (assigned)
        - Target-Bins aller wartenden Tasks (waiting_tasks)
        - Target-Bins aller Pickstation-Tasks (pickstation_tasks)
        - Alle Bins in temp_storage aller aktiven Tasks (blocker_ownership)

        Hinweis:
            Bins, die sich im Transport befinden (in_transit=True), werden
            NICHT hier gelistet, sondern separat durch den ConstraintManager
            über Bin.in_transit gegen parallele Zugriffe geschützt.

        Ersetzt get_assigned_target_bin_ids() vollständig.
        """
        reserved = set()

        for assignment in self.assigned.values():
            request = assignment["request"]
            reserved.add(request.target_box_id)

        for task in self.waiting_tasks:
            reserved.add(task.target_bin_id)

        for task in self.pickstation_tasks.values():
            reserved.add(task.target_bin_id)

        # Alle Bins, die aktuell als Blocker bei einem Task liegen.
        reserved.update(self._blocker_ownership.keys())

        return reserved

    def get_assigned_target_bin_ids(self):
        """
        Rückwärtskompatible Variante.
        Neue Logik sollte get_all_reserved_bin_ids() verwenden.
        """
        return self.get_all_reserved_bin_ids()

    # ------------------------------------------------------------------
    # Batching-Unterstützung (Stufe 4)
    # ------------------------------------------------------------------

    def get_pending_requests_for_bin(self, bin_id):
        """
        Gibt alle pending Requests zurück, die dieselbe Bin als Target haben.

        Wird für Pickstation-Batching genutzt: Bevor eine Bin zurückgelagert wird,
        können alle wartenden Requests für diese Bin gemeinsam bedient werden.
        """
        return [
            request
            for request in self.pending
            if request.target_box_id == bin_id
        ]

    def get_batch_waitlist_for_bin(self, bin_id):
        """
        Gibt alle wartenden Requests zurück, die auf dieselbe Bin warten (Batching).
        """
        return list(self._batch_waitlist.get(bin_id, []))

    def pop_batch_waitlist_for_bin(self, bin_id):
        """
        Gibt alle wartenden Batch-Requests zurück und entfernt sie aus der Warteliste.
        """
        return self._batch_waitlist.pop(bin_id, [])

    def has_batch_waitlist(self, bin_id):
        return bool(self._batch_waitlist.get(bin_id))

    def consume_pending_requests_for_bin(self, bin_id):
        """
        Entfernt alle pending Requests für eine bestimmte Bin aus der Queue
        und gibt sie zurück.

        Wird aufgerufen, wenn eine Bin an der Pickstation gebatcht wird.
        """
        batched = [
            request
            for request in self.pending
            if request.target_box_id == bin_id
        ]

        self.pending = deque(
            request
            for request in self.pending
            if request.target_box_id != bin_id
        )

        return batched

    # ------------------------------------------------------------------
    # Zustandsabfragen
    # ------------------------------------------------------------------

    def is_empty(self):
        return (
            len(self.pending) == 0
            and len(self.assigned) == 0
            and len(self.waiting_tasks) == 0
            and len(self.pickstation_tasks) == 0
        )

    def __len__(self):
        return (
            len(self.pending)
            + len(self.assigned)
            + len(self.waiting_tasks)
            + len(self.pickstation_tasks)
        )

    def __repr__(self):
        blocker_count = len(getattr(self, '_blocker_ownership', {}))
        batch_count = sum(len(v) for v in self._batch_waitlist.values())

        return (
            f"ActiveQueue("
            f"pending={len(self.pending)}, "
            f"assigned={len(self.assigned)}, "
            f"waiting_tasks={len(self.waiting_tasks)}, "
            f"pickstation_tasks={len(self.pickstation_tasks)}, "
            f"batch_waitlist={batch_count}, "
            f"blocker_owned={blocker_count})"
        )