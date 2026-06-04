# metrics/distribution_metrics.py

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from utils.distance_helpers import get_min_distance_to_pickstation


class DistributionMetrics:
    """Erfasst und berechnet Bin-Verteilungsmetriken für RQ3."""

    def __init__(self, state, config):
        self.state = state
        self.config = config

    # ------------------------------------------------------------------ #
    # Öffentliches Interface
    # ------------------------------------------------------------------ #

    def snapshot(self) -> dict:
        """
        Erfasst aktuellen Verteilungszustand.
        Sollte periodisch aufgerufen werden (z.B. alle N Zeiteinheiten).

        Returns:
            Dictionary mit allen Metriken zum aktuellen Zeitpunkt
        """
        return {
            "time": self.state.t,
            "average_digging_depth": self._calc_average_digging_depth(),
            "depth_by_abc_class": self._calc_depth_by_abc_class(),
            "hot_bins_top_ratio": self._calc_hot_bins_top_ratio(),
            "popularity_depth_correlation": self._calc_popularity_depth_correlation(),
            "stack_height_distribution": self._calc_stack_height_distribution(),
            "stack_height_variance": self._calc_stack_height_variance(),
            "bin_distribution_entropy": self._calc_distribution_entropy(),
            "abc_zone_adherence": self._calc_abc_zone_adherence(),
        }

    # Export-Helfer – nutze sie z.B. mit metrics.get_distribution_timeseries()
    def to_json(self, snapshots: List[dict]) -> str:
        """Serialisiert eine Liste von Snapshots nach JSON."""
        return json.dumps(snapshots, indent=2)

    def to_dataframe(self, snapshots: List[dict]):
        """
        Konvertiert Snapshots in ein pandas.DataFrame (falls pandas installiert ist).

        Achtung:
            - Nested Felder wie depth_by_abc_class / abc_zone_adherence werden als Dict-Spalten übernommen.
        """
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pandas is required for to_dataframe(), but is not installed."
            ) from exc

        return pd.json_normalize(snapshots)

    # ------------------------------------------------------------------ #
    # Interne Metrik-Berechnungen
    # ------------------------------------------------------------------ #

    def _iter_bins_in_stacks(self):
        """
        Generator über alle Bins, die aktuell in Stacks (nicht Pickstation) liegen.
        """
        for stack in self.state.grid.all_stacks():
            for lvl, bin_obj in enumerate(stack.bins):
                yield stack, lvl, bin_obj

    def _calc_average_digging_depth(self) -> float:
        """
        Durchschnittliche "Grabtiefe" für alle Bins.

        Grabtiefe einer Bin = Anzahl Bins, die über ihr im Stack liegen
                            = (stack_height - 1 - bin_level)

        Niedrigerer Wert = Bins sind leichter erreichbar.
        """
        depths: List[float] = []

        for stack in self.state.grid.all_stacks():
            h = stack.height()
            if h == 0:
                continue
            for level, _bin in enumerate(stack.bins):
                digging_depth = (h - 1) - level
                depths.append(float(digging_depth))

        if not depths:
            return 0.0

        return sum(depths) / len(depths)

    def _calc_depth_by_abc_class(self) -> dict:
        """
        Durchschnittliche Grabtiefe pro ABC-Klasse.

        Returns:
            {"A": 1.2, "B": 2.5, "C": 3.8}

        Erwartung bei guter ABC-Strategie: A < B < C
        """
        sums = {"A": 0.0, "B": 0.0, "C": 0.0}
        counts = {"A": 0, "B": 0, "C": 0}

        for stack in self.state.grid.all_stacks():
            h = stack.height()
            if h == 0:
                continue
            for level, bin_obj in enumerate(stack.bins):
                abc_class = bin_obj.get_abc_class()
                if abc_class not in sums:
                    continue
                digging_depth = (h - 1) - level
                sums[abc_class] += float(digging_depth)
                counts[abc_class] += 1

        result = {}
        for cls in ("A", "B", "C"):
            if counts[cls] == 0:
                result[cls] = 0.0
            else:
                result[cls] = sums[cls] / counts[cls]

        return result

    def _calc_hot_bins_top_ratio(self) -> float:
        """
        Anteil der A-Bins, die in den oberen 50% ihres jeweiligen Stacks liegen.

        "Obere 50%" bedeutet: level >= stack_height / 2 (Level 0 = ganz unten).

        Returns:
            Wert zwischen 0.0 und 1.0 (1.0 = alle A-Bins sind oben)
        """
        total_a = 0
        top_a = 0

        for stack in self.state.grid.all_stacks():
            h = stack.height()
            if h == 0:
                continue
            threshold_level = h // 2  # untere Hälfte [0 .. threshold-1], obere [threshold .. h-1]

            for level, bin_obj in enumerate(stack.bins):
                if bin_obj.get_abc_class() != "A":
                    continue
                total_a += 1
                if level >= threshold_level:
                    top_a += 1

        if total_a == 0:
            return 0.0

        return top_a / total_a

    def _calc_popularity_depth_correlation(self) -> float:
        """
        Pearson-Korrelation zwischen access_count und Grabtiefe.

        Berechnung:
          1. Für jede Bin: (access_count, digging_depth)
          2. Berechne Pearson-Korrelationskoeffizient

        Interpretation:
        - Negative Korrelation (< 0): Gut! Hohe Frequenz -> niedrige Grabtiefe
        - Positive Korrelation (> 0): Schlecht! Hohe Frequenz -> hohe Grabtiefe
        - Nahe 0: Keine Beziehung

        Returns:
            Korrelationskoeffizient zwischen -1 und 1
        """
        xs: List[float] = []
        ys: List[float] = []

        for stack in self.state.grid.all_stacks():
            h = stack.height()
            if h == 0:
                continue
            for level, bin_obj in enumerate(stack.bins):
                digging_depth = (h - 1) - level
                access_count = bin_obj.get_access_count()
                xs.append(float(access_count))
                ys.append(float(digging_depth))

        n = len(xs)
        if n < 2:
            return 0.0

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

        if denom_x == 0.0 or denom_y == 0.0:
            return 0.0

        return num / (denom_x * denom_y)

    def _calc_stack_height_distribution(self) -> dict:
        """
        Verteilung der Stack-Höhen.

        Returns:
            {"heights": [3, 4, 5, 3, 6, ...], "mean": 4.2, "std": 1.1}
        """
        heights = [stack.height() for stack in self.state.grid.all_stacks()]
        if not heights:
            return {"heights": [], "mean": 0.0, "std": 0.0}

        mean = sum(heights) / len(heights)
        var = sum((h - mean) ** 2 for h in heights) / len(heights)
        std = math.sqrt(var)

        return {
            "heights": heights,
            "mean": mean,
            "std": std,
        }

    def _calc_stack_height_variance(self) -> float:
        """Varianz der Stack-Höhen."""
        heights = [stack.height() for stack in self.state.grid.all_stacks()]
        if not heights:
            return 0.0

        mean = sum(heights) / len(heights)
        return sum((h - mean) ** 2 for h in heights) / len(heights)

    def _calc_distribution_entropy(self) -> float:
        """
        Shannon-Entropie der Bin-Verteilung über Grid-Zonen.

        Vorgehen:
        - Teile das Grid in 3 x 3 Zonen entlang (x, y)
        - Zähle Bins pro Zone
        - Berechne Entropie: H = -Σ p_i * ln(p_i)

        Hohe Entropie = gleichmäßig verteilt
        Niedrige Entropie = konzentriert in bestimmten Zonen
        """
        grid_w = self.config.grid_width
        grid_d = self.config.grid_depth

        if grid_w <= 0 or grid_d <= 0:
            return 0.0

        # 3x3-Zonen
        def zone_index(coord: int, max_coord: int) -> int:
            # robust gegen kleine Grids
            if max_coord <= 1:
                return 0
            # Segmentgröße ~ max_coord / 3
            segment = max(1, max_coord // 3)
            return min(2, coord // segment)

        zone_counts = [[0 for _ in range(3)] for _ in range(3)]
        total_bins = 0

        for stack in self.state.grid.all_stacks():
            pos = stack.stack_id
            if isinstance(pos, tuple) and len(pos) == 2:
                x, y = pos
            else:
                # Fallback: skip, wenn Position nicht interpretierbar
                continue

            if not (0 <= x < grid_w and 0 <= y < grid_d):
                continue

            zx = zone_index(x, grid_w)
            zy = zone_index(y, grid_d)

            bin_count = stack.height()
            if bin_count <= 0:
                continue

            zone_counts[zx][zy] += bin_count
            total_bins += bin_count

        if total_bins == 0:
            return 0.0

        entropy = 0.0
        for i in range(3):
            for j in range(3):
                c = zone_counts[i][j]
                if c <= 0:
                    continue
                p = c / total_bins
                entropy -= p * math.log(p)

        return entropy

    def _calc_abc_zone_adherence(self) -> dict:
        """
        Wie gut entspricht die tatsächliche Bin-Verteilung den ABC-Zonen?

        Idee:
        - Weise jeden Stack einer Distanz-Zone zu:
            - near  = unteres Drittel der Distanzen
            - mid   = mittleres Drittel
            - far   = oberes Drittel
        - Prüfe:
            - A-Bins in near-Zone
            - B-Bins in mid-Zone
            - C-Bins in far-Zone

        Returns:
            {
                "A_in_near_zone": 0.75,
                "B_in_mid_zone": 0.60,
                "C_in_far_zone": 0.80,
            }
        """
        # 1) Distanz je Stack berechnen
        stack_distances: Dict[Any, float] = {}
        distances: List[float] = []

        for stack in self.state.grid.all_stacks():
            pos = stack.stack_id
            if not (isinstance(pos, tuple) and len(pos) == 2):
                continue
            d = get_min_distance_to_pickstation(self.state, pos)
            stack_distances[stack.stack_id] = float(d)
            distances.append(float(d))

        if not distances:
            return {
                "A_in_near_zone": 0.0,
                "B_in_mid_zone": 0.0,
                "C_in_far_zone": 0.0,
            }

        # 2) Terzile bestimmen
        sorted_ds = sorted(distances)
        n = len(sorted_ds)

        def quantile(q: float) -> float:
            if n == 1:
                return sorted_ds[0]
            idx = int(q * (n - 1))
            return sorted_ds[idx]

        d1 = quantile(1 / 3)
        d2 = quantile(2 / 3)

        def zone_for_distance(d: float) -> str:
            if d <= d1:
                return "near"
            if d <= d2:
                return "mid"
            return "far"

        # 3) Bins nach Zonen zählen
        a_total = b_total = c_total = 0
        a_near = b_mid = c_far = 0

        for stack in self.state.grid.all_stacks():
            d = stack_distances.get(stack.stack_id, None)
            if d is None:
                continue
            zone = zone_for_distance(d)

            for _lvl, bin_obj in enumerate(stack.bins):
                cls = bin_obj.get_abc_class()
                if cls == "A":
                    a_total += 1
                    if zone == "near":
                        a_near += 1
                elif cls == "B":
                    b_total += 1
                    if zone == "mid":
                        b_mid += 1
                elif cls == "C":
                    c_total += 1
                    if zone == "far":
                        c_far += 1

        return {
            "A_in_near_zone": (a_near / a_total) if a_total > 0 else 0.0,
            "B_in_mid_zone": (b_mid / b_total) if b_total > 0 else 0.0,
            "C_in_far_zone": (c_far / c_total) if c_total > 0 else 0.0,
        }