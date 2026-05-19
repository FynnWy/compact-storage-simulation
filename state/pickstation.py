# state/pickstation.py

class Pickstation:
    """
    Repräsentiert eine physische Pickstation im Lager.

    Eigenschaften:
    - Feste Position (typischerweise am Rand oder außerhalb des Grids)
    - Queue wartender Tasks (FCFS oder Priorität)
    - Kapazität (wie viele Bins gleichzeitig bearbeitet werden können)
    - Statistiken (Durchsatz, Auslastung, Wartezeit)

    Wichtig:
    - Leichtgewichtige Entity ohne eigene Manager-Logik
    - Alle Scheduling-Logik bleibt im EventHandler/Scheduler
    - Diese Klasse hält nur den State
    """

    def __init__(self, station_id, position, capacity=1):
        """
        Args:
            station_id: Eindeutige ID der Pickstation (z.B. "PS_0")
            position: (x, y) Grid-Position (kann außerhalb liegen, z.B. (-1, 0))
            capacity: Wie viele Bins gleichzeitig bearbeitet werden können
        """
        self.station_id = station_id
        self.position = position
        self.capacity = capacity

        # --- Zustand ---
        self.queue = []  # [(task, arrival_time), ...]
        self.current_tasks = []  # Aktuell bediente Tasks (max = capacity)
        self.available_slots = capacity

        # --- Statistiken ---
        self.total_bins_processed = 0
        self.total_tasks_processed = 0
        self.total_wait_time = 0
        self.total_service_time = 0

    # ================================================================
    # Queue-Verwaltung
    # ================================================================

    def enqueue(self, task, current_time):
        """
        Fügt einen Task zur Warteschlange hinzu.

        Args:
            task: RobotTask-Objekt
            current_time: Aktueller Simulationszeitpunkt
        """
        self.queue.append((task, current_time))

    def dequeue_fcfs(self):
        """
        Entfernt und gibt nächsten Task zurück (First-Come-First-Served).

        Returns:
            (task, arrival_time) | None
        """
        if not self.queue:
            return None
        return self.queue.pop(0)

    def dequeue_priority(self, scheduler):
        """
        Entfernt und gibt Task mit höchster Priorität zurück.

        Args:
            scheduler: Scheduler-Instanz (für Prioritätsabfrage)

        Returns:
            (task, arrival_time) | None
        """
        if not self.queue:
            return None

        # Finde Task mit höchster Priorität (niedrigster Prioritätswert)
        best_idx = 0
        best_priority = scheduler._get_task_priority(self.queue[0][0])

        for i, (task, _) in enumerate(self.queue[1:], start=1):
            priority = scheduler._get_task_priority(task)
            if priority < best_priority:
                best_priority = priority
                best_idx = i

        return self.queue.pop(best_idx)

    def dequeue(self, strategy="FCFS", scheduler=None):
        """
        Entfernt und gibt nächsten Task basierend auf Strategie zurück.

        Args:
            strategy: "FCFS" oder "PRIORITY"
            scheduler: Scheduler-Instanz (nur bei PRIORITY erforderlich)

        Returns:
            (task, arrival_time) | None
        """
        if strategy == "FCFS":
            return self.dequeue_fcfs()
        elif strategy == "PRIORITY":
            if scheduler is None:
                raise ValueError("Priority-based dequeue requires scheduler instance")
            return self.dequeue_priority(scheduler)
        else:
            raise ValueError(f"Unknown queue strategy: {strategy}")

    # ================================================================
    # Service-Verwaltung
    # ================================================================

    def start_service(self, task):
        """
        Beginnt Service für einen Task.
        Darf nur aufgerufen werden, wenn freie Kapazität vorhanden ist.

        Args:
            task: RobotTask-Objekt
        """
        if self.available_slots <= 0:
            raise RuntimeError(
                f"Cannot start service at pickstation {self.station_id}: "
                f"no available slots (capacity={self.capacity})"
            )

        self.current_tasks.append(task)
        self.available_slots -= 1

    def complete_service(self, task):
        """
        Beendet Service für einen Task.

        Args:
            task: RobotTask-Objekt
        """
        if task not in self.current_tasks:
            raise RuntimeError(
                f"Cannot complete service for task {task.request_id} at "
                f"pickstation {self.station_id}: task not in current_tasks"
            )

        self.current_tasks.remove(task)
        self.available_slots += 1

        # Statistiken aktualisieren
        batch_size = 1 + len(task.batched_requests)
        self.total_bins_processed += batch_size
        self.total_tasks_processed += 1

    # ================================================================
    # Zustandsabfragen
    # ================================================================

    def has_capacity(self):
        """Gibt True zurück, wenn freie Kapazität vorhanden ist."""
        return self.available_slots > 0

    def is_idle(self):
        """Gibt True zurück, wenn keine Tasks bedient werden."""
        return len(self.current_tasks) == 0

    def queue_length(self):
        """Gibt Anzahl wartender Tasks zurück."""
        return len(self.queue)

    def is_serving(self, task):
        """Prüft, ob ein bestimmter Task aktuell bedient wird."""
        return task in self.current_tasks

    # ================================================================
    # Statistiken
    # ================================================================

    def get_utilization(self, total_simulation_time):
        """
        Berechnet Auslastung der Pickstation.

        Args:
            total_simulation_time: Gesamte Simulationsdauer

        Returns:
            float: Auslastung zwischen 0.0 und 1.0
        """
        if total_simulation_time == 0:
            return 0.0
        return self.total_service_time / total_simulation_time

    def get_average_wait_time(self):
        """
        Berechnet durchschnittliche Wartezeit.

        Returns:
            float: Durchschnittliche Wartezeit in Zeiteinheiten
        """
        if self.total_tasks_processed == 0:
            return 0.0
        return self.total_wait_time / self.total_tasks_processed

    def record_wait_time(self, wait_time):
        """Fügt Wartezeit zu Statistiken hinzu."""
        self.total_wait_time += wait_time

    def record_service_time(self, service_time):
        """Fügt Servicezeit zu Statistiken hinzu."""
        self.total_service_time += service_time

    # ================================================================
    # Debugging
    # ================================================================

    def __repr__(self):
        return (
            f"Pickstation("
            f"id={self.station_id}, "
            f"pos={self.position}, "
            f"capacity={self.capacity}, "
            f"queue={self.queue_length()}, "
            f"serving={len(self.current_tasks)}, "
            f"processed={self.total_tasks_processed}"
            f")"
        )