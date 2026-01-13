"""Tests for reconcile.openshift_bindings.integration module."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.openshift_bindings.integration import (
    OpenShiftBindingsIntegration,
    OpenShiftBindingsIntegrationParams,
    get_rolebindings_integration,
)
from reconcile.openshift_bindings.openshift_clusterrolebindings import (
    ClusterRoleBindingsIntegration,
)
from reconcile.openshift_bindings.openshift_rolebindings import RoleBindingsIntegration
from reconcile.utils.openshift_resource import ResourceInventory


class TestOpenShiftBindingsIntegrationParams:
    """Tests for OpenShiftBindingsIntegrationParams."""

    def test_default_values(self) -> None:
        """Test default parameter values."""
        params = OpenShiftBindingsIntegrationParams(
            integration_name="openshift-rolebindings"
        )
        assert params.support_role_ref is False
        assert params.enforced_user_keys is None
        assert params.thread_pool_size == 10  # DEFAULT_THREAD_POOL_SIZE
        assert params.internal is None
        assert params.use_jump_host is True

    def test_custom_values(self) -> None:
        """Test custom parameter values."""
        params = OpenShiftBindingsIntegrationParams(
            integration_name="openshift-clusterrolebindings",
            support_role_ref=True,
            enforced_user_keys=["org_username"],
            thread_pool_size=20,
            internal=True,
            use_jump_host=False,
        )
        assert params.integration_name == "openshift-clusterrolebindings"
        assert params.support_role_ref is True
        assert params.enforced_user_keys == ["org_username"]
        assert params.thread_pool_size == 20
        assert params.internal is True
        assert params.use_jump_host is False


class TestGetRolebindingsIntegration:
    """Tests for get_rolebindings_integration factory function."""

    def test_returns_rolebindings_integration(self) -> None:
        """Test factory returns RoleBindingsIntegration for rolebindings."""
        integration = get_rolebindings_integration(
            integration_name="openshift-rolebindings",
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

        assert isinstance(integration, RoleBindingsIntegration)
        assert integration.thread_pool_size == 10
        assert integration.internal is None
        assert integration.use_jump_host is True

    def test_returns_clusterrolebindings_integration(self) -> None:
        """Test factory returns ClusterRoleBindingsIntegration for clusterrolebindings."""
        integration = get_rolebindings_integration(
            integration_name="openshift-clusterrolebindings",
            thread_pool_size=20,
            internal=True,
            use_jump_host=False,
        )

        assert isinstance(integration, ClusterRoleBindingsIntegration)
        assert integration.thread_pool_size == 20
        assert integration.internal is True
        assert integration.use_jump_host is False


class TestOpenShiftBindingsIntegration:
    """Tests for OpenShiftBindingsIntegration class."""

    @pytest.fixture
    def mock_ri(self) -> ResourceInventory:
        """Mock ResourceInventory."""
        return ResourceInventory()

    @pytest.fixture
    def mock_oc_map(self, mocker: MockerFixture) -> MagicMock:
        """Mock OC_Map."""
        oc_map = mocker.MagicMock()
        oc_map.clusters.return_value = ["test-cluster"]
        oc_map.cleanup = mocker.MagicMock()
        return oc_map

    def test_name_property_rolebindings(self) -> None:
        """Test name property returns integration name for rolebindings."""
        params = OpenShiftBindingsIntegrationParams(
            integration_name="openshift-rolebindings"
        )
        integration = OpenShiftBindingsIntegration(params)

        assert integration.name == "openshift-rolebindings"

    def test_name_property_clusterrolebindings(self) -> None:
        """Test name property returns integration name for clusterrolebindings."""
        params = OpenShiftBindingsIntegrationParams(
            integration_name="openshift-clusterrolebindings"
        )
        integration = OpenShiftBindingsIntegration(params)

        assert integration.name == "openshift-clusterrolebindings"

    def test_run_calls_integration_methods(
        self,
        mocker: MockerFixture,
        mock_ri: ResourceInventory,
        mock_oc_map: MagicMock,
    ) -> None:
        """Test run method calls correct integration methods."""
        # Mock the factory function
        mock_integration = mocker.MagicMock()
        mock_integration.fetch_current_state.return_value = (mock_ri, mock_oc_map)
        mocker.patch(
            "reconcile.openshift_bindings.integration.get_rolebindings_integration",
            return_value=mock_integration,
        )

        params = OpenShiftBindingsIntegrationParams(
            integration_name="openshift-rolebindings",
            support_role_ref=True,
            enforced_user_keys=["org_username"],
        )
        integration = OpenShiftBindingsIntegration(params)

        # Run with dry_run=True
        integration.run(dry_run=True)

        # Verify methods were called
        mock_integration.fetch_current_state.assert_called_once()
        mock_integration.reconcile.assert_called_once_with(
            dry_run=True,
            ri=mock_ri,
            oc_map=mock_oc_map,
            support_role_ref=True,
            enforced_user_keys=["org_username"],
        )
