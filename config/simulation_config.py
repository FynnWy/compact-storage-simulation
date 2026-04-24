class SimulationConfig:
    def __init__(self):
        self.grid_width = 5
        self.grid_depth = 5
        self.bin_num = 100
        self.num_robots = 3
        self.simulation_time = 100
        self.random_seed = 42


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

        self.request_utilization = 2
        self.request_arrival_strategy = "Poisson"
        self.bin_request_prob_strategy = "Zipf"
        # Zipf-Parameter (wenn bin_request_prob_strategy = "Zipf")
        self.zipf_parameter = 0.8


        """
        Initale Verteilung der Kisten im Grid:
        """
        self.init_strategy = "uniform"

