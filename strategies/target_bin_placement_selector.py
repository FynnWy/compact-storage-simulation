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

        if strategy == "POPULARITY":
            return self._select_popularity_stack(state, bin_obj)

        if strategy == "NEAREST":
            # LR+NR: NÄCHSTER zulässiger Stack RELATIV ZUR PICKSTATION
            return self._select_nearest_stack(state)

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

        # NEU: Stack darf nicht in der Port-Pufferzone liegen
        if hasattr(state, "is_valid_storage_position"):
            pos = self._parse_stack_position(stack)
            if not state.is_valid_storage_position(pos[0], pos[1]):
                raise RuntimeError(
                    f"Cannot select original return stack: stack {stack.stack_id} "
                    f"is in a port buffer zone or at a port"
                )

        return stack

    def _select_random_stack(self, state):
        """
        Wählt zufälligen Stack mit freier Kapazität (CIRS/AutoStore Baseline),
        der NICHT in einer Port-Pufferzone liegt.
        """
        candidates = self._get_eligible_stacks(state)

        if not candidates:
            raise RuntimeError(
                "No suitable stack with free capacity available for RANDOM placement"
            )

        index = int(self.rng.integers(len(candidates)))
        return candidates[index]

    def _select_nearest_stack(self, state):
        """
        Wählt den nächstgelegenen zulässigen Stack relativ zur Pickstation.

        Distanz wird über Manhattan-Distanz zur NÄCHSTGELEGENEN Pickstation
        berechnet (get_min_distance_to_pickstation).

        Bei Gleichstand: Tie-Breaking nach y-Koordinate, dann x-Koordinate.

        Zulässigkeitskriterien:
        - Nicht gesperrt
        - Freie Kapazität (< max_stack_height)
        - Nicht in Port-Pufferzone
        """
        candidates = self._get_eligible_stacks(state)

        if not candidates:
            raise RuntimeError(
                "No suitable stack with free capacity available for NEAREST placement"
            )

        # Sortieren nach Distanz zur Pickstation mit deterministischem Tie-Breaking
        def sort_key(stack):
            pos = self._parse_stack_position(stack)
            distance = get_min_distance_to_pickstation(state, pos)
            # Tie-Breaking: y-Koordinate, dann x-Koordinate
            return (distance, pos[1], pos[0])

        candidates_sorted = sorted(candidates, key=sort_key)
        return candidates_sorted[0]

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

    def _select_popularity_stack(self, state, bin_obj):
        """
        Popularity-basierte Platzierung für Target-Bin-Rücklagerung.

        Scoring-Formel für jeden Stack:
            score = alpha * normalized_distance + beta * normalized_depth

        Wobei:
            - normalized_distance = distance_to_nearest_pickstation / max_distance
              (max_distance = max. Distanz unter allen Kandidaten)
            - normalized_depth = expected_digging_depth / max_stack_height
            - expected_digging_depth ~ aktuelle Stackhöhe (je voller, desto tiefer)
            - alpha, beta aus config
              (popularity_distance_weight, popularity_depth_weight)

        Placement-Logik:
            - Popularität p in [0, 1] (0 = kalt, 1 = heiß)
            - Hot (p >= hot_threshold):  Stack mit minimalem Score
            - Cold (p <= cold_threshold): Stack mit maximalem Score
            - Neutral: Stack mit Score am nächsten zu 0.5

        Warmup:
            - total_accesses = Summe aller access_counts im System
            - Solange total_accesses < popularity_warmup_requests oder
              max_access_count == 0 -> Fallback: RANDOM-Placement
        """
        candidates = self._get_eligible_stacks(state)

        if not candidates:
            raise RuntimeError("No suitable stack with free capacity available for POPULARITY placement")

        # --- Popularity & Warmup ------------------------------------------------
        all_counts = [b.get_access_count() for b in state.bins]
        max_count = max(all_counts) if all_counts else 0
        total_accesses = sum(all_counts)

        warmup_requests = getattr(self.config, "popularity_warmup_requests", 0)

        # Cold-Start / Warmup: noch keine sinnvolle Popularität verfügbar
        if max_count == 0 or total_accesses < warmup_requests:
            # Empfehlung aus Aufgabenstellung: Random-Fallback
            return self._select_random_stack(state)

        popularity = self._get_popularity_score(state, bin_obj, all_counts=all_counts, max_count=max_count)

        hot_threshold = getattr(self.config, "popularity_hot_threshold", 0.7)
        cold_threshold = getattr(self.config, "popularity_cold_threshold", 0.3)

        alpha = getattr(self.config, "popularity_distance_weight", 0.5)
        beta = getattr(self.config, "popularity_depth_weight", 0.5)

        max_stack_height = self._get_max_stack_height(state)
        if max_stack_height is None or max_stack_height <= 0:
            # Fallback: nutze maximale aktuelle Höhe als Normalisierung
            max_stack_height = max((stack.height() for stack in candidates), default=1) or 1

        # --- Distanz- und Depth-Infos je Stack ---------------------------------
        stack_infos = []
        distances = []

        for stack in candidates:
            pos = self._parse_stack_position(stack)
            distance = get_min_distance_to_pickstation(state, pos)
            expected_depth = self._calc_expected_digging_depth(state, stack)
            stack_infos.append((stack, distance, expected_depth))
            distances.append(distance)

        max_distance = max(distances) if distances else 0
        if max_distance <= 0:
            max_distance = 1  # vermeiden von Division durch 0

        # Score für jeden Stack berechnen
        scored_stacks = []
        for stack, distance, expected_depth in stack_infos:
            normalized_distance = distance / max_distance
            normalized_depth = expected_depth / max_stack_height
            score = alpha * normalized_distance + beta * normalized_depth
            scored_stacks.append((stack, score))

        # --- Auswahl je nach Popularität ---------------------------------------
        if popularity >= hot_threshold:
            # Hot: score minimieren
            best_score = None
            best_stacks = []
            for stack, score in scored_stacks:
                if best_score is None or score < best_score:
                    best_score = score
                    best_stacks = [stack]
                elif score == best_score:
                    best_stacks.append(stack)

        elif popularity <= cold_threshold:
            # Cold: score maximieren
            best_score = None
            best_stacks = []
            for stack, score in scored_stacks:
                if best_score is None or score > best_score:
                    best_score = score
                    best_stacks = [stack]
                elif score == best_score:
                    best_stacks.append(stack)
        else:
            # Neutral: Score möglichst balanciert (nahe 0.5)
            best_distance_to_mid = None
            best_stacks = []
            for stack, score in scored_stacks:
                dist_to_mid = abs(score - 0.5)
                if best_distance_to_mid is None or dist_to_mid < best_distance_to_mid:
                    best_distance_to_mid = dist_to_mid
                    best_stacks = [stack]
                elif dist_to_mid == best_distance_to_mid:
                    best_stacks.append(stack)

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
        - NICHT in einer Port-Pufferzone (falls State dies unterstützt)
        """
        max_stack_height = self._get_max_stack_height(state)
        candidates = []

        for stack in state.grid.all_stacks():
            if stack.is_locked():
                continue

            if max_stack_height is not None and stack.height() >= max_stack_height:
                continue

            # NEU: Pufferzonen-Filter, falls verfügbar
            if hasattr(state, "is_valid_storage_position"):
                pos = self._parse_stack_position(stack)
                if not state.is_valid_storage_position(pos[0], pos[1]):
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

    def _get_popularity_score(self, state, bin_obj, all_counts=None, max_count=None) -> float:
        """
        Gibt normalisierten Popularitätswert zwischen 0 und 1 zurück.

        Definition:
            popularity = access_count / max_access_count

        Fallback:
            Wenn max_access_count == 0:
                0.5 (neutral)
        """
        if all_counts is None:
            all_counts = [b.get_access_count() for b in state.bins]

        if max_count is None:
            max_count = max(all_counts) if all_counts else 0

        if max_count <= 0:
            return 0.5

        return bin_obj.get_access_count() / max_count

    def _calc_expected_digging_depth(self, state, stack) -> float:
        """
        Berechnet erwartete Grabtiefe, wenn eine Bin von diesem Stack angefordert wird.

        Vereinfachte Annahme:
            expected_digging_depth ~ aktuelle Stackhöhe.

        Interpretation:
            - Je höher (voller) der Stack, desto tiefer wird zukünftig
              durchschnittlich gegraben werden müssen.
        """
        current_height = stack.height()
        return float(current_height)