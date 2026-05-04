class ActionExecutor:
    def execute(self, event, state):
        action = self._get_action_from_event(event)
        action_type = action.get("type")

        if action_type == "relocate":
            self._execute_relocate(action, state)

        elif action_type == "remove_target":
            self._execute_remove_target(action, state)

        elif action_type == "return":
            self._execute_return(action, state)

        else:
            raise ValueError(f"Unknown action type: {action_type}")

    def _get_action_from_event(self, event):
        if isinstance(event.payload, dict) and "action" in event.payload:
            return event.payload["action"]

        if isinstance(event.payload, dict):
            return event.payload

        raise ValueError(f"ROBOT_ACTION event has invalid payload: {event.payload}")

    def _execute_relocate(self, action, state):
        """
        Bewegt eine blockierende Bin von einem Stack auf einen Buffer-Stack.
        """
        from_stack = self._get_stack_by_id(state, action.get("from_stack"))
        to_stack = self._get_stack_by_id(state, action.get("to_stack"))
        bin_id = action.get("bin_id")

        self._require_stack(from_stack, action.get("from_stack"))
        self._require_stack(to_stack, action.get("to_stack"))

        bin_obj = from_stack.pop()
        self._require_expected_bin(bin_obj, bin_id, "relocate")

        to_stack.push(bin_obj)
        self._sync_stack_bin_metadata(to_stack)

    def _execute_remove_target(self, action, state):
        """
        Entfernt die Ziel-Bin aus ihrem Stack.
        Die Bin befindet sich danach virtuell an der Pickstation.
        """
        from_stack = self._get_stack_by_id(state, action.get("from_stack"))
        bin_id = action.get("bin_id")

        self._require_stack(from_stack, action.get("from_stack"))

        bin_obj = from_stack.pop()
        self._require_expected_bin(bin_obj, bin_id, "remove_target")

        bin_obj.set_stack(None)
        bin_obj.set_level(None)
        bin_obj.set_status("at_pickstation")

        self._sync_stack_bin_metadata(from_stack)

    def _execute_return(self, action, state):
        """
        Legt eine Bin zurück:
        - entweder von einem Buffer-Stack
        - oder von der Pickstation, wenn from_stack == None
        """
        from_stack_id = action.get("from_stack")
        to_stack = self._get_stack_by_id(state, action.get("to_stack"))
        bin_id = action.get("bin_id")

        self._require_stack(to_stack, action.get("to_stack"))

        if from_stack_id is None:
            bin_obj = state.get_bin_by_id(bin_id)
            if bin_obj is None:
                raise ValueError(f"Cannot return unknown bin_id={bin_id} from pickstation")

            if bin_obj.get_status() != "at_pickstation":
                raise RuntimeError(
                    f"Cannot return bin_id={bin_id} from pickstation: "
                    f"bin status is {bin_obj.get_status()}"
                )

            if bin_obj.get_stack() is not None:
                raise RuntimeError(
                    f"Cannot return bin_id={bin_id} from pickstation: "
                    f"bin is already assigned to stack {bin_obj.get_stack()}"
                )

        else:
            from_stack = self._get_stack_by_id(state, from_stack_id)
            self._require_stack(from_stack, from_stack_id)

            bin_obj = from_stack.pop()
            self._require_expected_bin(bin_obj, bin_id, "return")

            self._sync_stack_bin_metadata(from_stack)

        to_stack.push(bin_obj)
        self._sync_stack_bin_metadata(to_stack)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_stack_by_id(self, state, stack_id):
        """
        Unterstützt beide Stack-ID-Formen:
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

    def _require_stack(self, stack, stack_id):
        if stack is None:
            raise ValueError(f"Stack not found: {stack_id}")

    def _require_expected_bin(self, bin_obj, expected_bin_id, action_type):
        if bin_obj is None:
            raise RuntimeError(f"Cannot execute {action_type}: source stack is empty")

        if bin_obj.bin_id != expected_bin_id:
            raise RuntimeError(
                f"Cannot execute {action_type}: expected bin_id={expected_bin_id}, "
                f"but got bin_id={bin_obj.bin_id}"
            )

    def _sync_stack_bin_metadata(self, stack):
        """
        Synchronisiert alle Bin-Objekte in einem Stack nach einer Veränderung.

        Dadurch bleiben:
        - bin.stack_id
        - bin.stack_level
        - bin.status

        konsistent mit der tatsächlichen Stack-Liste.
        """
        stack_position = self._parse_stack_position(stack)

        for level, bin_obj in enumerate(stack.bins):
            bin_obj.set_stack(stack_position)
            bin_obj.set_level(level)
            bin_obj.set_status("stored")

    def _parse_stack_position(self, stack):
        """
        Wandelt 'S_x_y' zurück in (x, y), damit Bin.stack_id konsistent bleibt.
        Falls ein anderes Format auftaucht, wird stack.stack_id direkt verwendet.
        """
        stack_id = stack.stack_id

        if isinstance(stack_id, tuple):
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")

            if len(parts) == 3:
                return int(parts[1]), int(parts[2])

        return stack_id