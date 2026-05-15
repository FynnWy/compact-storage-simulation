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
        Pickstation-Servicezeit.
        Eine Target-Bin verweilt nach Ankunft an der Pickstation
        für eine zufällige Dauer in diesem Intervall.
        """
        self.pickstation_service_time_min = 4
        self.pickstation_service_time_max = 6

        """
        Vereinfachte Pickstation-Position.
        Später kann das durch echte Pickstation-Objekte ersetzt werden.
        """
        self.pickstation_position = (-1, 0)
