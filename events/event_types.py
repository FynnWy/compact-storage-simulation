from enum import Enum


class EventType(Enum):
    ARRIVAL = "arrival"
    ROBOT_ACTION = "robot_action"
    REQUEST_COMPLETE = "request_complete"