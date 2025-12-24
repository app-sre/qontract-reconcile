"""Abstract base class for OpenShift role binding integrations."""

from abc import ABC, abstractmethod

from reconcile.openshift_bindings.models import BindingSpec, OCResource
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


class OpenShiftBindingsBase(ABC):
    def __init__(
        self,
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> None:
        self.thread_pool_size = thread_pool_size
        self.internal = internal
        self.use_jump_host = use_jump_host

    @property
    @abstractmethod
    def integration_name(self) -> str: ...

    @property
    @abstractmethod
    def integration_version(self) -> str: ...

    @property
    @abstractmethod
    def resource_kind(self) -> str: ...

    @abstractmethod
    def reconcile(
        self,
        dry_run: bool,
        ri: ResourceInventory,
        oc_map: OC_Map,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
    ) -> None:
        """Reconcile the integration."""
        ...

    def get_openshift_resources(
        self, binding_spec: BindingSpec, resource_kind: str,privileged: bool = False
    ) -> list[OCResource]:
        """Get the OpenShift resources for the binding specification."""
        oc_resources = [
            OCResource(
                resource=OR(
                    oc_resource_data.body,
                    self.integration_name,
                    self.integration_version,
                    error_details=oc_resource_data.name,
                ),
                resource_name=oc_resource_data.name,
                privileged=privileged,
            )
            for oc_resource_data in binding_spec.get_oc_resources(resource_kind=resource_kind)
        ]
        return oc_resources

    @abstractmethod
    def fetch_desired_state(
        self,
        ri: ResourceInventory | None,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
        allowed_clusters: set[str] | None = None,
    ) -> list[dict[str, str]]:
        """Fetch and populate the desired state.

        Args:
            ri: ResourceInventory to populate with desired state.
            oc_map: Map of OpenShift cluster connections.

        Returns:
            List of user desired state dictionaries.
        """
        ...

    @abstractmethod
    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        """Fetch current state from OpenShift.

        Args:
            items: List of clusters or namespaces to fetch state from.
            thread_pool_size: Number of threads for parallel operations.
            internal: Filter for internal clusters.
            use_jump_host: Whether to use jump host for connections.

        Returns:
            Tuple of ResourceInventory and ClusterMap.
        """
        ...
