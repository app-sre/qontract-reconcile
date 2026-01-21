"""Shared fixtures for openshift_bindings tests."""

import pytest

from reconcile.gql_definitions.common.app_interface_clusterrole import (
    AccessV1 as ClusterAccessV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    BotV1 as ClusterBotV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    ClusterAuthV1 as ClusterRoleClusterAuthV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    ClusterV1 as ClusterRoleClusterV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    RoleV1 as ClusterRoleV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    UserV1 as ClusterUserV1,
)
from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterAuthV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.openshift_bindings.openshift_clusterrolebindings import (
    OpenShiftClusterRoleBindingsIntegration,
    OpenShiftClusterRoleBindingsIntegrationParams,
)
from reconcile.openshift_bindings.openshift_rolebindings import (
    OpenShiftRoleBindingsIntegration,
    OpenShiftRoleBindingsIntegrationParams,
)

# ============================================================================
# Cluster Auth Fixtures
# ============================================================================


@pytest.fixture
def cluster_auth_rhidp() -> ClusterAuthV1:
    """RHIDP authentication service."""
    return ClusterAuthV1(service="rhidp")


@pytest.fixture
def cluster_role_auth_rhidp() -> ClusterRoleClusterAuthV1:
    """RHIDP authentication for cluster roles."""
    return ClusterRoleClusterAuthV1(service="rhidp")


# ============================================================================
# Cluster Fixtures
# ============================================================================


@pytest.fixture
def test_cluster(cluster_auth_rhidp: ClusterAuthV1) -> ClusterV1:
    """Standard test cluster with RHIDP auth."""
    return ClusterV1(name="test-cluster", auth=[cluster_auth_rhidp])


@pytest.fixture
def test_cluster_role_cluster(
    cluster_role_auth_rhidp: ClusterRoleClusterAuthV1,
) -> ClusterRoleClusterV1:
    """Cluster for ClusterRoleBinding tests."""
    return ClusterRoleClusterV1(name="test-cluster", auth=[cluster_role_auth_rhidp])


# ============================================================================
# Namespace Fixtures
# ============================================================================


@pytest.fixture
def test_namespace(test_cluster: ClusterV1) -> NamespaceV1:
    """Standard test namespace with managed roles."""
    return NamespaceV1(
        name="test-namespace",
        clusterAdmin=False,
        managedRoles=True,
        cluster=test_cluster,
        delete=False,
    )


@pytest.fixture
def test_namespace_no_managed_roles(test_cluster: ClusterV1) -> NamespaceV1:
    """Namespace without managed roles."""
    return NamespaceV1(
        name="test-namespace-no-managed",
        clusterAdmin=False,
        managedRoles=False,
        cluster=test_cluster,
        delete=False,
    )


# ============================================================================
# User Fixtures
# ============================================================================


@pytest.fixture
def test_user() -> UserV1:
    """Standard test user."""
    return UserV1(org_username="test-org-user", github_username="test-github-user")


@pytest.fixture
def test_user_2() -> UserV1:
    """Second test user for multi-user tests."""
    return UserV1(org_username="test-org-user-2", github_username="test-github-user-2")


@pytest.fixture
def test_cluster_user() -> ClusterUserV1:
    """User for ClusterRoleBinding tests."""
    return ClusterUserV1(
        org_username="test-cluster-user", github_username="test-cluster-github"
    )


# ============================================================================
# Bot Fixtures
# ============================================================================


@pytest.fixture
def test_bot() -> BotV1:
    """Bot with valid service account."""
    return BotV1(openshift_serviceaccount="test-namespace/test-sa")


@pytest.fixture
def test_bot_no_sa() -> BotV1:
    """Bot without service account."""
    return BotV1(openshift_serviceaccount=None)


@pytest.fixture
def test_bot_invalid_sa() -> BotV1:
    """Bot with invalid service account format."""
    return BotV1(openshift_serviceaccount="invalid-no-slash")


@pytest.fixture
def test_cluster_bot() -> ClusterBotV1:
    """Bot for ClusterRoleBinding tests."""
    return ClusterBotV1(openshift_serviceaccount="cluster-ns/cluster-sa")


# ============================================================================
# Access Fixtures
# ============================================================================


@pytest.fixture
def test_access_with_role(test_namespace: NamespaceV1) -> AccessV1:
    """Access with namespace-scoped role."""
    return AccessV1(namespace=test_namespace, role="test-role", clusterRole=None)


@pytest.fixture
def test_access_with_cluster_role(test_namespace: NamespaceV1) -> AccessV1:
    """Access with cluster role reference."""
    return AccessV1(
        namespace=test_namespace, role=None, clusterRole="test-cluster-role"
    )


@pytest.fixture
def test_access_no_role(test_namespace: NamespaceV1) -> AccessV1:
    """Access without role or cluster role."""
    return AccessV1(namespace=test_namespace, role=None, clusterRole=None)


@pytest.fixture
def test_cluster_access(
    test_cluster_role_cluster: ClusterRoleClusterV1,
) -> ClusterAccessV1:
    """Access for ClusterRoleBinding."""
    return ClusterAccessV1(
        cluster=test_cluster_role_cluster, clusterRole="test-cluster-role"
    )


# ============================================================================
# Role Fixtures
# ============================================================================


@pytest.fixture
def test_role(
    test_user: UserV1, test_bot: BotV1, test_access_with_role: AccessV1
) -> RoleV1:
    """Complete role with users, bots, and access."""
    return RoleV1(
        name="test-role",
        users=[test_user],
        bots=[test_bot],
        access=[test_access_with_role],
        expirationDate=None,
    )


@pytest.fixture
def test_cluster_role(
    test_cluster_user: ClusterUserV1,
    test_cluster_bot: ClusterBotV1,
    test_cluster_access: ClusterAccessV1,
) -> ClusterRoleV1:
    """Complete cluster role."""
    return ClusterRoleV1(
        name="test-cluster-role",
        users=[test_cluster_user],
        bots=[test_cluster_bot],
        access=[test_cluster_access],
        expirationDate=None,
    )


# ============================================================================
# Integration Fixtures
# ============================================================================


@pytest.fixture
def rolebindings_integration() -> OpenShiftRoleBindingsIntegration:
    """OpenShiftRoleBindingsIntegration instance."""
    params = OpenShiftRoleBindingsIntegrationParams()
    return OpenShiftRoleBindingsIntegration(params)


@pytest.fixture
def clusterrolebindings_integration() -> OpenShiftClusterRoleBindingsIntegration:
    """OpenShiftClusterRoleBindingsIntegration instance."""
    params = OpenShiftClusterRoleBindingsIntegrationParams()
    return OpenShiftClusterRoleBindingsIntegration(params)


# ============================================================================
# Vault Secret Fixtures
# ============================================================================


@pytest.fixture
def test_vault_secret() -> VaultSecret:
    """Standard vault secret for automation token."""
    return VaultSecret(
        path="secret/path",
        field="token",
        version=None,
        format=None,
    )


# ============================================================================
# Mock OC_Map Fixtures
# ============================================================================


class MockOCMap:
    """Mock OC_Map for testing."""

    def __init__(self, cluster_names: list[str] | None = None) -> None:
        self._clusters = cluster_names or ["test-cluster"]
        self._cleanup_called = False

    def clusters(self) -> list[str]:
        """Return list of cluster names."""
        return self._clusters

    def cleanup(self) -> None:
        """Mark cleanup as called."""
        self._cleanup_called = True


@pytest.fixture
def mock_oc_map() -> MockOCMap:
    """MockOCMap instance for testing."""
    return MockOCMap()


# ============================================================================
# Mock Query Cluster Fixtures
# ============================================================================


class MockQueryCluster:
    """Mock cluster for get_clusters query results."""

    def __init__(
        self,
        name: str = "test-cluster",
        managed_cluster_roles: bool = True,
        automation_token: VaultSecret | None = None,
    ) -> None:
        self.name = name
        self.managed_cluster_roles = managed_cluster_roles
        self.automation_token = automation_token

    def model_dump(self, by_alias: bool = False) -> dict:
        """Return dict representation."""
        return {
            "name": self.name,
            "managedClusterRoles": self.managed_cluster_roles,
        }


@pytest.fixture
def query_cluster_with_managed_roles(
    test_vault_secret: VaultSecret,
) -> MockQueryCluster:
    """Query cluster with managed_cluster_roles=True and automation_token."""
    return MockQueryCluster(
        name="test-cluster",
        managed_cluster_roles=True,
        automation_token=test_vault_secret,
    )


@pytest.fixture
def query_cluster_without_managed_roles(
    test_vault_secret: VaultSecret,
) -> MockQueryCluster:
    """Query cluster with managed_cluster_roles=False."""
    return MockQueryCluster(
        name="test-cluster-no-managed",
        managed_cluster_roles=False,
        automation_token=test_vault_secret,
    )


@pytest.fixture
def query_cluster_without_token() -> MockQueryCluster:
    """Query cluster without automation_token."""
    return MockQueryCluster(
        name="test-cluster-no-token",
        managed_cluster_roles=True,
        automation_token=None,
    )
