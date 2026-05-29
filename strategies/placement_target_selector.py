import numpy as np


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

        Args:
            state:
                Aktueller Simulationszustand.
            bin_obj:
                Die Target-Bin, die zurückgelegt werden soll.
            original_stack_id:
                Der Stack, von dem die Bin ursprünglich kam.

        Returns:
            Stack-Objekt, auf das die Bin gelegt werden soll.

        Raises:
            RuntimeError:
                Wenn kein geeigneter Stack gefunden wird.
            ValueError:
                Wenn eine unbekannte Placement-Strategie konfiguriert ist.
        """
        strategy = getattr(self.config, "placement_strategy", "ORIGINAL")

        if strategy == "ORIGINAL":
            return self._select_original_stack(state, original_stack_id)

        if strategy == "RANDOM":
            return self._select_random_stack(state)

        # Platzhalter für spätere Strategien (ABC, POPULARITY, ...)
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

        Kriterien:
        - Stack muss existieren.
        - Stack darf nicht gesperrt (locked) sein.
        - Stack muss freie Kapazität haben (height < max_stack_height, falls definiert).
        - Gleichverteilte Zufallsauswahl aus allen geeigneten Stacks.
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

        Unterstützte Varianten:
        - state.max_stack_height
        - state.config.max_stack_height
        - state.config.stack_height
        - state.config.stack_capacity

        Gibt None zurück, wenn keine Begrenzung gefunden wird.
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