class Robot:
    def __init__(self, robot_id, position=None):
        self.robot_id = robot_id
        self.position = position
        self.status = "idle"
        self.current_task = None

    def set_position(self, position):
        self.position = position

    def get_position(self):
        return self.position

    def get_status(self):
        return self.status

    def set_status(self, status):
        self.status = status

    def assign_task(self, request_id):
        self.current_task = request_id
        self.status = "busy"

    def clear_task(self):
        self.current_task = None
        self.status = "idle"


    def __repr__(self):
        return f"Robot(id={self.robot_id}, status={self.status}, task={self.current_task})"