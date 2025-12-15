"""Abstract base class for OpenShift role binding integrations."""

from abc import ABC, abstractmethod
from typing import Any

import reconcile.openshift_base as ob
from reconcile.openshift_bindings.models import OCResource
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


class OpenShiftBindingsBase(ABC):

    @property
    @abstractmethod
    def integration_name(self) -> str:
        ...

    @property
    @abstractmethod
    def integration_version(self) -> str:
        ...

    @property
    @abstractmethod
    def resource_kind(self) -> str:
        ...

    
    def construct_user_oc_resource(
        self,
        role: str,
        user: str,
        role_kind: str = "ClusterRole",
        privileged: bool = False,
    ) -> OCResource:
        """Construct an OpenShift resource for a user binding.

        Args:
            role: The role name to bind.
            user: The username to bind the role to.
            role_kind: The kind of role ('Role' or 'ClusterRole').
            privileged: Whether this is a privileged binding.

        Returns:
            An OCResource containing the constructed OpenShift resource.
        """
        name = f"{role}-{user}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": self.resource_kind,
            "metadata": {"name": name},
            "roleRef": {"kind": role_kind, "name": role},
            "subjects": [{"kind": "User", "name": user}],
        }
        return OCResource(
            resource=OR(
                body,
                self.integration_name,
                self.integration_version,
                error_details=name,
            ),
            resource_name=name,
            privileged=privileged,
        )

    def construct_sa_oc_resource(
        self,
        role: str,
        sa_namespace: str,
        sa_name: str,
        role_kind: str = "ClusterRole",
        privileged: bool = False,
    ) -> OCResource:
        """Construct an OpenShift resource for a service account binding.

        Args:
            role: The role name to bind.
            sa_namespace: The namespace of the service account.
            sa_name: The name of the service account.
            role_kind: The kind of role ('Role' or 'ClusterRole').
            privileged: Whether this is a privileged binding.

        Returns:
            An OCResource containing the constructed OpenShift resource.
        """
        name = f"{role}-{sa_namespace}-{sa_name}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": self.resource_kind,
            "metadata": {"name": name},
            "roleRef": {"kind": role_kind, "name": role},
            "subjects": [
                {"kind": "ServiceAccount", "name": sa_name, "namespace": sa_namespace}
            ],
        }
        return OCResource(
            resource=OR(
                body,
                self.integration_name,
                self.integration_version,
                error_details=name,
            ),
            resource_name=name,
            privileged=privileged,
        )

    @abstractmethod
    def fetch_desired_state(
        self, ri: ResourceInventory | None, oc_map: ob.ClusterMap
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
    def get_resources_to_reconcile(self) -> list[dict]:
        """Return clusters (for ClusterRoleBindings) or namespaces (for RoleBindings)."""
        ...

    @abstractmethod
    def fetch_current_state(
        self,
        items: list[dict],
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> tuple[ResourceInventory, ob.ClusterMap]:
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

    def reconcile(
        self,
        dry_run: bool,
        thread_pool_size: int,
        internal: bool | None = None,
        use_jump_host: bool = True,
    ) -> tuple[ResourceInventory, ob.ClusterMap]:
        """Execute the reconciliation process.

        Args:
            dry_run: If True, don't make actual changes.
            thread_pool_size: Number of threads for parallel operations.
            internal: Filter for internal clusters.
            use_jump_host: Whether to use jump host for connections.

        Returns:
            Tuple of ResourceInventory and ClusterMap for cleanup.
        """
        ...
