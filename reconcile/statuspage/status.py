from abc import (
    ABC,
    abstractmethod,
)
from datetime import (
    datetime,
    timezone,
)
from typing import Optional

from dateutil.parser import isoparse
from pydantic import BaseModel

from reconcile.gql_definitions.statuspage.statuspages import (
    ManualStatusProviderV1,
    StatusProviderV1,
)

# This module defines the interface for status providers for components on status
# pages. A status provider is responsible for determining the status of a component.
# This status will then be used to update the status page component.


class StatusProvider(ABC):
    """
    The generic static provider interface that can be used to determine the
    status of a component.
    """

    @abstractmethod
    def get_status(self) -> Optional[str]: ...


class ManualStatusProvider(StatusProvider, BaseModel):
    """
    This status provider is used to manually define the status of a component.
    An optional time windows can be defined in which the status is applied to
    the component.
    """

    start: Optional[datetime] = None
    """
    The optional start time of the time window in which the manually
    defined status is active.
    """

    end: Optional[datetime] = None
    """
    The optional end time of the time window in which the manually
    defined status is active.
    """

    component_status: str
    """
    The status to be used for the component if the
    time window is active or if no time window is defined.
    """

    def get_status(self) -> Optional[str]:
        if self._is_active():
            return self.component_status
        return None

    def _is_active(self) -> bool:
        """
        Returns true if the config is active in regards to the start and
        end time window. If no time window is defined, the config is always
        active.
        """
        if self.start and self.end and self.end < self.start:
            raise ValueError(
                "manual component status time window is invalid: end before start"
            )
        now = datetime.now(timezone.utc)
        if self.start and now < self.start:
            return False
        if self.end and self.end < now:
            return False
        return True


def build_status_provider_config(
    cfg: StatusProviderV1,
) -> Optional[StatusProvider]:
    """
    Translates a status provider config from the desired state into
    provider specific implementation that provides the status resolution logic.
    """
    if isinstance(cfg, ManualStatusProviderV1):
        start = isoparse(cfg.manual.q_from) if cfg.manual.q_from else None
        end = isoparse(cfg.manual.until) if cfg.manual.until else None
        return ManualStatusProvider(
            component_status=cfg.manual.component_status,
            start=start,
            end=end,
        )
    return None
