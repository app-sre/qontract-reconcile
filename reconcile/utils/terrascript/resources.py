from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable

from terrascript import (
    Data,
    Output,
    Resource,
)

from reconcile.utils.external_resource_spec import ExternalResourceSpec


class TerrascriptResource(ABC):
    """
    Base class for creating Terrascript resources. New resources are added by
    subclassing this class and implementing the logic to return the required Terrascript
    resource objects.

    Note: each populate_tf_resource_<resource_name> methods in the TerrascriptAwsClient
    is a separate class using this pattern. This means that each class that implements
    TerrascriptResource can result in N resources being created if it makes sense to
    implicitly created certain resources.
    """

    def __init__(self, spec: ExternalResourceSpec) -> None:
        self._spec = spec

    @staticmethod
    def _get_dependencies(tf_resources: Iterable[Resource]) -> list[str]:
        """
        Formats the dependency name properly for use with depends_on configuration.
        """
        return [
            f"{tf_resource.__class__.__name__}.{tf_resource._name}"
            for tf_resource in tf_resources
        ]

    @abstractmethod
    def populate(self) -> list[Resource | Output | Data]:
        """Calling this method should return the Terrascript resources to be created."""
