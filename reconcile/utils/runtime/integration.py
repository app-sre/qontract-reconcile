from abc import (
    ABC,
    abstractmethod,
)
from types import ModuleType
from typing import (
    Any,
    Optional,
)


class QontractReconcileIntegration(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def get_early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ...

    @abstractmethod
    def run(self, dry_run: bool, *args: Any, **kwargs: Any) -> None:
        ...


RUN_FUNCTION = "run"
EARLY_EXIT_DESIRED_STATE_FUNCTION = "early_exit_desired_state"


class ModuleBasedQontractReconcileIntegration(QontractReconcileIntegration):
    def __init__(self, module: ModuleType):
        self._module = module
        self.name  # run to check if the name can be extracted from the module
        if not self._integration_supports(RUN_FUNCTION):
            raise NotImplementedError(f"Integration has no {RUN_FUNCTION}() function")

    def _integration_supports(self, func_name: str) -> bool:
        return func_name in dir(self._module)

    @property
    def name(self) -> str:
        try:
            return self._module.QONTRACT_INTEGRATION.replace("_", "-")
        except AttributeError:
            raise NotImplementedError("Integration missing QONTRACT_INTEGRATION.")

    def get_early_exit_desired_state(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if self._integration_supports(EARLY_EXIT_DESIRED_STATE_FUNCTION):
            return self._module.early_exit_desired_state(*args, **kwargs)
        else:
            raise NotImplementedError("Integration does not support early exit.")

    def run(self, dry_run: bool, *args: Any, **kwargs: Any) -> None:
        self._module.run(dry_run, *args, **kwargs)
