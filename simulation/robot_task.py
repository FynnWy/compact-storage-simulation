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
    PHASE_RETURN_TARGET = "return_target"
    PHASE_COMPLETE = "complete"

    def __init__(self, request):
        self.request = request
        self.phase = self.PHASE_RETRIEVE_TARGET

        self.target_stack_id = None
        self.target_removed = False

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

    def __repr__(self):
        return (
            f"RobotTask("
            f"request_id={self.request_id}, "
            f"target_bin_id={self.target_bin_id}, "
            f"phase={self.phase}, "
            f"target_stack_id={self.target_stack_id}, "
            f"temp_storage={len(self.temp_storage)}"
            f")"
        )