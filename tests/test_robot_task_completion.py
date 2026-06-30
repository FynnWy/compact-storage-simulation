import types

from simulation.robot_task import RobotTask


class DummyBin:
    def __init__(self, bin_id, stack_pos=None):
        self.bin_id = bin_id
        self._stack_pos = stack_pos

    def get_stack(self):
        return self._stack_pos

    def set_stack(self, pos):
        self._stack_pos = pos


class DummyStack:
    def __init__(self, stack_id):
        self.stack_id = stack_id
        self.bins = []

    def peek(self):
        if not self.bins:
            return None
        return self.bins[-1]

    def height(self):
        return len(self.bins)

    def is_locked(self):
        return False


class DummyGrid:
    def __init__(self, stacks):
        self._stacks = {s.stack_id: s for s in stacks}

    def all_stacks(self):
        return list(self._stacks.values())

    def get_stack(self, x, y):
        # In diesen Tests benutzen wir stack_id direkt, nicht (x, y).
        # Diese Methode wird von RobotTask._get_stack_by_id nur für Tuple-IDs genutzt,
        # daher kann sie hier simpel bleiben.
        return None


class DummyState:
    def __init__(self, stacks, bins):
        self.grid = DummyGrid(stacks)
        self._bins = {b.bin_id: b for b in bins}

    def get_bin_by_id(self, bin_id):
        return self._bins.get(bin_id)


def _make_completed_task_on_stack(stack_id, target_bin_id=42):
    """
    Hilfsfunktion: Erzeugt einen RobotTask, der fachlich vollständig ist
    (alle Flags gesetzt) und dessen effektiver Rückgabe-Stack stack_id ist.
    """
    # Minimaler Request-Dummy mit target_box_id
    request = types.SimpleNamespace(
        request_id=0,
        target_box_id=target_bin_id,
    )
    task = RobotTask(request)
    task.target_stack_id = stack_id
    task.actual_return_stack_id = stack_id
    task.target_removed = True
    task.target_at_pickstation = True
    task.pickstation_completed = True
    task.target_returned = True
    task.temp_storage = []  # keine Blocker mehr
    return task


def test_can_complete_accepts_target_not_on_top():
    """
    Die Abschluss-Invariante darf NICHT verlangen, dass die Target-Bin
    ganz oben auf dem Rückgabestack liegt.

    Szenario:
    - Target-Bin liegt auf dem korrekten Rückgabe-Stack.
    - Eine andere Bin wurde später darüber gelegt.
    - Task ist ansonsten vollständig abgeschlossen.
    """
    stack_id = "S_1_1"
    stack = DummyStack(stack_id)

    target_bin = DummyBin(bin_id=42, stack_pos=(1, 1))
    other_bin = DummyBin(bin_id=99, stack_pos=(1, 1))

    # Reihenfolge im Stack: Target unten, andere Bin oben
    stack.bins = [target_bin, other_bin]

    state = DummyState(stacks=[stack], bins=[target_bin, other_bin])
    task = _make_completed_task_on_stack(stack_id=stack_id, target_bin_id=42)

    can_complete, reason = task.can_complete_consistently(state)

    assert can_complete is True, f"Task should be consistently completed, but got: {reason}"


def test_can_complete_requires_target_on_expected_stack():
    """
    Die Abschluss-Invariante MUSS verlangen, dass die Target-Bin
    auf dem erwarteten Rückgabe-Stack liegt.

    Szenario:
    - Target-Bin liegt auf einem anderen Stack als effective_stack_id.
    - Task ist ansonsten vollständig abgeschlossen.
    - Ergebnis: can_complete_consistently muss False liefern.
    """
    correct_stack_id = "S_1_1"
    wrong_stack_id = "S_2_2"

    correct_stack = DummyStack(correct_stack_id)
    wrong_stack = DummyStack(wrong_stack_id)

    target_bin = DummyBin(bin_id=42, stack_pos=(2, 2))
    wrong_stack.bins = [target_bin]

    state = DummyState(stacks=[correct_stack, wrong_stack], bins=[target_bin])
    task = _make_completed_task_on_stack(stack_id=correct_stack_id, target_bin_id=42)

    can_complete, reason = task.can_complete_consistently(state)

    assert can_complete is False
    assert "expected" in reason or "expected" in str(
        reason
    ), f"Reason should indicate wrong stack, got: {reason}"