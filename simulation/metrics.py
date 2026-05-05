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

    def record_target_bin_removed(self, state, action, request=None):
        """
        Speichert den Zeitpunkt, an dem die Zielkiste tatsächlich an der Pickstation ist.

        Dieser Zeitpunkt zählt als Erfüllungszeitpunkt des Requests.
        Danach kann die Zielkiste wieder zurückgelegt werden.
        """
        removal_time = state.t

        record = {
            "time": removal_time,
            "bin_id": action.get("bin_id"),
            "action_type": action.get("type"),
        }

        if request is not None:
            tardiness = max(0, removal_time - request.latest_time)
            deadline_missed = tardiness > 0

            record.update({
                "request_id": request.request_id,
                "arrival_time": request.arrival_time,
                "earliest_time": request.earliest_time,
                "latest_time": request.latest_time,
                "tardiness": tardiness,
                "deadline_missed": deadline_missed,
            })

            self.completed_requests.append(record)
            self.total_tardiness += tardiness

            self._increment(self.completed_requests_by_time, removal_time)

            if deadline_missed:
                self.missed_deadline_requests += 1
                self._increment(self.missed_deadline_requests_by_time, removal_time)
            else:
                self.successful_requests += 1
                self._increment(self.successful_requests_by_time, removal_time)

            if removal_time not in self.tardiness_by_time:
                self.tardiness_by_time[removal_time] = []

            self.tardiness_by_time[removal_time].append(tardiness)

        self.target_bin_removals.append(record)

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
        Anzahl erfolgreicher Requests, deren Zielkiste innerhalb der Deadline entnommen wurde.
        """
        return self.successful_requests

    def time_series(self):
        """
        Gibt Zeitreihen zurück, um später Strategien über die Zeit vergleichen zu können.
        """
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
        return {
            "completed_requests": len(self.completed_requests),
            "successful_requests": self.successful_requests,
            "missed_deadline_requests": self.missed_deadline_requests,
            "deadline_miss_rate": self.deadline_miss_rate(),
            "average_tardiness": self.average_tardiness(),
            "throughput": self.throughput(),
            "target_bin_removals": self.target_bin_removals,
            "time_series": self.time_series(),
        }

    def _increment(self, dictionary, key):
        dictionary[key] = dictionary.get(key, 0) + 1