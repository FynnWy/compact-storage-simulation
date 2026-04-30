from strategies.base_strategy import BaseStrategy


class TopAccessStrategy(BaseStrategy):

    def _create_plan(self, state, request):
        """
        Generates a plan to retrieve and return a bin using top access.

        Schritte:
        1. Finde Zielstack
        2. Entferne blockierende Kisten
        3. Entferne Zielkiste
        4. Lege blockierende Kisten zurück
        5. Lege Zielkiste zurück
        6. request_complete wird automatisch von BaseStrategy angehängt
        """
        plan = []

        target_bin_id = request.target_box_id

        # 1. finde Zielstack
        target_stack, target_pos = self._find_bin(state, target_bin_id)

        if target_stack is None:
            raise ValueError(f"Bin {target_bin_id} not found")

        buffer_stacks = self._get_buffer_stacks(state, target_stack)

        temp_storage = []

        # 2. entferne blockierende Kisten
        while True:
            top_bin = target_stack.peek()

            if top_bin is None:
                raise RuntimeError("Stack unexpectedly empty")

            if top_bin.bin_id == target_bin_id:
                break

            # Ziel ist noch blockiert → relocate
            buffer_stack = self._select_buffer_stack(buffer_stacks)

            plan.append({
                "type": "relocate",
                "from_stack": target_stack.stack_id,
                "to_stack": buffer_stack.stack_id,
                "bin_id": top_bin.bin_id
            })

            temp_storage.append((top_bin, buffer_stack))

            # virtuell ausführen (wichtig für Planung!)
            target_stack.pop()
            buffer_stack.push(top_bin)

        # 3. Zielkiste entfernen
        plan.append({
            "type": "remove_target",
            "from_stack": target_stack.stack_id,
            "bin_id": target_bin_id
        })

        target_bin = target_stack.pop()

        # 4. Blockierende Kisten zurücklegen (reverse order!)
        for bin_obj, buffer_stack in reversed(temp_storage):

            plan.append({
                "type": "return",
                "from_stack": buffer_stack.stack_id,
                "to_stack": target_stack.stack_id,
                "bin_id": bin_obj.bin_id
            })

            buffer_stack.pop()
            target_stack.push(bin_obj)

        # 5. Zielkiste zurücklegen
        plan.append({
            "type": "return",
            "from_stack": None,
            "to_stack": target_stack.stack_id,
            "bin_id": target_bin_id
        })

        target_stack.push(target_bin)

        return plan

    # ----------------------------------
    # Helper Functions
    # ----------------------------------

    def _find_bin(self, state, bin_id):
        for stack in state.grid.all_stacks():
            for bin_obj in stack.bins:
                if bin_obj.bin_id == bin_id:
                    return stack, bin_obj.stack_pos
        return None, None

    def _get_buffer_stacks(self, state, exclude_stack):
        return [s for s in state.grid.all_stacks() if s != exclude_stack]

    def _select_buffer_stack(self, buffer_stacks):
        # einfache Strategie: nimm ersten freien
        return buffer_stacks[0]