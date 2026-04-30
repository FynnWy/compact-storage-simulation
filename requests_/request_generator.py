# requests_/request_generator.py
import numpy as np
import random
from events.event_types import EventType
from requests_.request import Request
from config.bin_request_prob_strategy import (
    uniform_bin_sampling,
    zipf_bin_sampling
)


class RequestGenerator:

    def __init__(self, config):
        self.config = config
        self.request_id = 0

        np.random.seed(config.random_seed)
        random.seed(config.random_seed)
        
        # Cache für Pareto-Verteilung (Performance-Optimierung)
        self._pareto_cache = {}

    def generate_requests(self):
        """Generiert Requests basierend auf konfigurierter Arrival-Strategy"""
        
        if self.config.request_arrival_strategy == "Poisson":
            return self._generate_poisson()
        
        else:
            raise ValueError(f"Unknown request_arrival_strategy: {self.config.request_arrival_strategy}")


    def _generate_poisson(self):
        """Poisson-Verteilung: Realistische zufällige Ankünfte"""
        requests = []

        for t in range(self.config.simulation_time):
            num_requests = np.random.poisson(self.config.request_utilization)

            for _ in range(num_requests):
                req = self._create_request(t)
                requests.append(req)

        return requests


    def _create_request(self, t):
        """
        Erstellt einen einzelnen Request mithilfe von:
        _sample_bin: Wählt jeweilige Kiste anahnd der bin_request_prob_strategy aus
        _generate_earliest_time: Generiert t_earliest basierend auf t und einer Normalverteilung
        _generate_latest_time: Generiert t_latest basierend auf t, einer Priorität und einem Rauschen
        """
        bin_id = self._sample_bin()
        t_earliest = self._generate_earliest_time(t)
        t_latest = self._generate_latest_time(t)

        req = Request(
            request_id=self.request_id,
            event_type=EventType.ARRIVAL,
            bin_id=bin_id,
            t_arrival=t,
            t_earliest=t_earliest,
            t_latest=t_latest
        )

        self.request_id += 1
        return req

    def _sample_bin(self):
        """
        Wählt eine Kiste zum Request basierend auf konfigurierter bin_request_prob_strategy aus
        Erklärung: Um zu simulieren dass manche Kisten häufiger angefragt werden, als andere
        """
        if self.config.bin_request_prob_strategy.lower() == "uniform":
            return uniform_bin_sampling(self.config.bin_num)
        
        elif self.config.bin_request_prob_strategy.lower() == "zipf":
            return zipf_bin_sampling(self.config.bin_num, self.config.zipf_parameter)
        
        else:
            raise ValueError(f"Unknown bin_request_prob_strategy: {self.config.bin_request_prob_strategy}")

    def _generate_earliest_time(self, t):
        return t + random.randint(0, 2)

    def _generate_latest_time(self, t):
        # Priorität bestimmen (75% normal, 10% urgent, 15% low)
        rand = random.random()
        if rand < 0.10:  # 10% urgent
            base_time = 3
        elif rand < 0.85:  # 75% normal
            base_time = 6
        else:  # 15% low
            base_time = 12
    
        # Noise hinzufügen (normalverteilt um 0)
        noise = int(np.random.normal(0, 0.8))
        noise = max(-2, min(2, noise))
    
        return t + base_time + noise