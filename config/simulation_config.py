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

