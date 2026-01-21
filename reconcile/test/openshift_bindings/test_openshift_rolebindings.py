"""Tests for reconcile.openshift_bindings.openshift_rolebindings module."""

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterAuthV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.openshift_bindings.models import OCResource, RoleBindingSpec
from reconcile.openshift_bindings.openshift_rolebindings import (
    QONTRACT_INTEGRATION_MANAGED_TYPE,
    QONTRACT_INTEGRATION_VERSION,
    OpenShiftRoleBindingsIntegration,
    OpenShiftRoleBindingsIntegrationParams,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


def get_app_interface_test_roles() -> list[RoleV1]:
    """Get test roles for testing."""
    return [
        RoleV1(
            name="test-role5",
            users=[
                UserV1(
                    org_username="test-org-user", github_username="test-github-user"
                ),
            ],
            bots=[
                BotV1(openshift_serviceaccount="test-namespace5/test-serviceaccount")
            ],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace5",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster5", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role5",
                    clusterRole=None,
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="test-role",
            users=[
                UserV1(
                    org_username="test-org-user", github_username="test-github-user"
                ),
                UserV1(
                    org_username="test-org-user-2", github_username="test-github-user-2"
                ),
            ],
            bots=[],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role-access",
                    clusterRole=None,
                ),
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace",
                        clusterAdmin=True,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster2",
                            auth=[
                                ClusterAuthV1(service="rhidp"),
                                ClusterAuthV1(service="github-org"),
                            ],
                        ),
                        delete=False,
                    ),
                    role=None,
                    clusterRole="test-role-access",
                ),
            ],
            expirationDate=None,
        ),
        RoleV1(
            name="expiredtest-role-2",
            users=[
                UserV1(
                    org_username="test-org-user-3",
                    github_username="test-github-user-3",
                )
            ],
            bots=[],
            access=[
                AccessV1(
                    namespace=NamespaceV1(
                        name="test-namespace-2",
                        clusterAdmin=False,
                        managedRoles=True,
                        cluster=ClusterV1(
                            name="test-cluster-2", auth=[ClusterAuthV1(service="rhidp")]
                        ),
                        delete=False,
                    ),
                    role="test-role-access-2",
                    clusterRole=None,
                )
            ],
            expirationDate="2023-07-10",
        ),
    ]


class TestGetOcResources:
    """Tests for RoleBindingSpec.get_openshift_resources."""

    def test_get_oc_resources_without_support_role_ref(
        self, mocker: MockerFixture
    ) -> None:
        """Test get_openshift_resources without support_role_ref."""
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        test_role = get_app_interface_test_roles()
        role_binding_spec_list = RoleBindingSpec.create_rb_specs_from_role(
            test_role[0], None, support_role_ref=False
        )
        oc_resources = role_binding_spec_list[0].get_openshift_resources(
            integration_name="openshift-rolebindings",
            integration_version=QONTRACT_INTEGRATION_VERSION,
            privileged=False,
        )

        assert len(oc_resources) == 2
        assert oc_resources[0] == OCResource(
            resource=OR(
                integration="openshift-rolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-role5-test-org-user",
                body={
                    "kind": "RoleBinding",
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "metadata": {
                        "name": "test-role5-test-org-user",
                    },
                    "roleRef": {
                        "kind": "ClusterRole",
                        "name": "test-role5",
                    },
                    "subjects": [
                        {
                            "kind": "User",
                            "name": "test-org-user",
                        }
                    ],
                },
            ),
            resource_name="test-role5-test-org-user",
            privileged=False,
        )
        assert oc_resources[1] == OCResource(
            resource=OR(
                integration="openshift-rolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-role5-test-namespace5-test-serviceaccount",
                body={
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {
                        "name": "test-role5-test-namespace5-test-serviceaccount",
                    },
                    "roleRef": {
                        "kind": "ClusterRole",
                        "name": "test-role5",
                    },
                    "subjects": [
                        {
                            "kind": "ServiceAccount",
                            "name": "test-serviceaccount",
                            "namespace": "test-namespace5",
                        },
                    ],
                },
            ),
            resource_name="test-role5-test-namespace5-test-serviceaccount",
            privileged=False,
        )

    def test_get_oc_resources_with_support_role_ref(
        self, mocker: MockerFixture
    ) -> None:
        """Test get_openshift_resources with support_role_ref=True."""
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        test_role = get_app_interface_test_roles()
        role_binding_spec_list = RoleBindingSpec.create_rb_specs_from_role(
            test_role[0], None, support_role_ref=True
        )
        oc_resources = role_binding_spec_list[0].get_openshift_resources(
            integration_name="openshift-rolebindings",
            integration_version=QONTRACT_INTEGRATION_VERSION,
            privileged=False,
        )

        assert len(oc_resources) == 2
        assert oc_resources[0] == OCResource(
            resource=OR(
                integration="openshift-rolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-role5-test-org-user",
                body={
                    "kind": "RoleBinding",
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "metadata": {
                        "name": "test-role5-test-org-user",
                    },
                    "roleRef": {
                        "kind": "Role",
                        "name": "test-role5",
                    },
                    "subjects": [
                        {
                            "kind": "User",
                            "name": "test-org-user",
                        }
                    ],
                },
            ),
            resource_name="test-role5-test-org-user",
            privileged=False,
        )
        assert oc_resources[1] == OCResource(
            resource=OR(
                integration="openshift-rolebindings",
                integration_version=QONTRACT_INTEGRATION_VERSION,
                error_details="test-role5-test-namespace5-test-serviceaccount",
                body={
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {
                        "name": "test-role5-test-namespace5-test-serviceaccount",
                    },
                    "roleRef": {
                        "kind": "Role",
                        "name": "test-role5",
                    },
                    "subjects": [
                        {
                            "kind": "ServiceAccount",
                            "name": "test-serviceaccount",
                            "namespace": "test-namespace5",
                        },
                    ],
                },
            ),
            resource_name="test-role5-test-namespace5-test-serviceaccount",
            privileged=False,
        )


class TestOpenShiftRoleBindingsIntegrationFetchCurrentState:
    """Tests for OpenShiftRoleBindingsIntegration.fetch_current_state."""

    @pytest.fixture
    def integration(self) -> OpenShiftRoleBindingsIntegration:
        """Create integration instance."""
        params = OpenShiftRoleBindingsIntegrationParams()
        return OpenShiftRoleBindingsIntegration(params)

    def test_fetch_current_state(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_current_state calls ob.fetch_current_state correctly."""
        mock_ri = ResourceInventory()
        mock_oc_map = mocker.MagicMock()

        mock_get_namespaces = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_namespaces",
            return_value=[],
        )
        mock_fetch = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.fetch_current_state",
            return_value=(mock_ri, mock_oc_map),
        )

        ri, oc_map = integration.fetch_current_state()

        assert ri == mock_ri
        assert oc_map == mock_oc_map
        mock_get_namespaces.assert_called_once()
        mock_fetch.assert_called_once()

    def test_fetch_current_state_filters_namespaces(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_current_state filters invalid namespaces."""
        namespace = NamespaceV1(
            name="test-ns",
            clusterAdmin=False,
            managedRoles=True,
            cluster=ClusterV1(
                name="test-cluster", auth=[ClusterAuthV1(service="rhidp")]
            ),
            delete=False,
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_namespaces",
            return_value=[namespace],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.is_valid_namespace",
            return_value=True,
        )
        mock_fetch = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.fetch_current_state",
            return_value=(ResourceInventory(), mocker.MagicMock()),
        )

        integration.fetch_current_state()

        call_kwargs = mock_fetch.call_args.kwargs
        assert "namespaces" in call_kwargs
        assert len(call_kwargs["namespaces"]) == 1


class TestOpenShiftRoleBindingsIntegrationFetchDesiredState:
    """Tests for OpenShiftRoleBindingsIntegration.fetch_desired_state."""

    @pytest.fixture
    def integration(self) -> OpenShiftRoleBindingsIntegration:
        """Create integration instance."""
        params = OpenShiftRoleBindingsIntegrationParams()
        return OpenShiftRoleBindingsIntegration(params)

    def test_fetch_desired_state_empty_allowed_clusters(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state returns early when allowed_clusters is empty."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster5", "test-namespace5", QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles"
        ).return_value = get_app_interface_test_roles()

        integration.fetch_desired_state(ri, allowed_clusters=set())

        assert not ri.get_desired(
            "test-cluster5",
            "test-namespace5",
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-role5-test-org-user",
        )

    def test_fetch_desired_state_contents_with_filtered_clusters(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state populates ResourceInventory with filtered clusters."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster5", "test-namespace5", QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        ri.initialize_resource_type(
            "test-cluster", "test-namespace", QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.expiration.filter",
            side_effect=lambda x: [r for r in x if r.expiration_date is None],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles"
        ).return_value = get_app_interface_test_roles()
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        integration.fetch_desired_state(ri, allowed_clusters={"test-cluster5"})

        assert ri.get_desired(
            "test-cluster5",
            "test-namespace5",
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-role5-test-org-user",
        )
        assert not ri.get_desired(
            "test-cluster",
            "test-namespace",
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-role5-test-org-user",
        )

    def test_fetch_desired_state_contents_without_filtered_clusters(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state populates ResourceInventory without cluster filter."""
        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster5", "test-namespace5", QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        ri.initialize_resource_type(
            "test-cluster2", "test-namespace", QONTRACT_INTEGRATION_MANAGED_TYPE
        )
        ri.initialize_resource_type(
            "test-cluster", "test-namespace", QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.expiration.filter",
            side_effect=lambda x: [r for r in x if r.expiration_date is None],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles"
        ).return_value = get_app_interface_test_roles()
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        integration.fetch_desired_state(
            ri, allowed_clusters={"test-cluster5", "test-cluster", "test-cluster2"}
        )

        assert ri.get_desired(
            "test-cluster5",
            "test-namespace5",
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-role5-test-org-user",
        )
        assert ri.get_desired(
            "test-cluster",
            "test-namespace",
            QONTRACT_INTEGRATION_MANAGED_TYPE,
            "test-role-access-test-org-user",
        )


class TestOpenShiftRoleBindingsIntegrationRun:
    """Tests for OpenShiftRoleBindingsIntegration.run."""

    @pytest.fixture
    def integration(self) -> OpenShiftRoleBindingsIntegration:
        """Create integration instance."""
        params = OpenShiftRoleBindingsIntegrationParams()
        return OpenShiftRoleBindingsIntegration(params)

    def test_run_calls_expected_methods(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test run calls fetch_current_state, fetch_desired_state, and realize_data."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = False
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mocker.patch.object(
            integration, "fetch_current_state", return_value=(mock_ri, mock_oc_map)
        )
        mock_fetch_desired = mocker.patch.object(
            integration, "fetch_desired_state", return_value=None
        )
        mock_publish = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.publish_metrics"
        )
        mock_realize = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.realize_data"
        )

        integration.run(dry_run=True)

        mock_fetch_desired.assert_called_once()
        mock_publish.assert_called_once()
        mock_realize.assert_called_once()

    def test_run_exits_on_error(
        self, integration: OpenShiftRoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test run exits with code 1 when errors registered."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = True
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mocker.patch.object(
            integration, "fetch_current_state", return_value=(mock_ri, mock_oc_map)
        )
        mocker.patch.object(integration, "fetch_desired_state", return_value=None)
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.publish_metrics"
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.realize_data"
        )
        mock_exit = mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.sys.exit"
        )

        integration.run(dry_run=True)

        mock_exit.assert_called_once_with(1)
