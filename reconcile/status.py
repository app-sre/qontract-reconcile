from typing import Any


class ExitCodes:
    SUCCESS = 0
    ERROR = 1
    INTEGRATION_NOT_FOUND = 4
    FORBIDDEN_SCHEMA = 5


class _RunningState:

    _state: dict[Any, Any] = {}

    def __init__(self):
        self.__dict__ = self._state


class RunningState(_RunningState):
    """
    Simple Borg class to share information about
    the running state. Attributes will be populated
    by the callers.
    """

    def __getattr__(self, item):
        """
        Default value for attributes not explicitly created is None.
        """
