"""Abstract base class for OpenShift role binding integrations."""

import sys
from abc import ABC, abstractmethod

import reconcile.openshift_base as ob
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

    def reconcile(
        self,
        dry_run: bool,
        ri: ResourceInventory,
        oc_map: OC_Map,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
    ) -> None:
        """Reconcile the integration."""
        self.fetch_desired_state(
            ri,
            support_role_ref,
            enforced_user_keys,
            allowed_clusters=set(oc_map.clusters()),
        )
        ob.publish_metrics(ri, self.integration_name)
        ob.realize_data(dry_run, oc_map, ri, self.thread_pool_size)
        if ri.has_error_registered():
            sys.exit(1)

    def get_openshift_resources(
        self, binding_spec: BindingSpec, privileged: bool = False
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
            for oc_resource_data in binding_spec.get_oc_resources()
        ]
        return oc_resources

    @abstractmethod
    def fetch_desired_state(
        self,
        ri: ResourceInventory | None,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
        allowed_clusters: set[str] | None = None,
    ) -> None:
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

        Returns:
            Tuple of ResourceInventory and ClusterMap.
        """
        ...
