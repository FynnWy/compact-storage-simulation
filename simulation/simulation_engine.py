# simulation/simulation_engine.py

import math
import numpy as np

from config.init_strategy import initialize_bins
from requests_.request_generator import RequestGenerator
from state.bin import Bin
from state.request_queue import FutureRequestQueue
from state.state import State
from state.storage_grid import StorageGrid


class SimulationEngine:
    def __init__(self, config):
        self.config = config
        self.rng = np.random.default_rng(self.config.random_seed)

        self.state = None
        self.hot_bin_ids = []

        self._initialize_state()

    def _initialize_state(self):
        """
        Erstellt Grid, Bins, Requests und initialisiert das Lager
        gemäß der gewählten Strategie.
        """
        grid = StorageGrid(self.config.grid_width, self.config.grid_depth)
        bins = self._create_bins(self.config.bin_num)
        future_request_queue = self._create_future_request_queue()

        self.hot_bin_ids = self._determine_hot_bin_ids()

        initialize_bins(
            grid=grid,
            bins=bins,
            init_strategy=self._resolve_init_strategy(),
            hot_bin_ids=self.hot_bin_ids,
            random_seed=self.config.random_seed,
        )

        self.state = State(
            grid=grid,
            bins=bins,
            future_request_queue=future_request_queue,
        )
        self.state.mark_initialized()

    def _create_bins(self, bin_num):
        """
        Erstellt alle Bins ohne feste Platzierung.
        """
        bins = []
        for bin_id in range(bin_num):
            bin_obj = Bin(
                bin_id=bin_id,
                stack_id=None,
                # stack_level=None,
                level=None,
                status="not_locked",
            )
            bins.append(bin_obj)
        return bins

    def _create_future_request_queue(self):
        """
        Generiert alle Requests vorab und speichert sie in der Future-Queue.
        """
        request_generator = RequestGenerator(self.config)
        requests = request_generator.generate_requests()

        future_queue = FutureRequestQueue()
        for request in requests:
            future_queue.push(request)

        return future_queue

    def _determine_hot_bin_ids(self):
        """
        Ermittelt Hot Items aus der Request-Strategie.
        """
        if self.config.bin_request_prob_strategy.lower() != "zipf":
            return []

        hot_fraction = 0.2
        hot_count = max(1, math.ceil(self.config.bin_num * hot_fraction))
        return list(range(hot_count))

    def _resolve_init_strategy(self):
        if self.config.init_strategy == "uniform":
            return "uniform"

        if self.config.init_strategy == "hot_items_top":
            return "hot_items_top"

        raise ValueError(f"Unknown init_strategy: {self.config.init_strategy}")

    def is_ready(self):
        return self.state is not None and self.state.is_initialized()