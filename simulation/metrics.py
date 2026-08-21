from metrics.convergence_detector import ConvergenceDetector, PositionChangeTracker


class Metrics:
    def __init__(self):
        self.completed_requests = []
        self.successful_requests = 0
        self.missed_deadline_requests = 0
        self.total_tardiness = 0

        self.target_bin_removals = []

        self.successful_requests_by_time = {}
        self.missed_deadline_requests_by_time = {}
        self.tardiness_by_time = {}
        self.completed_requests_by_time = {}

        # Metrik 1: Arrival → Pickstation-Ankunft
        self._arrival_to_pickstation = []
        # Metrik 3 (Hauptmetrik): Arrival → vollständige Fertigstellung
        self._arrival_to_full_completion = []

        # ------------------------------------------------------------------
        # WP5: Steady-State / Konvergenz
        # ------------------------------------------------------------------
        # Detector für Distribution-Snapshots (Digging-Depth, Hot-Bin-Ratio, etc.)
        self.convergence_detector = ConvergenceDetector()
        # Tracker für Positionsänderungen der Bins
        self.position_tracker = PositionChangeTracker()
        # Optional: Roh-Snapshots für spätere Auswertung/Export
        self._distribution_snapshots = []

        # ------------------------------------------------------------------
        # WP5/RQ3: Digging-Depth pro Request
        # ------------------------------------------------------------------
        self.request_digging_depths = []

        # PHASE 5 (RQ1/RQ3): Eine Zeile je PHYSISCHEM Target-Retrieval.
        # Kompakte Rohdatentabelle statt eines vollständigen Eventlogs –
        # daraus lassen sich Level-Verteilung, P(beta = s), Digging-Tiefe je
        # ABC-Klasse und der Anteil der Retrievals aus den oberen Ebenen
        # rekonstruieren.
        self.retrievals = []

    # ----------------------------------------------------------------------
    # WP5: Distribution & Positionsänderungen
    # ----------------------------------------------------------------------

    def record_distribution_snapshot(self, snapshot: dict) -> None:
        """
        Fügt einen Distribution-Snapshot hinzu und aktualisiert den
        ConvergenceDetector.

        Erwartet u.a.:
            snapshot = {
                "time": int,
                "average_digging_depth": float,
                "hot_bins_top_ratio": float,
                "popularity_depth_correlation": float,  # optional
                ...
            }
        """
        self._distribution_snapshots.append(snapshot)
        self.convergence_detector.add_snapshot(snapshot)

    def record_position_state(self, state) -> None:
        """
        Nimmt den aktuellen Lagerzustand auf und berechnet Positionsänderungen
        gegenüber dem vorherigen Snapshot.
        """
        current_time = getattr(state, "t", None)
        if current_time is None:
            return
        self.position_tracker.record_state(state, current_time)

    def get_convergence_analysis(self) -> dict:
        """
        Liefert Konvergenz- und Stabilitätsmetriken für RQ4.

        Struktur:
            {
                "is_converged": bool,
                "convergence_time": int | None,
                "stability_metrics": { ... aus ConvergenceDetector.get_stability_metrics() ... },
                "snapshots": [... alle Roh-Snapshots ...],
            }
        """
        return {
            "is_converged": self.convergence_detector.is_converged(),
            "convergence_time": self.convergence_detector.get_convergence_time(),
            "stability_metrics": self.convergence_detector.get_stability_metrics(),
            "snapshots": list(self._distribution_snapshots),
        }

    def get_position_change_timeseries(self):
        """
        Liefert die Zeitreihe der Positionsänderungen für RQ3/RQ4:

            [
                {
                    "time": t,
                    "total_moves": ...,
                    "bins_changed_stack": ...,
                    "bins_changed_level": ...,
                },
                ...
            ]
        """
        return self.position_tracker.get_timeseries()

    def get_distribution_timeseries(self):
        """
        Liefert die Zeitreihe aller Distribution-Snapshots für RQ3/RQ4.
        """
        return list(self._distribution_snapshots)

    # ----------------------------------------------------------------------
    # WP5/RQ3: Digging-Depth pro Request
    # ----------------------------------------------------------------------

    def record_digging_depth(self, depth: int) -> None:
        """
        Zeichnet die Anzahl der Blocking-Bins (Digging-Depth) für ein Retrieval auf.
        """
        if depth is None:
            return
        try:
            d = int(depth)
        except (TypeError, ValueError):
            return
        if d < 0:
            d = 0
        self.request_digging_depths.append(d)

    def record_retrieval(self, record: dict) -> None:
        """
        Erfasst ein physisches Target-Retrieval (eine Bin an der Pickstation).

        Genau EINE Zeile je Retrieval – unabhängig davon, wie viele Requests
        durch dieses Retrieval bedient werden (Batching). Die Batchgröße steht
        als Feld in der Zeile.
        """
        self.retrievals.append(record)

    def get_average_digging_depth(self) -> float:
        """
        Durchschnittliche Anzahl Blocking-Bins pro tatsächlichem Retrieval
        (auf Basis der Request-Events).
        """
        if not self.request_digging_depths:
            return 0.0
        return sum(self.request_digging_depths) / len(self.request_digging_depths)

    # ----------------------------------------------------------------------
    # Bestehende Metriken (unverändert)
    # ----------------------------------------------------------------------

    def record_target_bin_at_pickstation(self, state, action, request=None):
        """
        Erfasst den Zeitpunkt, an dem die Ziel-Bin die Pickstation erreicht.

        Metrik 1: Arrival → Pickstation.
        Ersetzt record_target_bin_removed (rückwärtskompatibel umbenannt).
        """
        pickstation_time = state.t

        record = {
            "time": pickstation_time,
            "bin_id": action.get("bin_id"),
            "action_type": action.get("type"),
        }

        if request is not None:
            tardiness = max(0, pickstation_time - request.latest_time)
            deadline_missed = tardiness > 0

            record.update({
                "request_id": request.request_id,
                "arrival_time": request.arrival_time,
                "earliest_time": request.earliest_time,
                "latest_time": request.latest_time,
                "tardiness": tardiness,
                "deadline_missed": deadline_missed,
                "time_arrival_to_pickstation": pickstation_time - request.arrival_time,
            })

            self._arrival_to_pickstation.append({
                "request_id": request.request_id,
                "arrival_time": request.arrival_time,
                "pickstation_time": pickstation_time,
                "duration": pickstation_time - request.arrival_time,
            })

            self.total_tardiness += tardiness
            self._increment(self.completed_requests_by_time, pickstation_time)

            if deadline_missed:
                self.missed_deadline_requests += 1
                self._increment(self.missed_deadline_requests_by_time, pickstation_time)
            else:
                self.successful_requests += 1
                self._increment(self.successful_requests_by_time, pickstation_time)

            if pickstation_time not in self.tardiness_by_time:
                self.tardiness_by_time[pickstation_time] = []

            self.tardiness_by_time[pickstation_time].append(tardiness)

        self.target_bin_removals.append(record)
        self.completed_requests.append(record)

    # Rückwärtskompatibilität
    def record_target_bin_removed(self, state, action, request=None):
        self.record_target_bin_at_pickstation(state, action, request)

    def record_full_completion(self, completion_time, request):
        """
        Metrik 3 (Hauptmetrik): Arrival → vollständige Fertigstellung.

        Vollständig = Target-Bin zurückgelagert, Blocker zurück, Lager konsistent.
        Wird separat für jeden Request (inkl. gebatchte) aufgerufen.
        """
        if request is None:
            return

        self._arrival_to_full_completion.append({
            "request_id": request.request_id,
            "arrival_time": request.arrival_time,
            "completion_time": completion_time,
            "duration": completion_time - request.arrival_time,
        })

    def average_arrival_to_pickstation(self):
        if not self._arrival_to_pickstation:
            return 0
        return sum(r["duration"] for r in self._arrival_to_pickstation) / len(self._arrival_to_pickstation)

    def average_arrival_to_full_completion(self):
        """Hauptmetrik: durchschnittliche Durchlaufzeit Arrival → vollständige Fertigstellung."""
        if not self._arrival_to_full_completion:
            return 0
        return sum(r["duration"] for r in self._arrival_to_full_completion) / len(self._arrival_to_full_completion)

    def deadline_miss_rate(self):
        total = len(self.completed_requests)

        if total == 0:
            return 0

        return self.missed_deadline_requests / total

    def average_tardiness(self):
        total = len(self.completed_requests)

        if total == 0:
            return 0

        return self.total_tardiness / total

    def throughput(self):
        """
        Anzahl vollständig abgeschlossener Requests.

        Hinweis:
        On-time-Requests werden separat als successful_requests geführt.
        """
        return len(self._arrival_to_full_completion)

    def throughput_on_time(self):
        return self.successful_requests

    def time_series(self):
        all_times = sorted(
            set(self.completed_requests_by_time.keys())
            | set(self.successful_requests_by_time.keys())
            | set(self.missed_deadline_requests_by_time.keys())
            | set(self.tardiness_by_time.keys())
        )

        series = []

        cumulative_completed = 0
        cumulative_successful = 0
        cumulative_missed = 0
        cumulative_tardiness = 0

        for t in all_times:
            completed = self.completed_requests_by_time.get(t, 0)
            successful = self.successful_requests_by_time.get(t, 0)
            missed = self.missed_deadline_requests_by_time.get(t, 0)
            tardiness_values = self.tardiness_by_time.get(t, [])
            tardiness_sum = sum(tardiness_values)

            cumulative_completed += completed
            cumulative_successful += successful
            cumulative_missed += missed
            cumulative_tardiness += tardiness_sum

            cumulative_miss_rate = (
                cumulative_missed / cumulative_completed
                if cumulative_completed > 0
                else 0
            )

            cumulative_average_tardiness = (
                cumulative_tardiness / cumulative_completed
                if cumulative_completed > 0
                else 0
            )

            series.append({
                "time": t,
                "completed": completed,
                "successful": successful,
                "missed": missed,
                "average_tardiness_at_time": (
                    tardiness_sum / completed if completed > 0 else 0
                ),
                "cumulative_completed": cumulative_completed,
                "cumulative_successful": cumulative_successful,
                "cumulative_missed": cumulative_missed,
                "cumulative_miss_rate": cumulative_miss_rate,
                "cumulative_average_tardiness": cumulative_average_tardiness,
            })

        return series

    def summary(self):
        # Letzten Distribution-Snapshot für kompakte Übersicht holen (falls vorhanden)
        last_distribution_snapshot = self._distribution_snapshots[-1] if self._distribution_snapshots else None

        base = {
            "completed_requests": len(self.completed_requests),
            "successful_requests": self.successful_requests,
            "missed_deadline_requests": self.missed_deadline_requests,
            "deadline_miss_rate": self.deadline_miss_rate(),
            "average_tardiness": self.average_tardiness(),
            "throughput": self.throughput(),
            "throughput_on_time": self.throughput_on_time(),
            "average_arrival_to_pickstation": self.average_arrival_to_pickstation(),
            "average_arrival_to_full_completion": self.average_arrival_to_full_completion(),
            "target_bin_removals": self.target_bin_removals,
            "time_series": self.time_series(),
            "requests_completed": len(self._arrival_to_full_completion),
        }

        # WP5/RQ3-Zusatzinformationen (kompakt gehalten)
        base.update({
            "average_request_digging_depth": self.get_average_digging_depth(),
            "last_distribution_snapshot": last_distribution_snapshot,
            # PHASE 5: physische Retrievals – Basis der primären KPI.
            "physical_retrievals": len(self.retrievals),
        })

        return base

    def _increment(self, dictionary, key):
        dictionary[key] = dictionary.get(key, 0) + 1