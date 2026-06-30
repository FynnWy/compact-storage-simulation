from __future__ import annotations

from typing import List, Dict, Any, Optional


class ConvergenceDetector:
    """
    Erkennt Konvergenz und Steady-State basierend auf Distribution-Snapshots.

    Ein Snapshot ist ein dict, das mindestens folgende Keys enthält:
        - "time": int
        - "average_digging_depth": float
        - "hot_bins_top_ratio": float
        - "popularity_depth_correlation": float (optional für Konvergenz-Check)
    """

    def __init__(self, window_size: int = 10, threshold: float = 0.05):
        """
        Args:
            window_size: Anzahl der Snapshots für gleitendes Fenster
            threshold: Varianz-Schwellenwert für Konvergenz-Erkennung
        """
        self.window_size = window_size
        self.threshold = threshold
        self.history: List[dict] = []
        self._convergence_time: Optional[int] = None

    # --------------------------------------------------------------------- #
    # Öffentliche API
    # --------------------------------------------------------------------- #

    def add_snapshot(self, snapshot: dict) -> None:
        """Fügt neuen Snapshot hinzu und prüft auf Konvergenz."""
        self.history.append(snapshot)
        self._check_convergence()

    def is_converged(self) -> bool:
        """Gibt True zurück, wenn System konvergiert ist."""
        return self._convergence_time is not None

    def get_convergence_time(self) -> Optional[int]:
        """Gibt Zeitpunkt der ersten Konvergenz zurück (oder None)."""
        return self._convergence_time

    def get_stability_metrics(self) -> dict:
        """
        Berechnet Stabilitätsmetriken über die gesamte Historie.

        Returns:
            {
                "variance_over_time": [
                    {
                        "time":  t_window_end,
                        "var_average_digging_depth": ...,
                        "var_hot_bins_top_ratio": ...,
                        "var_popularity_depth_correlation": ...,
                    },
                    ...
                ],
                "rolling_mean_digging_depth": [
                    {"time": t_window_end, "value": mean_digging_depth},
                    ...
                ],
                "convergence_point": 500,       # Zeitpunkt oder None
                "post_convergence_stability": { # Varianz nach Konvergenz
                    "average_digging_depth": 0.02,
                    "hot_bins_top_ratio": 0.01,
                    "popularity_depth_correlation": 0.03,
                },
            }
        """
        if not self.history:
            return {
                "variance_over_time": [],
                "rolling_mean_digging_depth": [],
                "convergence_point": None,
                "post_convergence_stability": {
                    "average_digging_depth": 0.0,
                    "hot_bins_top_ratio": 0.0,
                    "popularity_depth_correlation": 0.0,
                },
            }

        variance_over_time: List[Dict[str, Any]] = []
        rolling_mean_digging_depth: List[Dict[str, float]] = []

        # Rolling-Window-Auswertung
        if len(self.history) >= self.window_size:
            for i in range(self.window_size, len(self.history) + 1):
                window = self.history[i - self.window_size:i]

                digging_vals = [s.get("average_digging_depth", 0.0) for s in window]
                hot_top_vals = [s.get("hot_bins_top_ratio", 0.0) for s in window]
                pop_corr_vals = [s.get("popularity_depth_correlation", 0.0) for s in window]

                var_digging = self._calc_variance(digging_vals)
                var_hot = self._calc_variance(hot_top_vals)
                var_pop = self._calc_variance(pop_corr_vals)

                mean_digging = sum(digging_vals) / len(digging_vals) if digging_vals else 0.0

                t_window_end = window[-1].get("time", i - 1)

                variance_over_time.append({
                    "time": t_window_end,
                    "var_average_digging_depth": var_digging,
                    "var_hot_bins_top_ratio": var_hot,
                    "var_popularity_depth_correlation": var_pop,
                })

                rolling_mean_digging_depth.append({
                    "time": t_window_end,
                    "value": mean_digging,
                })

        # Post-Konvergenz-Stabilität
        conv_time = self._convergence_time
        if conv_time is None:
            post_stability = {
                "average_digging_depth": 0.0,
                "hot_bins_top_ratio": 0.0,
                "popularity_depth_correlation": 0.0,
            }
        else:
            post_window = [s for s in self.history if s.get("time", 0) >= conv_time]

            digging_vals = [s.get("average_digging_depth", 0.0) for s in post_window]
            hot_top_vals = [s.get("hot_bins_top_ratio", 0.0) for s in post_window]
            pop_corr_vals = [s.get("popularity_depth_correlation", 0.0) for s in post_window]

            post_stability = {
                "average_digging_depth": self._calc_variance(digging_vals),
                "hot_bins_top_ratio": self._calc_variance(hot_top_vals),
                "popularity_depth_correlation": self._calc_variance(pop_corr_vals),
            }

        return {
            "variance_over_time": variance_over_time,
            "rolling_mean_digging_depth": rolling_mean_digging_depth,
            "convergence_point": conv_time,
            "post_convergence_stability": post_stability,
        }

    # --------------------------------------------------------------------- #
    # Interne Helfer
    # --------------------------------------------------------------------- #

    def _check_convergence(self) -> None:
        """
        Prüft, ob System konvergiert ist.

        Kriterium: Varianz der Key-Metriken über letzten window_size Snapshots < threshold

        Key Metrics für Konvergenz-Check:
        - average_digging_depth
        - hot_bins_top_ratio
        (popularity_depth_correlation kann optional ergänzt werden)
        """
        if len(self.history) < self.window_size:
            return

        if self._convergence_time is not None:
            return  # Bereits konvergiert

        window = self.history[-self.window_size:]

        # Berechne Varianz für jede Key-Metric
        for metric_name in ["average_digging_depth", "hot_bins_top_ratio"]:
            values = [s.get(metric_name, 0.0) for s in window]
            variance = self._calc_variance(values)
            if variance > self.threshold:
                return  # Noch nicht konvergiert

        # Alle Metriken stabil -> konvergiert
        last_time = window[-1].get("time")
        if last_time is not None:
            self._convergence_time = int(last_time)

    @staticmethod
    def _calc_variance(values: List[float]) -> float:
        """Berechnet Varianz einer Werteliste."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)


class PositionChangeTracker:
    """Verfolgt, wie stark sich Bin-Positionen zwischen Snapshots ändern."""

    def __init__(self):
        self.previous_positions: Dict[int, tuple] = {}  # bin_id -> (stack_id, level)
        self.change_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Öffentliche API
    # ------------------------------------------------------------------ #

    def record_state(self, state, time: int) -> None:
        """
        Erfasst aktuelle Bin-Positionen und berechnet Änderungen zum Vorgänger.
        """
        current_positions = self._extract_positions(state)

        if self.previous_positions:
            changes = self._calc_position_changes(
                self.previous_positions,
                current_positions,
            )
            self.change_history.append({
                "time": time,
                "total_moves": changes["total_moves"],
                "bins_changed_stack": changes["bins_changed_stack"],
                "bins_changed_level": changes["bins_changed_level"],
            })

        self.previous_positions = current_positions

    def get_timeseries(self) -> List[Dict[str, Any]]:
        """
        Gibt die Zeitreihe der Positionsänderungen zurück.
        Elemente:
            {
                "time": t,
                "total_moves": ...,
                "bins_changed_stack": ...,
                "bins_changed_level": ...,
            }
        """
        return list(self.change_history)

    # ------------------------------------------------------------------ #
    # Interne Helfer
    # ------------------------------------------------------------------ #

    def _extract_positions(self, state) -> Dict[int, tuple]:
        """Extrahiert alle Bin-Positionen als dict."""
        positions: Dict[int, tuple] = {}
        for bin_obj in state.bins:
            positions[bin_obj.bin_id] = (
                bin_obj.get_stack(),
                bin_obj.get_level(),
            )
        return positions

    def _calc_position_changes(self, prev: dict, curr: dict) -> dict:
        """Berechnet Änderungen zwischen zwei Positionszuständen."""
        total_moves = 0
        stack_changes = 0
        level_changes = 0

        for bin_id, (prev_stack, prev_level) in prev.items():
            curr_stack, curr_level = curr.get(bin_id, (None, None))
            if prev_stack != curr_stack:
                stack_changes += 1
                total_moves += 1
            elif prev_level != curr_level:
                level_changes += 1
                total_moves += 1

        return {
            "total_moves": total_moves,
            "bins_changed_stack": stack_changes,
            "bins_changed_level": level_changes,
        }