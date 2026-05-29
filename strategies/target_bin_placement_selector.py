import numpy as np

from utils.distance_helpers import get_min_distance_to_pickstation


class PlacementSelector:
    """
    Wählt den Ziel-Stack für die Target-Bin-Rücklagerung nach Pickstation-Bearbeitung.

    Wichtig:
    - NICHT für Blocking-Bins während des Retrievals zuständig.
      Blocking-Bins werden ausschließlich von RelocationSelection behandelt.
    - Diese Klasse entscheidet nur, auf welchen Stack die Target-Bin NACH
      der Pickstation gelegt werden soll.
    """

    def __init__(self, config, rng=None):
        """
        Args:
            config:
                SimulationConfig mit Attribut placement_strategy.
            rng:
                Optionaler Random Number Generator für reproduzierbare Zufallsauswahl.
        """
        self.config = config
        self.rng = rng or np.random.default_rng()

    # ------------------------------------------------------------------ #
    # Öffentliches Interface
    # ------------------------------------------------------------------ #

    def select_return_stack(self, state, bin_obj, original_stack_id):
        """
        Wählt Stack für Target-Bin-Rücklagerung basierend auf placement_strategy.
        """
        strategy = "ORIGINAL"
        if self.config is not None and hasattr(self.config, "placement_strategy"):
            strategy = getattr(self.config, "placement_strategy", "ORIGINAL")

        if strategy == "ORIGINAL":
            return self._select_original_stack(state, original_stack_id)

        if strategy == "RANDOM":
            return self._select_random_stack(state)

        if strategy == "ABC":
            return self._select_abc_stack(state, bin_obj)

        raise ValueError(f"Unknown placement strategy: {strategy}")

    # ------------------------------------------------------------------ #
    # Strategien
    # ------------------------------------------------------------------ #

    def _select_original_stack(self, state, original_stack_id):
        """
        Gibt den Original-Stack zurück (aktuelles Verhalten).

        Prüft defensiv:
        - Stack existiert
        - Stack ist nicht gesperrt
        - Stack hat freie Kapazität (falls max_stack_height gesetzt ist)
        """
        stack = self._get_stack_by_id(state, original_stack_id)

        if stack is None:
            raise RuntimeError(
                f"Cannot select original return stack: stack {original_stack_id} not found"
            )

        if stack.is_locked():
            raise RuntimeError(
                f"Cannot select original return stack: stack {stack.stack_id} is locked"
            )

        if not self._has_capacity(stack, state):
            raise RuntimeError(
                f"Cannot select original return stack: stack {stack.stack_id} "
                f"has no free capacity"
            )

        return stack

    def _select_random_stack(self, state):
        """
        Wählt zufälligen Stack mit freier Kapazität (CIRS/AutoStore Baseline).
        """
        max_stack_height = self._get_max_stack_height(state)

        candidates = []
        for stack in state.grid.all_stacks():
            if stack.is_locked():
                continue

            if max_stack_height is not None and stack.height() >= max_stack_height:
                continue

            candidates.append(stack)

        if not candidates:
            raise RuntimeError("No suitable stack with free capacity available for RANDOM placement")

        index = int(self.rng.integers(len(candidates)))
        return candidates[index]

    def _select_abc_stack(self, state, bin_obj):
        """
        ABC-Zonenbasierte Platzierung für Target-Bin-Rücklagerung.

        Algorithmus:
        1. Ermittelt für alle Stacks mit freier Kapazität die Distanz zur nächsten
           Pickstation und die aktuelle Höhe.
        2. Basierend auf der ABC-Klasse der Bin:
           - A-Bins: Minimiere (distance + depth) -> nahe Pickstation, niedrige Stacks.
           - B-Bins: Minimiere |distance - median_distance| -> mittlere Distanz.
           - C-Bins: Maximiere distance (Tiefe wird toleriert).
        3. Bei Gleichstand: Zufällige Auswahl unter den besten Kandidaten.
        """
        abc_class = bin_obj.get_abc_class()
        candidates = self._get_eligible_stacks(state)

        if not candidates:
            raise RuntimeError("No suitable stack with free capacity available for ABC placement")

        # Vorab Distanz und Tiefe berechnen
        stack_infos = []
        distances = []

        for stack in candidates:
            pos = self._parse_stack_position(stack)
            distance = get_min_distance_to_pickstation(state, pos)
            depth = stack.height()
            stack_infos.append((stack, distance, depth))
            distances.append(distance)

        if not distances:
            raise RuntimeError("No distances available for ABC placement")

        if abc_class == "A":
            # A-Score = distance + depth (minimieren)
            best_score = None
            best_stacks = []
            for stack, distance, depth in stack_infos:
                score = distance + depth
                if best_score is None or score < best_score:
                    best_score = score
                    best_stacks = [stack]
                elif score == best_score:
                    best_stacks.append(stack)

        elif abc_class == "B":
            # B-Score = |distance - median_distance| (minimieren = mittlere Distanz)
            if not distances:
                raise RuntimeError("No distances available for ABC placement (B-class)")
            sorted_distances = sorted(distances)
            mid = len(sorted_distances) // 2
            if len(sorted_distances) % 2 == 1:
                median_distance = sorted_distances[mid]
            else:
                median_distance = 0.5 * (
                    sorted_distances[mid - 1] + sorted_distances[mid]
                )

            best_score = None
            best_stacks = []
            for stack, distance, _depth in stack_infos:
                score = abs(distance - median_distance)
                if best_score is None or score < best_score:
                    best_score = score
                    best_stacks = [stack]
                elif score == best_score:
                    best_stacks.append(stack)

        else:
            # C oder None: Maximiere Distanz (Tiefe wird toleriert)
            max_distance = None
            best_stacks = []
            for stack, distance, _depth in stack_infos:
                if max_distance is None or distance > max_distance:
                    max_distance = distance
                    best_stacks = [stack]
                elif distance == max_distance:
                    best_stacks.append(stack)

        # Bei mehreren gleich guten Kandidaten zufällig auswählen
        if len(best_stacks) == 1:
            return best_stacks[0]

        index = int(self.rng.integers(len(best_stacks)))
        return best_stacks[index]

    # ------------------------------------------------------------------ #
    # Hilfsfunktionen
    # ------------------------------------------------------------------ #

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

    def _get_max_stack_height(self, state):
        """
        Sucht defensiv die maximale Stapelhöhe.
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

    def _has_capacity(self, stack, state):
        max_stack_height = self._get_max_stack_height(state)

        if max_stack_height is None:
            return True

        return stack.height() < max_stack_height

    def _get_eligible_stacks(self, state):
        """
        Liefert alle Stacks, die für Target-Bin-Rücklagerung verfügbar sind:
        - nicht gesperrt
        - unterhalb max_stack_height (falls definiert)
        """
        max_stack_height = self._get_max_stack_height(state)
        candidates = []

        for stack in state.grid.all_stacks():
            if stack.is_locked():
                continue

            if max_stack_height is not None and stack.height() >= max_stack_height:
                continue

            candidates.append(stack)

        return candidates

    def _parse_stack_position(self, stack):
        """
        Ermittelt eine (x, y)-Position für einen Stack, falls möglich.

        Unterstützt:
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