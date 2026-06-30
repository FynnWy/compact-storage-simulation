from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """
    Base class for all storage access strategies.

    Neuer Standard:
    Eine Strategie plant genau die nächste Aktion für einen aktiven Task.

    Legacy:
    Die vollständige Planerzeugung bleibt vorerst vorhanden, wird im neuen
    Next-Step-Flow aber nicht mehr verwendet.
    """

    @abstractmethod
    def next_action(self, state, task):
        """
        Create exactly one next action for the given task.
        """
        raise NotImplementedError("Subclasses must implement next_action.")

    def plan(self, state, request):
        """
        Legacy: Create a complete plan for a request.

        Der neue Scheduler nutzt diese Methode nicht mehr.
        """
        plan = self._create_plan(state, request)
        plan.append(self._create_request_complete_action(request))
        return plan

    @abstractmethod
    def _create_plan(self, state, request):
        """
        Legacy: Create the physical action plan for a request.
        """
        raise NotImplementedError("Subclasses must implement the _create_plan method.")

    def _create_request_complete_action(self, request):
        return {
            "type": "request_complete",
            "request_id": request.request_id,
            "bin_id": request.target_box_id,
        }