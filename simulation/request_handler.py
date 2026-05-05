class RequestHandler:
    def __init__(self, state, event_builder):
        self.state = state
        self.event_builder = event_builder

    def add_ready_requests_to_event_queue(self):
        """
        Holt alle Requests, die bis zur aktuellen Simulationszeit angekommen sind,
        aus der FutureRequestQueue und legt sie als ARRIVAL-Events in die EventQueue.

        Der RequestGenerator erzeugt weiterhin nur Request-Objekte.
        Die konkrete Event-Erzeugung ist im EventBuilder gekapselt.
        """
        if self.state.future_request_queue is None:
            return []

        if self.state.event_queue is None:
            raise ValueError("State has no event_queue.")

        ready_requests = self.state.future_request_queue.pop_ready(self.state.t)

        for request in ready_requests:
            arrival_event = self.event_builder.build_arrival_event(request)
            self.state.event_queue.push(arrival_event)

        return ready_requests