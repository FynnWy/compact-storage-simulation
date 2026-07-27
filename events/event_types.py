from enum import Enum


class EventType(Enum):
    ARRIVAL = "arrival"
    ROBOT_ACTION = "robot_action"
    PICKSTATION_COMPLETE = "pickstation_complete"
    REQUEST_COMPLETE = "request_complete"
    ROBOT_MOVE = "ROBOT_MOVE"

    # NEU: Zwei-Phasen-Aktionen
    ROBOT_PICKUP = "robot_pickup"  # Roboter nimmt Bin auf
    ROBOT_DROP = "robot_drop"  # Roboter legt Bin ab