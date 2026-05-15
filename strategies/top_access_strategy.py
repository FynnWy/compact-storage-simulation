from strategies.base_strategy import BaseStrategy
from simulation.robot_task import RobotTask
from strategies.relocation_selection import RelocationSelection



class TopAccessStrategy(BaseStrategy):
    def __init__(self, relocation_selector=None):
        """
        Top-Access-Strategie mit Next-Step-Planning.

        Args:
            relocation_selector:
                Optionale externe Instanz von RelocationSelection.
                Falls None, wird eine Standardinstanz verwendet.
        """
        super().__init__()
        self._relocation_selector = relocation_selector or RelocationSelection()

    def next_action(self, state, task):
        """
        Plant genau die nächste fachlich sinnvolle Aktion für einen aktiven Task.

        Wichtig:
        - Diese Methode verändert nicht den Lager-State.
        - Sie erzeugt keine Events.
        - Sie schreibt keine Metriken.
        - Sie entscheidet nur, welche einzelne Action als Nächstes sinnvoll ist.
        """
        if task.phase == RobotTask.PHASE_RETRIEVE_TARGET:
            return self._next_retrieve_target_action(state, task)

        if task.phase == RobotTask.PHASE_RESTORE_BLOCKERS:
            return self._next_restore_blockers_action(state, task)

        if task.phase == RobotTask.PHASE_WAIT_FOR_PICKSTATION:
            return self._next_wait_for_pickstation_action(task)

        if task.phase == RobotTask.PHASE_RETURN_TARGET:
            # BUGFIX: state muss übergeben werden, da _next_return_target_action(state, task) erwartet.
            return self._next_return_target_action(state, task)

        if task.phase == RobotTask.PHASE_COMPLETE:
            return self._next_complete_action(task)

        raise ValueError(f"Unknown task phase: {task.phase}")

    def _next_retrieve_target_action(self, state, task):
        target_bin_id = task.target_bin_id
        target_stack, target_level = self._find_bin(state, target_bin_id)

        if target_stack is None:
            target_bin = state.get_bin_by_id(target_bin_id)

            if target_bin is not None and target_bin.get_status() == "at_pickstation":
                task.target_at_pickstation = True
                task.phase = RobotTask.PHASE_RESTORE_BLOCKERS
                return self.next_action(state, task)

            raise RuntimeError(f"Target bin {target_bin_id} not found in storage or pickstation")

        if task.target_stack_id is None:
            task.target_stack_id = target_stack.stack_id

        top_bin = target_stack.peek()

        if top_bin is None:
            raise RuntimeError(
                f"Target stack {target_stack.stack_id} unexpectedly empty "
                f"while retrieving bin {target_bin_id}"
            )

        if top_bin.bin_id == target_bin_id:
            task.target_removed = True

            return {
                "type": "remove_target",
                "from_stack": target_stack.stack_id,
                "bin_id": target_bin_id,
            }

        buffer_stack = self._select_relocation_stack(
            state=state,
            exclude_stack=target_stack,
        )

        return {
            "type": "relocate",
            "from_stack": target_stack.stack_id,
            "to_stack": buffer_stack.stack_id,
            "bin_id": top_bin.bin_id,
        }

    def _next_restore_blockers_action(self, state, task):
        relocation = task.peek_last_relocation()

        if relocation is not None:
            to_stack_id = relocation["from_stack"]

            # R-D2: Ziel-Stack für Rücklagerung validieren – ist er zugänglich?
            to_stack = self._get_stack_by_id(state, to_stack_id)

            if to_stack is not None and not self._is_stack_accessible_for_return(state, to_stack):
                # Ziel-Stack ist blockiert → alternativen Stack wählen und Eintrag aktualisieren
                alt_stack = self._select_relocation_stack(
                    state=state,
                    exclude_stack=to_stack,
                )
                task.update_return_stack_for_blocker(
                    bin_id=relocation["bin_id"],
                    new_to_stack=alt_stack.stack_id,
                )
                to_stack_id = alt_stack.stack_id

            return {
                "type": "return",
                "return_kind": "blocker",
                "from_stack": relocation["buffer_stack"],
                "to_stack": to_stack_id,
                "bin_id": relocation["bin_id"],
            }

        if not task.pickstation_completed:
            task.phase = RobotTask.PHASE_WAIT_FOR_PICKSTATION
            return None

        task.phase = RobotTask.PHASE_RETURN_TARGET
        return self.next_action(state, task)

    def _next_wait_for_pickstation_action(self, task):
        """
        Während PHASE_WAIT_FOR_PICKSTATION kann der Task keine Aktion ausführen.
        Er wartet darauf, dass das PICKSTATION_COMPLETE-Event den Task fortsetzt.
        """
        return None

    def _next_return_target_action(self, state, task):
        """
        R-D3: Prüft, ob der ursprüngliche Ziel-Stack für die Target-Bin noch zugänglich ist.
        """
        if task.target_stack_id is None:
            raise RuntimeError(
                f"Cannot return target bin {task.target_bin_id}: "
                f"task.target_stack_id is unknown"
            )

        target_stack = self._get_stack_by_id(state, task.target_stack_id)

        if target_stack is None:
            raise RuntimeError(
                f"Cannot return target bin {task.target_bin_id}: "
                f"target stack {task.target_stack_id} not found"
            )

        top_bin = target_stack.peek()
        max_height = self._get_max_stack_height(state)

        # Stack ist voll oder wird von einer fremden Bin belegt → freispielen
        if top_bin is not None and top_bin.bin_id != task.target_bin_id:
            if max_height is not None and target_stack.height() >= max_height:
                # Oberste (fremde) Bin räumen, damit Platz entsteht
                alt_stack = self._select_relocation_stack(
                    state=state,
                    exclude_stack=target_stack,
                )
                return {
                    "type": "relocate",
                    "from_stack": target_stack.stack_id,
                    "to_stack": alt_stack.stack_id,
                    "bin_id": top_bin.bin_id,
                }

        return {
            "type": "return",
            "return_kind": "target",
            "from_stack": None,
            "to_stack": task.target_stack_id,
            "bin_id": task.target_bin_id,
        }

    def _next_complete_action(self, task):
        return {
            "type": "request_complete",
            "request_id": task.request_id,
            "bin_id": task.target_bin_id,
        }

    def _create_plan(self, state, request):
        """
        Legacy-Komplettplanung.

        Der neue Next-Step-Flow nutzt diese Methode nicht mehr.
        Sie bleibt vorerst erhalten, damit ältere Aufrufe nicht sofort brechen.
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

    # (Legacy _create_plan und weitere Helper bleiben unverändert)
    # ----------------------------------
    # Helper Functions
    # ----------------------------------

    def _find_bin(self, state, bin_id):
        for stack in state.grid.all_stacks():
            for level, bin_obj in enumerate(stack.bins):
                if bin_obj.bin_id == bin_id:
                    return stack, level

        return None, None

    def _is_stack_accessible_for_return(self, state, stack):
        """
        Prüft, ob ein Stack für eine Rücklagerung zugänglich ist.

        Ein Stack ist nicht zugänglich, wenn:
        - er gesperrt (locked) ist, oder
        - er die maximale Höhe bereits erreicht hat.
        """
        if stack.is_locked():
            return False

        max_height = self._get_max_stack_height(state)
        if max_height is not None and stack.height() >= max_height:
            return False

        return True

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

    def _get_buffer_stacks(self, state, exclude_stack):
        return [stack for stack in state.grid.all_stacks() if stack != exclude_stack]

    def _select_relocation_stack(self, state, exclude_stack):
        """
        Delegiert die Platzwahl für temporäre Ablage an RelocationSelection.

        Bewusst nicht als Heuristik bezeichnet:
        Diese Funktion kapselt nur die aktuelle Relocation-Selection und kann
        später durch bessere Auswahlverfahren ersetzt werden.
        """
        # RelocationSelection arbeitet mit dem konkreten Quellstack-Objekt.
        # exclude_stack ist hier genau dieser Quellstack.
        return self._relocation_selector.select_temporary_stack(
            state=state,
            source_stack=exclude_stack,
        )

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