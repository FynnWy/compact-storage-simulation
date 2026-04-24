class Event:
    def __init__(self, time, event_type, payload):
        self.time = time
        self.event_type = event_type
        self.payload = payload

    def __lt__(self, other):
        return self.time < other.time

    def __repr__(self):
        return f"Event(t={self.time}, type={self.event_type})"