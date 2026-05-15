class RobotTask:
    """
    Hält den fachlichen Fortschritt eines aktiven Requests.

    Wichtig:
    Die Strategie darf immer nur die nächste Aktion planen.
    Dafür muss sie wissen, was für diesen Request bereits passiert ist:
    - ursprünglicher Zielstack
    - ausgelagerte blockierende Bins
    - aktuelle Phase
    """

    PHASE_RETRIEVE_TARGET = "retrieve_target"
    PHASE_RESTORE_BLOCKERS = "restore_blockers"
    PHASE_WAIT_FOR_PICKSTATION = "wait_for_pickstation"
    PHASE_RETURN_TARGET = "return_target"
    PHASE_COMPLETE = "complete"

    def __init__(self, request):
        self.request = request
        self.phase = self.PHASE_RETRIEVE_TARGET

        self.target_stack_id = None
        self.target_removed = False
        self.target_at_pickstation = False
        self.pickstation_completed = False
        self.target_returned = False

        # LIFO: zuletzt ausgelagerte Bin wird zuerst zurückgelegt.
        self.temp_storage = []

    @property
    def request_id(self):
        return self.request.request_id

    @property
    def target_bin_id(self):
        return self.request.target_box_id

    def remember_relocation(self, bin_id, from_stack, buffer_stack):
        self.temp_storage.append({
            "bin_id": bin_id,
            "from_stack": from_stack,
            "buffer_stack": buffer_stack,
        })

    def peek_last_relocation(self):
        """
        Gibt die nächste zurückzulagernde Relocation zurück, ohne sie zu entfernen.

        Wichtig:
        Die Strategie darf beim Planen keine Task-Information verlieren.
        Entfernt wird der Eintrag erst nach erfolgreicher Ausführung der Return-Action.
        """
        if not self.temp_storage:
            return None

        return self.temp_storage[-1]

    def mark_last_relocation_restored(self, bin_id, from_stack, to_stack):
        """
        Markiert genau die zuletzt ausgelagerte Bin als erfolgreich zurückgelagert.

        Diese Methode darf erst nach erfolgreicher physischer Return-Action aufgerufen werden.
        """
        relocation = self.peek_last_relocation()

        if relocation is None:
            raise RuntimeError(
                f"Cannot mark relocation restored for bin {bin_id}: "
                f"task {self.request_id} has no open relocations"
            )

        if relocation["bin_id"] != bin_id:
            raise RuntimeError(
                f"Cannot mark relocation restored for task {self.request_id}: "
                f"expected bin {relocation['bin_id']}, got {bin_id}"
            )

        if relocation["buffer_stack"] != from_stack:
            raise RuntimeError(
                f"Cannot mark relocation restored for bin {bin_id}: "
                f"expected from_stack {relocation['buffer_stack']}, got {from_stack}"
            )

        if relocation["from_stack"] != to_stack:
            raise RuntimeError(
                f"Cannot mark relocation restored for bin {bin_id}: "
                f"expected to_stack {relocation['from_stack']}, got {to_stack}"
            )

        self.temp_storage.pop()

    def pop_last_relocation(self):
        if not self.temp_storage:
            return None

        return self.temp_storage.pop()

    def has_blockers_to_restore(self):
        return len(self.temp_storage) > 0

    def mark_target_at_pickstation(self):
        self.mark_waiting_at_pickstation()

    def mark_waiting_at_pickstation(self):
        """
        Variante B:
        Die Target-Bin ist an der Pickstation angekommen.
        Der Roboter darf entkoppelt werden, der Task bleibt aber aktiv
        und wartet auf das Ende der Pickstation-Bearbeitung.

        Wichtig:
        Während dieser Phase darf der Task noch nicht fortgesetzt werden.
        """
        self.target_removed = True
        self.target_at_pickstation = True
        self.phase = self.PHASE_WAIT_FOR_PICKSTATION

    def mark_pickstation_completed(self):
        """
        Die Pickstation-Bearbeitung ist abgeschlossen.

        Danach wird nicht direkt die Target-Bin zurückgelegt.
        Zuerst müssen eventuell ausgelagerte blockierende Bins zurück.
        """
        self.pickstation_completed = True

        if self.phase == self.PHASE_WAIT_FOR_PICKSTATION:
            self.phase = self.PHASE_RESTORE_BLOCKERS

    def mark_target_returned(self):
        self.target_returned = True
        self.phase = self.PHASE_COMPLETE

    def can_complete_consistently(self, state):
        """
        Prüft die formale Abschlussinvariante eines Requests.

        Ein Request ist nur vollständig abgeschlossen, wenn:
        - die Target-Bin entnommen wurde,
        - die Target-Bin an der Pickstation war,
        - die Pickstation-Bearbeitung abgeschlossen ist,
        - alle blockierenden Bins zurückgelagert wurden,
        - die Target-Bin zurückgelagert wurde,
        - die Target-Bin oben auf dem ursprünglichen Zielstack liegt.
        """
        if self.target_stack_id is None:
            return False, "target_stack_id is unknown"

        if not self.target_removed:
            return False, "target was not removed"

        if not self.target_at_pickstation:
            return False, "target was not at pickstation"

        if not self.pickstation_completed:
            return False, "pickstation service is not completed"

        if self.has_blockers_to_restore():
            return False, "there are still blockers to restore"

        if not self.target_returned:
            return False, "target was not returned"

        target_stack = self._get_stack_by_id(state, self.target_stack_id)

        if target_stack is None:
            return False, f"target stack {self.target_stack_id} does not exist"

        top_bin = target_stack.peek()

        if top_bin is None:
            return False, f"target stack {self.target_stack_id} is empty"

        if top_bin.bin_id != self.target_bin_id:
            return (
                False,
                f"target bin {self.target_bin_id} is not on top of "
                f"target stack {self.target_stack_id}; top is {top_bin.bin_id}"
            )

        return True, "task is consistently completed"

    def require_consistently_completed(self, state):
        can_complete, reason = self.can_complete_consistently(state)

        if not can_complete:
            raise RuntimeError(
                f"Cannot complete request {self.request_id}: {reason}"
            )

    def _get_stack_by_id(self, state, stack_id):
        if stack_id is None:
            return None

        if isinstance(stack_id, tuple):
            x, y = stack_id
            return state.grid.get_stack(x, y)

        for stack in state.grid.all_stacks():
            if stack.stack_id == stack_id:
                return stack

        return None

    def __repr__(self):
        return (
            f"RobotTask("
            f"request_id={self.request_id}, "
            f"target_bin_id={self.target_bin_id}, "
            f"phase={self.phase}, "
            f"target_stack_id={self.target_stack_id}, "
            f"target_at_pickstation={self.target_at_pickstation}, "
            f"pickstation_completed={self.pickstation_completed}, "
            f"target_returned={self.target_returned}, "
            f"temp_storage={len(self.temp_storage)}"
            f")"
        )