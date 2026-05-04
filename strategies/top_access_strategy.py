from strategies.base_strategy import BaseStrategy


class TopAccessStrategy(BaseStrategy):

    def _create_plan(self, state, request):
        """
        Generates a plan to retrieve and return a bin using top access.

        Wichtig:
        Diese Methode verändert NICHT den echten State.
        Sie arbeitet nur auf lokalen Listen-Snapshots der betroffenen Stacks.

        Schritte:
        1. Finde Zielstack
        2. Plane Umlagerung blockierender Kisten
        3. Plane Entfernen der Zielkiste
        4. Plane Rücklagerung blockierender Kisten
        5. Plane Rücklagerung der Zielkiste
        6. request_complete wird automatisch von BaseStrategy angehängt
        """
        plan = []

        target_bin_id = request.target_box_id

        target_stack, target_level = self._find_bin(state, target_bin_id)

        if target_stack is None:
            raise ValueError(f"Bin {target_bin_id} not found")

        simulated_target_bins = list(target_stack.bins)
        simulated_buffers = {
            stack.stack_id: list(stack.bins)
            for stack in self._get_buffer_stacks(state, target_stack)
        }

        temp_storage = []

        while True:
            if not simulated_target_bins:
                raise RuntimeError("Target stack unexpectedly empty during planning")

            top_bin = simulated_target_bins[-1]

            if top_bin.bin_id == target_bin_id:
                break

            buffer_stack = self._select_buffer_stack(
                state=state,
                simulated_buffers=simulated_buffers,
            )

            plan.append({
                "type": "relocate",
                "from_stack": target_stack.stack_id,
                "to_stack": buffer_stack.stack_id,
                "bin_id": top_bin.bin_id,
            })

            simulated_target_bins.pop()
            simulated_buffers[buffer_stack.stack_id].append(top_bin)
            temp_storage.append((top_bin, buffer_stack))

        plan.append({
            "type": "remove_target",
            "from_stack": target_stack.stack_id,
            "bin_id": target_bin_id,
        })

        simulated_target_bins.pop()

        for bin_obj, buffer_stack in reversed(temp_storage):
            plan.append({
                "type": "return",
                "from_stack": buffer_stack.stack_id,
                "to_stack": target_stack.stack_id,
                "bin_id": bin_obj.bin_id,
            })

            simulated_buffers[buffer_stack.stack_id].pop()
            simulated_target_bins.append(bin_obj)

        plan.append({
            "type": "return",
            "from_stack": None,
            "to_stack": target_stack.stack_id,
            "bin_id": target_bin_id,
        })

        return plan

    # ----------------------------------
    # Helper Functions
    # ----------------------------------

    def _find_bin(self, state, bin_id):
        for stack in state.grid.all_stacks():
            for level, bin_obj in enumerate(stack.bins):
                if bin_obj.bin_id == bin_id:
                    return stack, level

        return None, None

    def _get_buffer_stacks(self, state, exclude_stack):
        return [stack for stack in state.grid.all_stacks() if stack != exclude_stack]

    def _select_buffer_stack(self, state, simulated_buffers):
        """
        Wählt den aktuell niedrigsten Buffer-Stack mit freier Kapazität.
        """
        max_stack_height = self._get_max_stack_height(state)

        candidate_stacks = []

        for stack in state.grid.all_stacks():
            if stack.stack_id not in simulated_buffers:
                continue

            simulated_height = len(simulated_buffers[stack.stack_id])

            if max_stack_height is not None and simulated_height >= max_stack_height:
                continue

            candidate_stacks.append(stack)

        if not candidate_stacks:
            raise RuntimeError("No buffer stack with free capacity available")

        return min(
            candidate_stacks,
            key=lambda stack: len(simulated_buffers[stack.stack_id]),
        )

    def _get_max_stack_height(self, state):
        config = getattr(state, "config", None)

        if config is None:
            raise RuntimeError("State has no config. Cannot determine max_stack_height.")

        max_stack_height = getattr(config, "max_stack_height", None)

        if max_stack_height is None:
            raise RuntimeError("Config has no max_stack_height.")

        return max_stack_height