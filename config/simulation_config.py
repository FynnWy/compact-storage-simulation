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
        self.enable_visualization = True
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
