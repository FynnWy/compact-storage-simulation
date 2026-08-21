from strategies.base_strategy import BaseStrategy
from strategies.relocation_selection import RelocationSelection
from strategies.target_bin_placement_selector import PlacementSelector
from simulation.robot_task import RobotTask



class TopAccessStrategy(BaseStrategy):
    def __init__(
        self,
        relocation_selector=None,
        reordering_strategy="LOFI",
        placement_strategy="ORIGINAL",
        placement_selector=None,
        reordering_selector=None,
        active_queue=None,
    ):
        """
        Top-Access-Strategie mit Next-Step-Planning.

        Args:
            relocation_selector:
                Optionale externe Instanz von RelocationSelection.
                Falls None, wird eine Standardinstanz verwendet.
            reordering_strategy:
                Name der Blocking-Bin-Reordering-Strategie ("LOFI", "ABC", "POPULARITY").
                WP0: nur Konfiguration, die Logik folgt in späteren WPs.
            placement_strategy:
                Name der Target-Bin-Placement-Strategie
                ("ORIGINAL", "RANDOM", "ABC", "POPULARITY").
                WP0: nur Konfiguration, die Logik folgt in späteren WPs.
            placement_selector:
                Optionale Instanz von PlacementSelector.
                Falls None, wird eine Default-Instanz ohne Config erstellt
                (sollte in der Praxis aber immer über SimulationEngine injiziert werden).
            reordering_selector:
                Optionale Instanz von ReorderingSelector für Blocking-Bin-Reordering.
            active_queue:
                Optionale ActiveQueue-Instanz. Wird ausschließlich benötigt,
                um beim Verwerfen der Blocker-Restore-Verpflichtung
                (`return_blocking_bins=False`) die globale Blocker-Ownership
                freizugeben (Phase 3B, Befund P3-02). Analog zur bereits
                vorhandenen Injektion in `RelocationSelection`.
        """
        super().__init__()
        self._relocation_selector = relocation_selector or RelocationSelection()
        self.reordering_strategy = reordering_strategy
        self.placement_strategy = placement_strategy
        self._placement_selector = placement_selector
        self._reordering_selector = reordering_selector
        self._active_queue = active_queue
        # Fallback, falls jemand TopAccessStrategy direkt ohne Selector konstruiert.
        # In der regulären Simulation wird eine korrekt konfigurierte Instanz injiziert.
        if self._placement_selector is None:
            self._placement_selector = PlacementSelector(config=None)

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
            return self._next_return_target_action(state, task)

        if task.phase == RobotTask.PHASE_COMPLETE:
            # NEU: Keine weitere Action mehr planen.
            # Completion-Events werden ausschließlich im EventHandler direkt
            # nach einem erfolgreichen Target-Return erzeugt.
            return None

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

            if target_bin is not None and getattr(target_bin, "in_transit", False):
                # Bin ist temporär zwischen Pickup und Drop unterwegs.
                # Kein Fehlerzustand: Task kurz warten lassen und später neu versuchen.
                return None

            status = target_bin.get_status() if target_bin is not None else None
            in_transit = getattr(target_bin, "in_transit", None) if target_bin is not None else None
            raise RuntimeError(
                f"Target bin {target_bin_id} not found in storage or pickstation "
                f"(status={status}, in_transit={in_transit})"
            )

        if task.target_stack_id is None:
            task.target_stack_id = target_stack.stack_id

        top_bin = target_stack.peek()

        if top_bin is None:
            raise RuntimeError(
                f"Target stack {target_stack.stack_id} unexpectedly empty "
                f"while retrieving bin {target_bin_id}"
            )

        if top_bin.bin_id == target_bin_id:
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
        # NEU: Prüfen, ob Blocking-Bins überhaupt zurückgelegt werden sollen
        if not self._should_return_blocking_bins(state):
            # Alle Relocation-Einträge verwerfen (Bins bleiben wo sie sind).
            # PHASE 3B (P3-02): Zusammen mit der Task-lokalen Verpflichtung
            # muss auch die globale Blocker-Ownership fallen, sonst bleibt die
            # Bin dauerhaft reserviert, obwohl niemand sie mehr zurücklegt.
            task.clear_all_relocations(active_queue=self._active_queue)

            # Weiter zur nächsten Phase
            if not task.pickstation_completed:
                task.phase = RobotTask.PHASE_WAIT_FOR_PICKSTATION
                return None

            task.phase = RobotTask.PHASE_RETURN_TARGET
            return self.next_action(state, task)

        # --- Bestehende Logik für Ordered Return ---
        # NEU: Vor der ersten Rücklagerung Blocker ggf. umsortieren
        if not task.blockers_reordered and task.has_blockers_to_restore():
            if self._reordering_selector is None:
                # Defensive: Ohne ReorderingSelector bleibt aktuelles Verhalten (LOFI)
                task.blockers_reordered = True
            else:
                task.reorder_blockers_for_return(
                    state=state,
                    reordering_selector=self._reordering_selector,
                )

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
        R-D3 (erweitert):
        Wählt den Rückgabe-Stack für die Target-Bin gemäß placement_strategy.

        - ORIGINAL:
            Target-Bin wird auf den ursprünglichen Stack zurückgelegt
            (sofern dieser existiert, nicht gesperrt ist und Kapazität hat).
        - RANDOM:
            Target-Bin wird auf einen zufälligen Stack mit freier Kapazität gelegt
            (CIRS / AutoStore-Baseline).
        """
        if task.target_stack_id is None:
            raise RuntimeError(
                f"Cannot return target bin {task.target_bin_id}: "
                f"task.target_stack_id is unknown"
            )

        # Target-Bin muss an der Pickstation sein
        bin_obj = state.get_bin_by_id(task.target_bin_id)
        if bin_obj is None:
            raise RuntimeError(
                f"Cannot return target bin {task.target_bin_id}: bin not found in state"
            )

        if bin_obj.get_status() != "at_pickstation":
            # Defensiv gegen veraltete Task-Fortsetzungen:
            # Die Bin kann bereits durch einen früheren/konkurrierenden Event-Pfad
            # zurückgelegt worden sein (status='stored').
            if bin_obj.get_status() == "stored":
                expected_stack_id = task.actual_return_stack_id or task.target_stack_id
                expected_stack_pos = expected_stack_id

                if isinstance(expected_stack_id, str) and expected_stack_id.startswith("S_"):
                    parts = expected_stack_id.split("_")
                    if len(parts) == 3:
                        try:
                            expected_stack_pos = (int(parts[1]), int(parts[2]))
                        except ValueError:
                            expected_stack_pos = expected_stack_id

                if bin_obj.get_stack() == expected_stack_pos:
                    task.mark_target_returned()
                    return {
                        "type": "request_complete",
                        "request_id": task.request_id,
                        "bin_id": task.target_bin_id,
                    }

            # ConstraintManager würde das auch abfangen, aber hier ist es klarer
            raise RuntimeError(
                f"Cannot return target bin {task.target_bin_id}: "
                f"expected status 'at_pickstation', got '{bin_obj.get_status()}'"
            )

        # Ziel-Stack über PlacementSelector bestimmen
        target_stack = self._placement_selector.select_return_stack(
            state=state,
            bin_obj=bin_obj,
            original_stack_id=task.target_stack_id,
        )

        if target_stack is None:
            raise RuntimeError(
                f"PlacementSelector returned None for target bin {task.target_bin_id}"
            )

        # Für Metriken/Debugging merken, wohin die Bin tatsächlich gelegt wurde
        task.actual_return_stack_id = target_stack.stack_id

        return {
            "type": "return",
            "return_kind": "target",
            "from_stack": None,  # Rückgabe von der Pickstation
            "to_stack": target_stack.stack_id,
            "bin_id": task.target_bin_id,
        }

    def _next_complete_action(self, task):
        """
        Legacy-Helper für frühere Strategien.

        Im Next-Step-Flow von TopAccessStrategy wird PHASE_COMPLETE nicht mehr
        über eine request_complete-Action beendet, sondern ausschließlich über
        REQUEST_COMPLETE-Events, die im EventHandler nach Target-Return
        erzeugt werden. Diese Methode bleibt nur für Rückwärtskompatibilität
        bestehen und sollte in neuen Flows nicht mehr verwendet werden.
        """
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
        Buffer-Stacks dürfen NICHT in Port-Pufferzonen liegen.
        """
        max_stack_height = self._get_max_stack_height(state)

        candidate_stacks = []

        for stack in state.grid.all_stacks():
            if stack.stack_id not in simulated_buffers:
                continue

            simulated_height = len(simulated_buffers[stack.stack_id])

            if max_stack_height is not None and simulated_height >= max_stack_height:
                continue

            # NEU: Pufferzonen-Filter (falls State dies unterstützt)
            if hasattr(state, "is_valid_storage_position"):
                pos = self._parse_stack_position(stack)
                if not state.is_valid_storage_position(pos[0], pos[1]):
                    continue

            candidate_stacks.append(stack)

        if not candidate_stacks:
            raise RuntimeError("No buffer stack with free capacity available")

        return min(
            candidate_stacks,
            key=lambda stack: len(simulated_buffers[stack.stack_id]),
        )

    def _get_max_stack_height(self, state):
        """
        Sucht defensiv die maximale Stapelhöhe.

        Unterstützte Varianten:
        - state.max_stack_height
        - state.config.max_stack_height
        - state.config.stack_height
        - state.config.stack_capacity

        Gibt None zurück, wenn keine Begrenzung gefunden wird.
        """
        # Direkt am State
        if hasattr(state, "max_stack_height"):
            return state.max_stack_height

        config = getattr(state, "config", None)
        if config is None:
            return None

        for attr_name in ("max_stack_height", "stack_height", "stack_capacity"):
            if hasattr(config, attr_name):
                return getattr(config, attr_name)

        return None

    def _should_return_blocking_bins(self, state):
        """
        Prüft, ob Blocking-Bins zurückgelegt werden sollen.

        Liest return_blocking_bins aus state.config.
        Default: True (Ordered Return)
        """
        config = getattr(state, "config", None)
        if config is None:
            return True
        return getattr(config, "return_blocking_bins", True)

    def _parse_stack_position(self, stack):
        """
        Ermittelt eine (x, y)-Position für einen Stack, falls möglich.

        Unterstützte Varianten:
        - stack.stack_id als Tuple: (x, y)
        - stack.stack_id als String: 'S_x_y'
        """
        stack_id = getattr(stack, "stack_id", None)

        if isinstance(stack_id, tuple) and len(stack_id) == 2:
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")
            if len(parts) == 3:
                try:
                    x = int(parts[1])
                    y = int(parts[2])
                    return x, y
                except ValueError:
                    pass

        raise RuntimeError(f"Cannot parse position for stack_id={stack_id}")