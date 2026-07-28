# config/simulation_config.py

class SimulationConfig:
    def __init__(self):
        self.grid_width = 5
        self.grid_depth = 5
        self.max_stack_height = 6

        self.bin_num = 100
        self.num_robots = 3
        self.simulation_time = 100
        self.random_seed = 42

        """
        Visualisierung:
        False = Simulation läuft komplett ohne GUI durch.
        True = Interaktive Visualisierung mit Next-Event-Button.
        """
        self.enable_visualization = False
        self.visualization_type = "web"  # "matplotlib" oder "web"

        """
        Initialisierung:
        random_distribution = alle Bins zufällig über alle Stack-Positionen verteilen.
        Hot Items werden hier NICHT speziell platziert.
        Hot Items entstehen nur über bin_request_prob_strategy.
        """
        self.init_strategy = "random_distribution"

        """
        Scheduling:
        FIFO = First In First Out, ältester Request zuerst
        EDF = Earliest Deadline First, Request mit kleinster latest_time zuerst
        """
        self.scheduler_strategy = "FIFO"

        """
        Request Generierung:

        self.request_queue: request_generator (t_earliest, t_latest dort modifizierbar) aufrufen
        self.request_utilization: Wie viele Request im mittel pro ZE reinkommen
        self.request_arrival_strategy: wie viele Requests pro ZE reinkommen
            "Poisson" = Poisson-Verteilung (realistisch für zufällige Ankünfte)
            "Uniform" = Gleichmäßig viele Requests pro ZE
        self.bin_request_prob_strategy: welche Kiste wird wie häufig angefragt
            "Uniform" = gleichverteilt
            "Zipf" = Hot Items, realistischer - manche Kisten werden häufig angefragt
        self.zipf_parameter: Typische Werte: 0.8 (moderat) bis 1.5 (extrem)
        """
        self.request_utilization = 0.6
        self.request_arrival_strategy = "Poisson"
        self.bin_request_prob_strategy = "Uniform"
        self.zipf_parameter = 1.1

        """
        Realistische Aktionskosten:
        - Bewegung auf dem Grid: Manhattan-Distanz * move_cost_per_grid_step
        - Armbewegung: Runterfahren + Hochziehen abhängig von Zugriffstiefe
        - Greifen / Herausziehen einer Bin
        - Pickstation-Servicezeit
        """
        self.move_cost_per_grid_step = 1
        self.arm_move_cost_per_level = 1
        self.grip_cost = 1
        self.drop_cost = 1

        # Dauer für Bin-Manipulation (relocate, remove_target, return)
        # Umfasst: Greifen + Heben/Senken des Arms
        self.action_cost_bin_manipulation = self.grip_cost + self.arm_move_cost_per_level

        """
        Pickstation-Konfiguration.
        
        num_pickstations:
            Anzahl der Pickstations im System.
            Jede Pickstation wird automatisch am linken Rand des Grids platziert.
        
        pickstation_capacity:
            Wie viele Bins gleichzeitig an einer Pickstation bearbeitet werden können.
            Typischerweise 1 (eine Bin pro Station).
        
        pickstation_queue_strategy:
            "FCFS" = First-Come-First-Served (Standard)
            "PRIORITY" = Tasks mit höherer Priorität werden bevorzugt
        
        pickstation_service_time_min/max:
            Bearbeitungszeit-Intervall an der Pickstation.
        """
        self.num_pickstations = 1
        self.pickstation_capacity = 1
        self.pickstation_queue_strategy = "FCFS"  # "FCFS" oder "PRIORITY"
        
        self.pickstation_service_time_min = 4
        self.pickstation_service_time_max = 6

        # DEPRECATED: Diese wird durch Pickstation-Objekte ersetzt
        # Bleibt vorerst für Backward-Compatibility
        self.pickstation_position = (-1, 0)


        """
        Highway-System (optional).

        enable_highway_system:
            Aktiviert/Deaktiviert das Highway-System.
            Default: False (deaktiviert)

        highway_pattern:
            Pattern für bevorzugte Fahrtrichtungen.
            Optionen:
            - "ring": Ringförmiges Einbahnstraßensystem
            - "rows": Alternierende horizontale Reihen
            - "lanes": Vertikale Bahnen
            - "none": Keine Beschränkungen

        highway_wrong_direction_penalty:
            Strafkosten für Fahrt gegen bevorzugte Richtung.
            Höhere Werte = stärkere Bevorzugung der Highway-Richtungen.
        """
        self.enable_highway_system = False
        self.highway_pattern = "ring"  # "ring", "rows", "lanes", "none"
        self.highway_wrong_direction_penalty = 5

        # ------------------------------------------------------------
        # Strategie-Konfiguration (WP0)
        # ------------------------------------------------------------

        # Reordering-Strategie für Blocking-Bins
        # "LOFI"       = Last-Out-First-In (Baseline)
        # "ABC"        = Klassenbasiertes Reordering (A oben)
        # "POPULARITY" = tatsächliche Zugriffshäufigkeit
        self.reordering_strategy = "LOFI"

        # Placement-Strategie für Target-Bin-Rücklagerung
        # "ORIGINAL"   = zurück auf Original-Stack (aktuelles Verhalten)
        # "RANDOM"     = zufälliger Stack mit Kapazität (CIRS-Baseline, für RR+RR)
        # "NEAREST"    = nächstgelegener Stack zum Original (für LR+NR)
        # "ABC"        = Zonen nach ABC-Klasse
        # "POPULARITY" = Distanz + erwartete Grabtiefe gewichtet
        self.placement_strategy = "ORIGINAL"

        # ------------------------------------------------------------
        # Blocking-Bin Rücklagerung
        # ------------------------------------------------------------

        # Ob Blocking-Bins nach dem Pick auf den Original-Stack zurückgelegt werden
        # True  = Ordered Return (aktuelles Verhalten)
        # False = Blocking-Bins verbleiben an neuer Position (für RR+RR, LR+NR)
        self.return_blocking_bins = True

        # ABC-Klassifizierung basierend auf Zipf-Verteilung (über bin_id)
        # Beispiel bei 100 Bins:
        #   - Top 20% (0-19): A
        #   - Nächste 30% (20-49): B
        #   - Rest (50-99): C
        self.abc_threshold_a = 0.2  # Top 20% = A-Items
        self.abc_threshold_b = 0.5  # Nächste 30% = B-Items (kumulativ 50%)

        # Gewichtung für Popularity-Placement
        # Wird später genutzt, um Distanz vs. Tiefe zu balancieren.
        # score = alpha * normalized_distance + beta * normalized_depth
        self.popularity_distance_weight = 0.5
        self.popularity_depth_weight = 0.5

        # ------------------------------------------------------------
        # Popularity-spezifische Parameter (WP3)
        # ------------------------------------------------------------

        # Warmup-Phase: Bis zu dieser Anzahl kumulierter Retrievals
        # wird Popularity-Placement nicht verwendet, sondern auf
        # RANDOM-Placement zurückgefallen.
        self.popularity_warmup_requests = 50

        # Schwellen für Hot/Cold-Klassifikation auf Basis des
        # normalisierten Popularity-Scores in [0, 1]
        # p >= hot_threshold  -> Hot  (näher zur Pickstation, geringe Tiefe)
        # p <= cold_threshold -> Cold (weiter weg, tiefere Stacks ok)
        # dazwischen          -> Neutral
        self.popularity_hot_threshold = 0.7
        self.popularity_cold_threshold = 0.3

        # ------------------------------------------------------------
        # WP5: Steady-State / Konvergenz-Erkennung & Early-Stopping
        # ------------------------------------------------------------

        # Falls True:
        # - Simulation kann vorzeitig beendet werden, wenn ein
        #   Konvergenzzustand erkannt wurde und die Geduldszeit
        #   (convergence_patience) abgelaufen ist.
        self.stop_on_convergence = False

        # Wie lange nach dem ersten Konvergenzzeitpunkt noch weiter
        # simuliert wird (in Zeiteinheiten), bevor frühzeitig
        # abgebrochen werden darf.
        self.convergence_patience = 200

        # Optional: Parameter für ConvergenceDetector
        # (werden in SimulationEngine beim Erzeugen von Metrics gespiegelt)
        self.convergence_window_size = 10
        self.convergence_threshold = 0.05

        # ------------------------------------------------------------
        # WP5/RQ3: Distribution-Snapshots
        # ------------------------------------------------------------

        # Zeiteinheiten zwischen zwei Distribution-Snapshots.
        # Empfehlung: 50–200, abhängig von Simulation_time.
        self.distribution_snapshot_interval = 100

        # ------------------------------------------------------------
        # Port-Priorisierung (WP4)
        # ------------------------------------------------------------
        # Zeiteinheiten pro Bewegungsschritt für die Port-Ankunftsschätzung.
        # Default: identisch zu move_cost_per_grid_step.
        self.port_move_cost_per_cell: int = self.move_cost_per_grid_step
