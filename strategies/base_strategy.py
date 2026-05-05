from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """
    Base class for all storage access strategies.

    A strategy creates an abstract action plan.
    Every plan ends with a request_complete action.
    """

    def plan(self, state, request):
        """
        Create a complete plan for a request.

        Subclasses create the physical actions in `_create_plan`.
        The final request_complete action is appended here centrally.
        """
        plan = self._create_plan(state, request)
        plan.append(self._create_request_complete_action(request))
        return plan

    @abstractmethod
    def _create_plan(self, state, request):
        """
        Create the physical action plan for a request.

        Subclasses must not append request_complete themselves.
        """
        raise NotImplementedError("Subclasses must implement the _create_plan method.")

    def _create_request_complete_action(self, request):
        return {
            "type": "request_complete",
            "request_id": request.request_id,
            "bin_id": request.target_box_id,
        }