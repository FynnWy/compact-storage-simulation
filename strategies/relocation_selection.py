# strategies/relocation_selection.py
import numpy as np


class RelocationSelection:
    """
    Kapselt die Platzwahl für temporäre Ablageplätze (Relocation-Selection)
    von blockierenden Bins.

    Verantwortlichkeiten:
    - Ermittelt zulässige Kandidaten-Stacks für eine temporäre Ablage.
    - Bewertet Kandidaten mit einer einfachen Kostenfunktion
      (Nachbarschaft + Distanz).
    - Liefert genau einen Stack zurück oder wirft eine RuntimeError,
      wenn kein zulässiger Stack existiert.

    Wichtig:
    - Kein direkter State-Mut, keine Events, keine Metriken.
    - Keine Scheduler-/Executor-Logik.
    """

    def __init__(
        self,
        neighbor_bonus=1,
        critical_stack_penalty=1000,
        cost_model=None,
        active_queue=None,
        rng=None,
    ):
        """
        Args:
            neighbor_bonus:
                Wie stark direkte Nachbar-Stacks bevorzugt werden
                (subtrahiert von der Distanz).
            critical_stack_penalty:
                Aufschlag für Stacks, die für andere aktive Tasks kritisch sind.
            cost_model:
                Optionales Kostenmodell (z.B. ActionCostModel-Instanz).
                Falls vorhanden und kompatibel, wird es zur Kostenschätzung
                von Relocation-Aktionen verwendet.
            active_queue:
                Optional: ActiveQueue-Instanz, um kritische Bins/Stacks
                zu ermitteln (reservierte Target- und Blocker-Bins).
            rng:
                Optionaler Random Number Generator für zufällige Auswahl
                (z.B. im RR+RR-Setup).
        """
        self.neighbor_bonus = neighbor_bonus
        self.critical_stack_penalty = critical_stack_penalty
        self.cost_model = cost_model
        self.active_queue = active_queue
        self.rng = rng or np.random.default_rng()

    # ------------------------------------------------------------------ #
    # Öffentliches Interface
    # ------------------------------------------------------------------ #

    def select_temporary_stack(self, state, source_stack):
        """
        Wählt einen Stack für die temporäre Ablage einer blockierenden Bin.

        Kriterien:
        - Stack muss existieren und im Grid liegen.
        - Stack darf nicht gesperrt (locked) sein.
        - Stack muss freie Kapazität haben.
        - Quellstack selbst wird nicht verwendet.
        - Bevorzugt werden direkte Nachbar-Stacks.
        - Bevorzugt werden kurze Wege (Manhattan-Distanz im Grid).
        - Stacks, die für andere aktive Tasks kritisch sind, werden bestraft.

        Kritische Stacks (erste Version):
        - Stacks, die eine Bin enthalten, deren ID in
          active_queue.get_all_reserved_bin_ids() liegt
          (Target-Bins aktiver/wartender Tasks + Blocker-Bins mit Ownership).

        WICHTIG:
        - Im RR+RR-Setup (placement_strategy="RANDOM" UND return_blocking_bins=False)
          werden temporäre Stacks ZUFÄLLIG aus den zulässigen Kandidaten gewählt
          (zufällige Verteilung der Blocker im Grid).

        Args:
            state: aktueller Lagerzustand (enthält grid und config).
            source_stack: Stack-Objekt, von dem die Blocker-Bin kommt.

        Returns:
            Ein Stack-Objekt, das als temporärer Ablageplatz genutzt werden soll.

        Raises:
            RuntimeError: wenn kein zulässiger temporärer Ablageplatz gefunden werden kann.
        """
        if state is None or source_stack is None:
            raise RuntimeError("Cannot select relocation stack: state or source_stack is None")

        max_stack_height = self._get_max_stack_height(state)

        source_pos = self._parse_stack_position(source_stack)
        if source_pos is None:
            source_pos = (0, 0)

        critical_stack_ids = self._get_critical_stack_ids(state)

        candidate_scores = []
        candidate_stacks = []

        for stack in state.grid.all_stacks():
            # Quellstack nie als Ziel verwenden
            if stack is source_stack:
                continue

            # Gesperrte Stacks meiden
            if stack.is_locked():
                continue

            # Kapazitätsgrenze beachten, falls definiert
            if max_stack_height is not None and stack.height() >= max_stack_height:
                continue

            # NEU: Pufferzonen-Filter – Buffer-Stack darf nicht in Pufferzone liegen
            if hasattr(state, "is_valid_storage_position"):
                target_pos = self._parse_stack_position(stack)
                if target_pos is not None:
                    if not state.is_valid_storage_position(target_pos[0], target_pos[1]):
                        continue

            candidate_stacks.append(stack)

            # Basis-Kosten: geschätzte Relocation-Kosten (Zeit)
            base_cost = self._estimate_relocation_cost(state, source_stack, stack, source_pos)

            # Kritische Stacks mit Aufschlag versehen
            is_critical = stack.stack_id in critical_stack_ids
            critical_term = self.critical_stack_penalty if is_critical else 0

            score = base_cost + critical_term
            candidate_scores.append((score, stack))

        if not candidate_stacks:
            raise RuntimeError("No relocation stack with free capacity available")

        # ------------------------------------------------------------------ #
        # RR+RR-Modus: Zufällige Verteilung der Blocker auf zulässige Stacks
        # ------------------------------------------------------------------ #
        cfg = getattr(state, "config", None)
        placement_strategy = getattr(cfg, "placement_strategy", None) if cfg is not None else None
        return_blocking_bins = getattr(cfg, "return_blocking_bins", True) if cfg is not None else True

        if placement_strategy == "RANDOM" and return_blocking_bins is False:
            # RR+RR-Setup: Random Relocation – wähle Zufallsstack aus Kandidaten
            index = int(self.rng.integers(len(candidate_stacks)))
            return candidate_stacks[index]

        # ------------------------------------------------------------------ #
        # Default: Kostenbasierte Auswahl (Local Relocation)
        # ------------------------------------------------------------------ #
        candidate_scores.sort(key=lambda item: item[0])
        return candidate_scores[0][1]

    # ------------------------------------------------------------------ #
    # Kostenabschätzung
    # ------------------------------------------------------------------ #

    def _estimate_relocation_cost(self, state, source_stack, target_stack, source_pos):
        """
        Schätzt die Kosten einer Relocation von source_stack nach target_stack.

        Reihenfolge:
        1. Falls ein Kostenmodell vorhanden ist und eine passende Methode
           anbietet, wird dieses verwendet.
        2. Fallback: Manhattan-Distanz im Grid * move_cost_per_grid_step,
           plus optionaler Nachbar-Bonus.
        """
        # 1) Kostenmodell nutzen, falls vorhanden und kompatibel
        if self.cost_model is not None:
            # Konservativ und robust bleiben: nur verwenden, wenn eine
            # intuitive Estimate-Methode existiert.
            if hasattr(self.cost_model, "estimate_relocate_cost"):
                try:
                    return float(
                        self.cost_model.estimate_relocate_cost(
                            state=state,
                            from_stack=source_stack,
                            to_stack=target_stack,
                        )
                    )
                except Exception:
                    # Fallback auf Distanz-basiertes Modell, falls etwas schiefgeht
                    pass

        # 2) Fallback: Distanz-basierte Abschätzung
        target_pos = self._parse_stack_position(target_stack)
        if target_pos is None:
            horizontal_distance = 0
        else:
            sx, sy = source_pos
            tx, ty = target_pos
            horizontal_distance = abs(sx - tx) + abs(sy - ty)

        # Direkte Nachbarn (Manhattan-Distanz 1) leicht bevorzugen
        neighbor_term = -self.neighbor_bonus if horizontal_distance == 1 else 0

        # Move-Kosten aus Config (falls vorhanden), sonst 1
        move_cost_per_step = 1
        config = getattr(state, "config", None)
        if config is not None and hasattr(config, "move_cost_per_grid_step"):
            move_cost_per_step = getattr(config, "move_cost_per_grid_step")

        base_move_cost = horizontal_distance * move_cost_per_step

        return base_move_cost + neighbor_term

    # ------------------------------------------------------------------ #
    # Kritische Stacks ermitteln
    # ------------------------------------------------------------------ #

    def _get_critical_stack_ids(self, state):
        """
        Bestimmt Stacks, die bevorzugt nicht als temporäre Ablage verwendet
        werden sollen.

        Einfache Definition (erste Version):
        - Alle Stacks, die eine Bin enthalten, deren ID in
          active_queue.get_all_reserved_bin_ids() liegt.

        Dazu gehören u.a.:
        - Target-Bins zugewiesener/wartender/Pickstation-Tasks.
        - Alle Blocker-Bins mit aktiver Ownership.
        """
        if self.active_queue is None:
            return set()

        # Reservierte Bins (Targets + Blocker-Ownership)
        try:
            reserved_bin_ids = set(self.active_queue.get_all_reserved_bin_ids())
        except Exception:
            return set()

        if not reserved_bin_ids:
            return set()

        critical_stack_ids = set()

        for bin_id in reserved_bin_ids:
            bin_obj = state.get_bin_by_id(bin_id)
            if bin_obj is None:
                continue

            stack_id = bin_obj.get_stack()
            if stack_id is None:
                # Bin könnte z.B. an der Pickstation sein
                continue

            critical_stack_ids.add(stack_id)

        return critical_stack_ids

    # ------------------------------------------------------------------ #
    # Hilfsfunktionen
    # ------------------------------------------------------------------ #

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

    def _parse_stack_position(self, stack):
        """
        Ermittelt eine (x, y)-Position für einen Stack, falls möglich.

        Unterstützte Varianten:
        - stack.stack_id als Tuple: (x, y)
        - stack.stack_id als String: 'S_x_y'
        - Fallback: None, wenn keine Position bestimmbar ist.
        """
        stack_id = getattr(stack, "stack_id", None)

        # Direktes Tuple
        if isinstance(stack_id, tuple) and len(stack_id) == 2:
            return stack_id

        # Kodierung als 'S_x_y'
        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")
            if len(parts) == 3:
                try:
                    x = int(parts[1])
                    y = int(parts[2])
                    return x, y
                except ValueError:
                    return None

        # Keine verlässliche Position ermittelbar
        return None