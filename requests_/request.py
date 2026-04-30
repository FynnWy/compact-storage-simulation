# reuests_/request.py
class Request:
    def __init__(self, request_id, event_type, bin_id, t_arrival, t_earliest, t_latest):
        self.request_id = request_id
        self.event_type = event_type
        self.target_box_id = bin_id
        self.arrival_time = t_arrival
        self.earliest_time = t_earliest
        self.latest_time = t_latest

    def __lt__(self, other):
        if not isinstance(other, Request):
            return NotImplemented
        return self.request_id < other.request_id

    def __repr__(self):
        return (
            f"Request(id={self.request_id}, "
            f"type={self.event_type.value}, "
            f"target_bin={self.target_box_id}, "
            f"arrival_time={self.arrival_time}, "
            f"earliest_time={self.earliest_time}, "
            f"latest_time={self.latest_time})"
        )