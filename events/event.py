class Event:
    _next_event_id = 0

    def __init__(self, time, event_type, payload, retry_count=0, priority=0):
        self.event_id = Event._next_event_id
        Event._next_event_id += 1

        self.time = time
        self.event_type = event_type
        self.payload = payload
        self.retry_count = retry_count
        self.priority = priority

    def __lt__(self, other):
        return (
            self.time,
            self.priority,
            self.event_id,
        ) < (
            other.time,
            other.priority,
            other.event_id,
        )

    def __repr__(self):
        return (
            f"Event(id={self.event_id}, "
            f"t={self.time}, "
            f"type={self.event_type.value}, "
            f"retry_count={self.retry_count}, "
            f"priority={self.priority})"
        )