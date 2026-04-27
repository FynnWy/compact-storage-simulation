# reuests_/request.py

class Request:
    def __init__(self, request_id, bin_id, t_arrival, t_earliest, t_latest):
        self.request_id = request_id
        self.target_box_id = bin_id
        self.arrival_time = t_arrival
        self.earliest_time = t_earliest
        self.latest_time = t_latest

    def __lt__(self, other):
        if not isinstance(other, Request):
            return NotImplemented
        return self.request_id < other.request_id

    def __repr__(self):
        return f"Request(id={self.request_id}, target_bin={self.target_box_id}, arrival_time={self.arrival_time}, earliest_time={self.earliest_time}, latest_time={self.latest_time})"