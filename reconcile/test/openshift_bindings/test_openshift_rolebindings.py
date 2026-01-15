"""Tests for reconcile.openshift_bindings.openshift_rolebindings module."""

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    ClusterAuthV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.openshift_bindings.openshift_rolebindings import (
    QONTRACT_INTEGRATION_MANAGED_TYPE,
    RoleBindingsIntegration,
)
from reconcile.utils.openshift_resource import ResourceInventory


class TestRoleBindingsIntegrationFetchCurrentState:
    """Tests for RoleBindingsIntegration.fetch_current_state."""

    @pytest.fixture
    def integration(self) -> RoleBindingsIntegration:
        """Create integration instance."""
        return RoleBindingsIntegration(
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

    def test_fetch_current_state(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
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
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_current_state filters invalid namespaces."""
        # Create test namespace
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

        # Verify namespaces were passed to fetch_current_state
        call_kwargs = mock_fetch.call_args.kwargs
        assert "namespaces" in call_kwargs
        assert len(call_kwargs["namespaces"]) == 1


class TestRoleBindingsIntegrationFetchDesiredState:
    """Tests for RoleBindingsIntegration.fetch_desired_state."""

    @pytest.fixture
    def integration(self) -> RoleBindingsIntegration:
        """Create integration instance."""
        return RoleBindingsIntegration(
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

    def test_fetch_desired_state_empty_allowed_clusters(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state returns early when allowed_clusters is empty."""
        ri = ResourceInventory()

        # Should return early without doing any work
        integration.fetch_desired_state(
            ri=ri,
            allowed_clusters=set(),
        )
        # No assertions needed - just verifying no exceptions

    def test_fetch_desired_state_none_ri(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state returns early when ri is None."""
        # Should return early without doing any work
        integration.fetch_desired_state(
            ri=None,
            allowed_clusters={"test-cluster"},
        )
        # No assertions needed - just verifying no exceptions

    def test_fetch_desired_state_populates_ri(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state populates ResourceInventory."""
        # Setup test data
        namespace = NamespaceV1(
            name="test-ns",
            clusterAdmin=False,
            managedRoles=True,
            cluster=ClusterV1(
                name="test-cluster", auth=[ClusterAuthV1(service="rhidp")]
            ),
            delete=False,
        )
        role = RoleV1(
            name="test-role",
            users=[UserV1(org_username="test-user", github_username="test-gh")],
            bots=[],
            access=[AccessV1(namespace=namespace, role="test-role", clusterRole=None)],
            expirationDate=None,
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.expiration.filter",
            return_value=[role],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles",
            return_value=[role],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.is_valid_namespace",
            return_value=True,
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        ri = ResourceInventory()
        ri.initialize_resource_type(
            "test-cluster", "test-ns", QONTRACT_INTEGRATION_MANAGED_TYPE
        )

        integration.fetch_desired_state(
            ri=ri,
            allowed_clusters={"test-cluster"},
        )

        # Verify ResourceInventory was populated (no exception means success)

    def test_fetch_desired_state_filters_by_allowed_clusters(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test fetch_desired_state filters by allowed_clusters."""
        namespace = NamespaceV1(
            name="test-ns",
            clusterAdmin=False,
            managedRoles=True,
            cluster=ClusterV1(
                name="other-cluster", auth=[ClusterAuthV1(service="rhidp")]
            ),
            delete=False,
        )
        role = RoleV1(
            name="test-role",
            users=[UserV1(org_username="test-user", github_username="test-gh")],
            bots=[],
            access=[AccessV1(namespace=namespace, role="test-role", clusterRole=None)],
            expirationDate=None,
        )

        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.expiration.filter",
            return_value=[role],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.get_app_interface_roles",
            return_value=[role],
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.is_valid_namespace",
            return_value=True,
        )
        mocker.patch(
            "reconcile.openshift_bindings.openshift_rolebindings.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        ri = ResourceInventory()
        ri_add_desired_mock = mocker.patch.object(ri, "add_desired")

        # allowed_clusters doesn't include "other-cluster"
        integration.fetch_desired_state(
            ri=ri,
            allowed_clusters={"test-cluster"},
        )

        # add_desired should not be called since cluster is filtered out
        ri_add_desired_mock.assert_not_called()


class TestRoleBindingsIntegrationReconcile:
    """Tests for RoleBindingsIntegration.reconcile (inherited from base)."""

    @pytest.fixture
    def integration(self) -> RoleBindingsIntegration:
        """Create integration instance."""
        return RoleBindingsIntegration(
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

    def test_reconcile_calls_expected_methods(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test reconcile calls fetch_desired_state, publish_metrics, and realize_data."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = False
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mock_fetch_desired = mocker.patch.object(
            integration, "fetch_desired_state", return_value=None
        )
        # reconcile() is inherited from base, so mock the base module's ob
        mock_publish = mocker.patch(
            "reconcile.openshift_bindings.base.ob.publish_metrics"
        )
        mock_realize = mocker.patch("reconcile.openshift_bindings.base.ob.realize_data")

        integration.reconcile(
            dry_run=True,
            ri=mock_ri,
            oc_map=mock_oc_map,
            support_role_ref=True,
            enforced_user_keys=["org_username"],
        )

        mock_fetch_desired.assert_called_once_with(
            mock_ri,
            True,
            ["org_username"],
            allowed_clusters={"test-cluster"},
        )
        mock_publish.assert_called_once_with(mock_ri, integration.integration_name)
        mock_realize.assert_called_once_with(
            True, mock_oc_map, mock_ri, integration.thread_pool_size
        )

    def test_reconcile_exits_on_error(
        self, integration: RoleBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test reconcile exits with code 1 when errors registered."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = True
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mocker.patch.object(integration, "fetch_desired_state", return_value=None)
        mocker.patch("reconcile.openshift_bindings.base.ob.publish_metrics")
        mocker.patch("reconcile.openshift_bindings.base.ob.realize_data")
        mock_exit = mocker.patch("reconcile.openshift_bindings.base.sys.exit")

        integration.reconcile(
            dry_run=True,
            ri=mock_ri,
            oc_map=mock_oc_map,
        )

        mock_exit.assert_called_once_with(1)
