import numpy as np


class ActionCostModel:
    """
    Berechnet realistische Aktionsdauern.

    Das Kostenmodell verändert keinen State.
    Es entscheidet nicht, welche Aktion ausgeführt wird.
    Es berechnet ausschließlich Zeitkosten.
    """

    def __init__(self, config, rng):
        self.config = config
        self.rng = rng

    def action_duration(self, action, state, robot):
        action_type = action.get("type")

        if action_type == "relocate":
            return self._relocate_duration(action, state, robot)

        if action_type == "remove_target":
            return self._remove_target_duration(action, state, robot)

        if action_type == "return":
            return self._return_duration(action, state, robot)

        if action_type == "request_complete":
            return 0

        raise ValueError(f"Unknown action type for duration calculation: {action_type}")

    def pickstation_service_duration(self):
        """
        Gibt Basis-Servicezeit für EINE Bin an der Pickstation zurück.
        
        Bei Batching wird dieser Wert mit der Batch-Größe multipliziert.
        """
        minimum = self.config.pickstation_service_time_min
        maximum = self.config.pickstation_service_time_max

        if minimum > maximum:
            raise ValueError(
                f"Invalid pickstation service time: min={minimum}, max={maximum}"
            )

        return int(self.rng.integers(minimum, maximum + 1))

    def final_robot_position(self, action):
        """
        Gibt zurück, wo der Roboter nach erfolgreicher Aktion steht.
        """
        action_type = action.get("type")

        if action_type == "relocate":
            return self._resolve_position(action.get("to_stack"))

        if action_type == "remove_target":
            return self._pickstation_position()

        if action_type == "return":
            return self._resolve_position(action.get("to_stack"))

        return None

    def _relocate_duration(self, action, state, robot):
        from_position = self._resolve_position(action.get("from_stack"))
        to_position = self._resolve_position(action.get("to_stack"))

        return (
                self._travel_from_robot_to(robot, from_position)
                + self._arm_cost_for_source_stack(action, state)
                + self._grip_cost()
                + self._travel_between(from_position, to_position)
                + self._drop_cost()
        )

    def _remove_target_duration(self, action, state, robot):
        """
        Bedeutet fachlich:
        - Roboter fährt zum Target-Stack
        - Arm fährt runter
        - Target-Bin wird gegriffen
        - Arm fährt hoch
        - Roboter fährt mit Target-Bin zur Pickstation
        - Bin wird an der Pickstation abgegeben
        """
        from_position = self._resolve_position(action.get("from_stack"))
        pickstation_position = self._pickstation_position()

        return (
                self._travel_from_robot_to(robot, from_position)
                + self._arm_cost_for_source_stack(action, state)
                + self._grip_cost()
                + self._travel_between(from_position, pickstation_position)
                + self._drop_cost()
        )

    def _return_duration(self, action, state, robot):
        from_stack_id = action.get("from_stack")
        to_position = self._resolve_position(action.get("to_stack"))

        if from_stack_id is None:
            from_position = self._pickstation_position()
            arm_cost = self._arm_cost_for_target_stack(action, state)
        else:
            from_position = self._resolve_position(from_stack_id)
            arm_cost = self._arm_cost_for_source_stack(action, state)

        return (
                self._travel_from_robot_to(robot, from_position)
                + self._grip_cost()
                + self._travel_between(from_position, to_position)
                + arm_cost
                + self._drop_cost()
        )

    def _travel_from_robot_to(self, robot, target_position):
        if robot is None:
            return 0

        robot_position = robot.get_position()

        if robot_position is None:
            return 0

        return self._travel_between(robot_position, target_position)

    def _travel_between(self, from_position, to_position):
        if from_position is None or to_position is None:
            return 0

        distance = (
                abs(from_position[0] - to_position[0])
                + abs(from_position[1] - to_position[1])
        )

        return distance * self.config.move_cost_per_grid_step

    def _arm_cost_for_source_stack(self, action, state):
        stack = self._get_stack_by_id(state, action.get("from_stack"))

        if stack is None:
            return 0

        access_depth = max(0, stack.height() - 1)
        return self._arm_roundtrip_cost(access_depth)

    def _arm_cost_for_target_stack(self, action, state):
        stack = self._get_stack_by_id(state, action.get("to_stack"))

        if stack is None:
            return 0

        access_depth = max(0, stack.height())
        return self._arm_roundtrip_cost(access_depth)

    def _arm_roundtrip_cost(self, depth):
        return 2 * depth * self.config.arm_move_cost_per_level

    def _grip_cost(self):
        return self.config.grip_cost

    def _drop_cost(self):
        return self.config.drop_cost

    def _pickstation_position(self):
        """
        Gibt Pickstation-Position zurück.
        
        Neu: Nutzt erste verfügbare Pickstation aus State, falls vorhanden.
        Fallback: Config-Position (Backward-Compatibility).
        """
        # Versuche Pickstation aus State zu holen
        state = getattr(self, '_cached_state', None)
        if state is not None and hasattr(state, 'pickstations') and state.pickstations:
            # Nutze erste Pickstation als Default
            return state.pickstations[0].position
        
        # Fallback auf Config
        return self.config.pickstation_position
    
    def calculate_path(self, from_position, to_position, robot=None, state=None, current_time=0):
        """
        Berechnet Pfad zwischen zwei Positionen.
        
        NEU: Nutzt TrafficManager falls vorhanden, sonst einfacher Manhattan-Pfad.
        
        Args:
            from_position: (x, y) Startposition
            to_position: (x, y) Zielposition
            robot: Optional - Robot-Instanz (für TrafficManager)
            state: Optional - State-Instanz (für TrafficManager)
            current_time: Optional - Aktueller Zeitpunkt
        
        Returns:
            list[(x, y)]: Liste von Wegpunkten (ohne Start)
        """
        if from_position is None or to_position is None:
            return []
        
        if from_position == to_position:
            return []
        
        # NEU: Nutze TrafficManager falls vorhanden
        if (state is not None and 
            hasattr(state, 'traffic_manager') and 
            state.traffic_manager is not None and
            robot is not None):
            
            path = state.traffic_manager.request_path(
                robot=robot,
                target=to_position,
                current_time=current_time,
            )
            
            if path is not None:
                return path
            
            # Fallback auf einfachen Pfad falls TrafficManager fehlschlägt
            print(f"[WARNING] TrafficManager failed for robot {robot.robot_id}, using simple path")
        
        # Fallback: Einfacher Manhattan-Pfad
        path = [from_position]
        current_x, current_y = from_position
        target_x, target_y = to_position
        
        # Erst horizontal bewegen
        while current_x != target_x:
            if current_x < target_x:
                current_x += 1
            else:
                current_x -= 1
            path.append((current_x, current_y))
        
        # Dann vertikal bewegen
        while current_y != target_y:
            if current_y < target_y:
                current_y += 1
            else:
                current_y -= 1
            path.append((current_x, current_y))
        
        # Startposition nicht im Pfad
        return path[1:]

        return (
                self._travel_from_robot_to(robot, from_position)
                + self._arm_cost_for_source_stack(action, state)
                + self._grip_cost()
                + self._travel_between(from_position, pickstation_position)
                + self._drop_cost()
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

    def _resolve_position(self, stack_id):
        if stack_id is None:
            return None

        if isinstance(stack_id, tuple):
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")

            if len(parts) == 3:
                return int(parts[1]), int(parts[2])

        raise ValueError(f"Cannot resolve position from stack_id={stack_id}")