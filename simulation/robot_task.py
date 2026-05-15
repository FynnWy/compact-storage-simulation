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

    def __repr__(self):
        return (
            f"RobotTask("
            f"request_id={self.request_id}, "
            f"target_bin_id={self.target_bin_id}, "
            f"phase={self.phase}, "
            f"target_stack_id={self.target_stack_id}, "
            f"target_at_pickstation={self.target_at_pickstation}, "
            f"pickstation_completed={self.pickstation_completed}, "
            f"temp_storage={len(self.temp_storage)}"
            f")"
        )