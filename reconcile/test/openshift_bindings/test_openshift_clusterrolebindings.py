"""Tests for reconcile.openshift_bindings.openshift_clusterrolebindings module."""

from pytest_mock import MockerFixture

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
from reconcile.openshift_bindings.models import ClusterRoleBindingSpec, OCResource
from reconcile.openshift_bindings.openshift_clusterrolebindings import (
    NAMESPACE_CLUSTER_SCOPE,
    QONTRACT_INTEGRATION_MANAGED_TYPE,
    QONTRACT_INTEGRATION_VERSION,
    OpenShiftClusterRoleBindingsIntegration,
)
from reconcile.test.openshift_bindings.conftest import MockOCMap, MockQueryCluster
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


def get_app_interface_test_cluster_roles() -> list[ClusterRoleV1]:
    """Get test cluster roles for testing."""
    return [
        ClusterRoleV1(
            name="test-cluster-role",
            users=[
                ClusterUserV1(
                    org_username="test-org-user", github_username="test-github-user"
                ),
            ],
            bots=[
                ClusterBotV1(
                    openshift_serviceaccount="test-namespace/test-serviceaccount"
                )
            ],
            access=[
                ClusterAccessV1(
                    cluster=ClusterRoleClusterV1(
                        name="test-cluster",
                        auth=[ClusterRoleClusterAuthV1(service="rhidp")],
                    ),
                    clusterRole="test-cluster-role",
                ),
            ],
            expirationDate=None,
        ),
        ClusterRoleV1(
            name="test-cluster-role-2",
            users=[
                ClusterUserV1(
                    org_username="test-org-user-2",
                    github_username="test-github-user-2",
                ),
            ],
            bots=[],
            access=[
                ClusterAccessV1(
                    cluster=ClusterRoleClusterV1(
                        name="test-cluster-2",
                        auth=[ClusterRoleClusterAuthV1(service="rhidp")],
                    ),
                    clusterRole="test-cluster-role-2",
                ),
            ],
            expirationDate=None,
        ),
        ClusterRoleV1(
            name="expired-cluster-role",
            users=[
                ClusterUserV1(
                    org_username="test-org-user-3",
                    github_username="test-github-user-3",
                )
            ],
            bots=[],
            access=[
                ClusterAccessV1(
                    cluster=ClusterRoleClusterV1(
                        name="test-cluster-3",
                        auth=[ClusterRoleClusterAuthV1(service="rhidp")],
                    ),
                    clusterRole="expired-cluster-role",
                )
            ],
            expirationDate="2023-07-10",
        ),
    ]


class TestGetOcResources:
    """Tests for ClusterRoleBindingSpec.get_openshift_resources."""

    def test_get_oc_resources(self, mocker: MockerFixture) -> None:
        """Test get_openshift_resources generates correct ClusterRoleBindings."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        test_cluster_roles = get_app_interface_test_cluster_roles()
        cluster_role_binding_specs = (
            ClusterRoleBindingSpec.create_cluster_role_binding_specs(
                test_cluster_roles[0]
            )
        )
        oc_resources = cluster_role_binding_specs[0].get_openshift_resources(
            integration_name="openshift-clusterrolebindings",
            integration_version=QONTRACT_INTEGRATION_VERSION,
        )

        assert len(oc_resources) == 2
        assert oc_resources[0] == OCResource(
            resource=OR(
                integration="openshift-clusterrolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-cluster-role-test-org-user",
                body={
                    "kind": "ClusterRoleBinding",
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "metadata": {
                        "name": "test-cluster-role-test-org-user",
                    },
                    "roleRef": {
                        "kind": "ClusterRole",
                        "name": "test-cluster-role",
                    },
                    "subjects": [
                        {
                            "kind": "User",
                            "name": "test-org-user",
                        }
                    ],
                },
            ),
            resource_name="test-cluster-role-test-org-user",
            privileged=False,
        )
        assert oc_resources[1] == OCResource(
            resource=OR(
                integration="openshift-clusterrolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-cluster-role-test-namespace-test-serviceaccount",
                body={
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRoleBinding",
                    "metadata": {
                        "name": "test-cluster-role-test-namespace-test-serviceaccount",
                    },
                    "roleRef": {
                        "kind": "ClusterRole",
                        "name": "test-cluster-role",
                    },
                    "subjects": [
                        {
                            "kind": "ServiceAccount",
                            "name": "test-serviceaccount",
                            "namespace": "test-namespace",
                        },
                    ],
                },
            ),
            resource_name="test-cluster-role-test-namespace-test-serviceaccount",
            privileged=False,
        )


class TestOpenShiftClusterRoleBindingsIntegrationFetchCurrentState:
    """Tests for OpenShiftClusterRoleBindingsIntegration.fetch_current_state."""

    def test_fetch_current_state(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_current_state calls ob.fetch_current_state correctly."""
        ri = ResourceInventory()
        oc_map = MockOCMap()

        mock_get_clusters = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_clusters",
            return_value=[],
        )
        mock_fetch = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.fetch_current_state",
            return_value=(ri, oc_map),
        )

        result_ri, result_oc_map = clusterrolebindings_integration.fetch_current_state()

        assert result_ri == ri
        assert result_oc_map == oc_map
        mock_get_clusters.assert_called_once()
        mock_fetch.assert_called_once()

    def test_fetch_current_state_filters_clusters(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        query_cluster_with_managed_roles: MockQueryCluster,
        query_cluster_without_managed_roles: MockQueryCluster,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_current_state filters clusters without managed_cluster_roles."""
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_clusters",
            return_value=[
                query_cluster_with_managed_roles,
                query_cluster_without_managed_roles,
            ],
        )
        mock_fetch = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.fetch_current_state",
            return_value=(ResourceInventory(), MockOCMap()),
        )

        clusterrolebindings_integration.fetch_current_state()

        call_kwargs = mock_fetch.call_args.kwargs
        assert "clusters" in call_kwargs
        # Only the cluster with managed_cluster_roles should be included
        assert len(call_kwargs["clusters"]) == 1

    def test_fetch_current_state_filters_clusters_without_automation_token(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        query_cluster_with_managed_roles: MockQueryCluster,
        query_cluster_without_token: MockQueryCluster,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_current_state filters clusters without automation_token."""
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_clusters",
            return_value=[
                query_cluster_with_managed_roles,
                query_cluster_without_token,
            ],
        )
        mock_fetch = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.fetch_current_state",
            return_value=(ResourceInventory(), MockOCMap()),
        )

        clusterrolebindings_integration.fetch_current_state()

        call_kwargs = mock_fetch.call_args.kwargs
        assert "clusters" in call_kwargs
        assert len(call_kwargs["clusters"]) == 1


class TestOpenShiftClusterRoleBindingsIntegrationFetchDesiredState:
    """Tests for OpenShiftClusterRoleBindingsIntegration.fetch_desired_state."""

    def test_fetch_desired_state_empty_allowed_clusters(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_desired_state returns early when allowed_clusters is empty."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles"
        ).return_value = get_app_interface_test_cluster_roles()

        clusterrolebindings_integration.fetch_desired_state(ri, allowed_clusters=set())

        assert not ri.get_desired(
            "test-cluster",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-cluster-role-test-org-user",
        )

    def test_fetch_desired_state_none_ri(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
    ) -> None:
        """Test fetch_desired_state returns early when ri is None."""
        # Should not raise any exception
        clusterrolebindings_integration.fetch_desired_state(
            None, allowed_clusters={"test-cluster"}
        )

    def test_fetch_desired_state_contents_with_filtered_clusters(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_desired_state populates ResourceInventory with filtered clusters."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        ri.initialize_resource_type(
            "test-cluster-2", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.expiration.filter",
            side_effect=lambda x: [r for r in x if r.expiration_date is None],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles"
        ).return_value = get_app_interface_test_cluster_roles()
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        clusterrolebindings_integration.fetch_desired_state(
            ri, allowed_clusters={"test-cluster"}
        )

        assert ri.get_desired(
            "test-cluster",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-cluster-role-test-org-user",
        )
        assert not ri.get_desired(
            "test-cluster-2",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-cluster-role-2-test-org-user-2",
        )

    def test_fetch_desired_state_contents_without_filtered_clusters(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_desired_state populates ResourceInventory without cluster filter."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        ri.initialize_resource_type(
            "test-cluster-2", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.expiration.filter",
            side_effect=lambda x: [r for r in x if r.expiration_date is None],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles"
        ).return_value = get_app_interface_test_cluster_roles()
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        clusterrolebindings_integration.fetch_desired_state(
            ri, allowed_clusters={"test-cluster", "test-cluster-2"}
        )

        assert ri.get_desired(
            "test-cluster",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-cluster-role-test-org-user",
        )
        assert ri.get_desired(
            "test-cluster-2",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-cluster-role-2-test-org-user-2",
        )

    def test_fetch_desired_state_filters_expired_roles(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test fetch_desired_state filters expired cluster roles."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster-3", NAMESPACE_CLUSTER_SCOPE, QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.expiration.filter",
            side_effect=lambda x: [r for r in x if r.expiration_date is None],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.get_app_interface_clusterroles"
        ).return_value = get_app_interface_test_cluster_roles()
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        clusterrolebindings_integration.fetch_desired_state(
            ri, allowed_clusters={"test-cluster-3"}
        )

        # Expired role should not be in desired state
        assert not ri.get_desired(
            "test-cluster-3",
            NAMESPACE_CLUSTER_SCOPE,
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "expired-cluster-role-test-org-user-3",
        )


class TestOpenShiftClusterRoleBindingsIntegrationRun:
    """Tests for OpenShiftClusterRoleBindingsIntegration.run."""

    def test_run_calls_expected_methods(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test run calls fetch_current_state, fetch_desired_state, and realize_data."""
        ri = ResourceInventory()
        oc_map = MockOCMap()

        mocker.patch.object(
            clusterrolebindings_integration,
            "fetch_current_state",
            return_value=(ri, oc_map),
        )
        mock_fetch_desired = mocker.patch.object(
            clusterrolebindings_integration, "fetch_desired_state", return_value=None
        )
        mock_publish = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.publish_metrics"
        )
        mock_realize = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.realize_data"
        )

        clusterrolebindings_integration.run(dry_run=True)

        mock_fetch_desired.assert_called_once()
        mock_publish.assert_called_once()
        mock_realize.assert_called_once()

    def test_run_exits_on_error(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test run exits with code 1 when errors registered."""
        ri = ResourceInventory()
        ri.register_error()
        oc_map = MockOCMap()

        mocker.patch.object(
            clusterrolebindings_integration,
            "fetch_current_state",
            return_value=(ri, oc_map),
        )
        mocker.patch.object(
            clusterrolebindings_integration, "fetch_desired_state", return_value=None
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.publish_metrics"
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.realize_data"
        )
        mock_exit = mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.sys.exit"
        )

        clusterrolebindings_integration.run(dry_run=True)

        mock_exit.assert_called_once_with(1)

    def test_run_calls_oc_map_cleanup(
        self,
        clusterrolebindings_integration: OpenShiftClusterRoleBindingsIntegration,
        mocker: MockerFixture,
    ) -> None:
        """Test run defers oc_map cleanup."""
        ri = ResourceInventory()
        oc_map = MockOCMap()

        mocker.patch.object(
            clusterrolebindings_integration,
            "fetch_current_state",
            return_value=(ri, oc_map),
        )
        mocker.patch.object(
            clusterrolebindings_integration, "fetch_desired_state", return_value=None
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.publish_metrics"
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_clusterrolebindings.ob.realize_data"
        )

        clusterrolebindings_integration.run(dry_run=True)

        # The cleanup should be called due to @defer decorator
        assert oc_map._cleanup_called
