from enum import Enum


class EventType(Enum):
    ARRIVAL = "arrival"
    ROBOT_ACTION = "robot_action"
    PICKSTATION_COMPLETE = "pickstation_complete"
    REQUEST_COMPLETE = "request_complete"
    ROBOT_MOVE = "ROBOT_MOVE"