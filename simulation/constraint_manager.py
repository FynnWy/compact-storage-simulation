class ConstraintManager:
    """
    Prüft, ob geplante Aktionen im aktuellen State zulässig sind.

    Wichtig:
    - Ob ein Roboter frei ist, wird absichtlich NICHT hier geprüft.
      Das ist Aufgabe des Schedulers.
    - request_complete wird hier ebenfalls NICHT geprüft.
      Completion-Events werden direkt im EventHandler verarbeitet.
    - Dieser Manager prüft nur physische/strukturelle Lager-Constraints.
    """

    PHYSICAL_ACTIONS = {"relocate", "remove_target", "return"}
    KNOWN_ACTIONS = PHYSICAL_ACTIONS

    def can_execute(self, action, state):
        can_execute, _ = self.can_execute_with_reason(action, state)
        return can_execute

    def can_execute_with_reason(self, action, state):
        """
        Gibt (can_execute, reason) zurück.

        reason ist besonders für Debugging wichtig, um hohe retry_count-Werte
        nachvollziehen zu können.
        """
        self._validate_basic_action(action)

        action_type = action.get("type")

        if action_type == "relocate":
            return self._can_relocate_with_reason(action, state)

        if action_type == "remove_target":
            return self._can_remove_target_with_reason(action, state)

        if action_type == "return":
            return self._can_return_with_reason(action, state)

        raise ValueError(f"Unknown physical action type: {action_type}")

    # ------------------------------------------------------------------
    # Action-specific checks
    # ------------------------------------------------------------------

    def _can_relocate_with_reason(self, action, state):
        from_stack = self._get_stack_by_id(state, action.get("from_stack"))
        to_stack = self._get_stack_by_id(state, action.get("to_stack"))
        bin_id = action.get("bin_id")

        if from_stack is None:
            return False, f"relocate blocked: from_stack not found ({action.get('from_stack')})"

        if to_stack is None:
            return False, f"relocate blocked: to_stack not found ({action.get('to_stack')})"

        if from_stack == to_stack:
            return False, "relocate blocked: from_stack equals to_stack"

        if self._is_stack_locked(from_stack):
            return False, f"relocate blocked: from_stack {from_stack.stack_id} is locked"

        if self._is_stack_locked(to_stack):
            return False, f"relocate blocked: to_stack {to_stack.stack_id} is locked"

        if not self._is_expected_bin_on_top(from_stack, bin_id):
            top_bin = from_stack.peek()
            top_bin_id = top_bin.bin_id if top_bin is not None else None
            return (
                False,
                f"relocate blocked: expected bin {bin_id} on top of {from_stack.stack_id}, "
                f"but top is {top_bin_id}"
            )

        if not self._has_capacity(to_stack, state):
            return False, f"relocate blocked: to_stack {to_stack.stack_id} has no capacity"

        return True, "relocate allowed"

    def _can_remove_target_with_reason(self, action, state):
        from_stack = self._get_stack_by_id(state, action.get("from_stack"))
        bin_id = action.get("bin_id")

        if from_stack is None:
            return False, f"remove_target blocked: from_stack not found ({action.get('from_stack')})"

        if self._is_stack_locked(from_stack):
            return False, f"remove_target blocked: from_stack {from_stack.stack_id} is locked"

        if not self._is_expected_bin_on_top(from_stack, bin_id):
            top_bin = from_stack.peek()
            top_bin_id = top_bin.bin_id if top_bin is not None else None
            return (
                False,
                f"remove_target blocked: expected target bin {bin_id} on top of "
                f"{from_stack.stack_id}, but top is {top_bin_id}"
            )

        bin_obj = state.get_bin_by_id(bin_id)
        if bin_obj is None:
            return False, f"remove_target blocked: bin {bin_id} does not exist"

        return True, "remove_target allowed"

    def _can_return_with_reason(self, action, state):
        to_stack = self._get_stack_by_id(state, action.get("to_stack"))
        from_stack_id = action.get("from_stack")
        bin_id = action.get("bin_id")

        if to_stack is None:
            return False, f"return blocked: to_stack not found ({action.get('to_stack')})"

        if self._is_stack_locked(to_stack):
            return False, f"return blocked: to_stack {to_stack.stack_id} is locked"

        if not self._has_capacity(to_stack, state):
            return False, f"return blocked: to_stack {to_stack.stack_id} has no capacity"

        bin_obj = state.get_bin_by_id(bin_id)
        if bin_obj is None:
            return False, f"return blocked: bin {bin_id} does not exist"

        # Rückgabe von der Pickstation.
        if from_stack_id is None:
            if bin_obj.get_status() != "at_pickstation":
                return (
                    False,
                    f"return blocked: bin {bin_id} is not at pickstation "
                    f"(status={bin_obj.get_status()})"
                )

            if bin_obj.get_stack() is not None:
                return (
                    False,
                    f"return blocked: bin {bin_id} already assigned to stack "
                    f"{bin_obj.get_stack()}"
                )

            if bin_obj.get_level() is not None:
                return (
                    False,
                    f"return blocked: bin {bin_id} still has level {bin_obj.get_level()}"
                )

            return True, "return from pickstation allowed"

        # Rückgabe aus einem Buffer-Stack.
        from_stack = self._get_stack_by_id(state, from_stack_id)

        if from_stack is None:
            return False, f"return blocked: from_stack not found ({from_stack_id})"

        if from_stack == to_stack:
            return False, "return blocked: from_stack equals to_stack"

        if self._is_stack_locked(from_stack):
            return False, f"return blocked: from_stack {from_stack.stack_id} is locked"

        if not self._is_expected_bin_on_top(from_stack, bin_id):
            top_bin = from_stack.peek()
            top_bin_id = top_bin.bin_id if top_bin is not None else None
            return (
                False,
                f"return blocked: expected bin {bin_id} on top of {from_stack.stack_id}, "
                f"but top is {top_bin_id}"
            )

        return True, "return from buffer allowed"

    # ------------------------------------------------------------------
    # Backwards-compatible wrappers
    # ------------------------------------------------------------------

    def _can_relocate(self, action, state):
        can_execute, _ = self._can_relocate_with_reason(action, state)
        return can_execute

    def _can_remove_target(self, action, state):
        can_execute, _ = self._can_remove_target_with_reason(action, state)
        return can_execute

    def _can_return(self, action, state):
        can_execute, _ = self._can_return_with_reason(action, state)
        return can_execute

    # ------------------------------------------------------------------
    # Generic validation
    # ------------------------------------------------------------------

    def _validate_basic_action(self, action):
        if not isinstance(action, dict):
            raise ValueError(f"Action must be a dict, got: {type(action)}")

        action_type = action.get("type")

        if action_type is None:
            raise ValueError(f"Action has no type: {action}")

        if action_type not in self.KNOWN_ACTIONS:
            raise ValueError(f"Unknown physical action type: {action_type}")

        if action.get("bin_id") is None:
            raise ValueError(f"Physical action has no bin_id: {action}")

    # ------------------------------------------------------------------
    # Stack/bin helpers
    # ------------------------------------------------------------------

    def _get_stack_by_id(self, state, stack_id):
        """
        Unterstützt beide aktuell möglichen Stack-ID-Formen:
        - Tuple: (x, y)
        - String: 'S_x_y'
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

    def _is_expected_bin_on_top(self, stack, bin_id):
        top_bin = stack.peek()

        if top_bin is None:
            return False

        return top_bin.bin_id == bin_id

    def _is_stack_locked(self, stack):
        return stack.is_locked()

    def _has_capacity(self, stack, state):
        max_stack_height = self._get_max_stack_height(state)

        if max_stack_height is None:
            return True

        return stack.height() < max_stack_height

    def _get_max_stack_height(self, state):
        """
        Kapazität wird defensiv gesucht.

        Unterstützte Varianten:
        - state.max_stack_height
        - state.config.max_stack_height
        - state.config.stack_height
        - state.config.stack_capacity
        """
        if hasattr(state, "max_stack_height"):
            return state.max_stack_height

        config = getattr(state, "config", None)

        if config is None:
            return None

        for attr_name in ("max_stack_height", "stack_height", "stack_capacity"):
            if hasattr(config, attr_name):
                return getattr(config, attr_name)

        return None