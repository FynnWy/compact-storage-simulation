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
