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
        Führt eine relocate-Aktion aus.
        Konkrete State-Update-Logik wird später ergänzt.
        """
        pass

    def _execute_remove_target(self, action, state):
        """
        Führt eine remove_target-Aktion aus.
        Konkrete State-Update-Logik wird später ergänzt.
        """
        pass

    def _execute_return(self, action, state):
        """
        Führt eine return-Aktion aus.
        Konkrete State-Update-Logik wird später ergänzt.
        """
        pass