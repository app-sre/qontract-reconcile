"""Tests for reconcile.openshift_bindings.base module."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterV1,
    UserV1,
)
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.models import (
    BindingSpec,
    OCResource,
    RoleBindingSpec,
)
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory


class ConcreteBindingsIntegration(OpenShiftBindingsBase):
    """Concrete implementation for testing abstract base class."""

    @property
    def integration_name(self) -> str:
        return "test-integration"

    @property
    def integration_version(self) -> str:
        return "0.1.0"

    @property
    def resource_kind(self) -> str:
        return "RoleBinding"

    def fetch_desired_state(
        self,
        ri: ResourceInventory | None,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
        allowed_clusters: set[str] | None = None,
    ) -> None:
        pass

    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        return ResourceInventory(), MagicMock(spec=OC_Map)


class TestOpenShiftBindingsBase:
    """Tests for OpenShiftBindingsBase abstract class."""

    @pytest.fixture
    def integration(self) -> ConcreteBindingsIntegration:
        """Create concrete integration instance."""
        return ConcreteBindingsIntegration(
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

    def test_init(self, integration: ConcreteBindingsIntegration) -> None:
        """Test initialization stores parameters."""
        assert integration.thread_pool_size == 10
        assert integration.internal is None
        assert integration.use_jump_host is True

    def test_integration_name(self, integration: ConcreteBindingsIntegration) -> None:
        """Test integration_name property."""
        assert integration.integration_name == "test-integration"

    def test_integration_version(
        self, integration: ConcreteBindingsIntegration
    ) -> None:
        """Test integration_version property."""
        assert integration.integration_version == "0.1.0"

    def test_resource_kind(self, integration: ConcreteBindingsIntegration) -> None:
        """Test resource_kind property."""
        assert integration.resource_kind == "RoleBinding"

    def test_get_openshift_resources(
        self,
        integration: ConcreteBindingsIntegration,
        mocker: MockerFixture,
        test_access_with_role: AccessV1,
        test_user: UserV1,
    ) -> None:
        """Test get_openshift_resources creates OCResource objects."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
        )
        assert spec is not None

        resources = integration.get_openshift_resources(spec)

        assert len(resources) == 1
        assert isinstance(resources[0], OCResource)
        assert resources[0].resource_name == "test-role-test-org-user"
        assert resources[0].privileged is False

    def test_get_openshift_resources_privileged(
        self,
        integration: ConcreteBindingsIntegration,
        mocker: MockerFixture,
        test_access_with_role: AccessV1,
        test_user: UserV1,
    ) -> None:
        """Test get_openshift_resources with privileged flag."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
        )
        assert spec is not None

        resources = integration.get_openshift_resources(spec, privileged=True)

        assert len(resources) == 1
        assert resources[0].privileged is True

    def test_get_openshift_resources_with_service_accounts(
        self,
        integration: ConcreteBindingsIntegration,
        mocker: MockerFixture,
        test_access_with_role: AccessV1,
        test_user: UserV1,
        test_bot: BotV1,
    ) -> None:
        """Test get_openshift_resources includes service account resources."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
            bots=[test_bot],
        )
        assert spec is not None

        resources = integration.get_openshift_resources(spec)

        # 1 user + 1 service account
        assert len(resources) == 2

    def test_get_openshift_resources_empty(
        self,
        integration: ConcreteBindingsIntegration,
        mocker: MockerFixture,
        test_cluster: ClusterV1,
    ) -> None:
        """Test get_openshift_resources with empty binding spec."""

        # Create a minimal binding spec with no users or SAs
        class MinimalBindingSpec(BindingSpec):
            pass

        spec = MinimalBindingSpec(
            role_name="test-role",
            role_kind="ClusterRole",
            cluster=test_cluster,
            resource_kind="RoleBinding",
            usernames=set(),
            openshift_service_accounts=[],
        )

        resources = integration.get_openshift_resources(spec)

        assert resources == []


class TestOpenShiftBindingsBaseReconcile:
    """Tests for OpenShiftBindingsBase.reconcile method."""

    @pytest.fixture
    def integration(self) -> ConcreteBindingsIntegration:
        """Create concrete integration instance."""
        return ConcreteBindingsIntegration(
            thread_pool_size=10,
            internal=None,
            use_jump_host=True,
        )

    def test_reconcile_calls_expected_methods(
        self, integration: ConcreteBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test reconcile calls fetch_desired_state, publish_metrics, and realize_data."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = False
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mock_fetch_desired = mocker.patch.object(
            integration, "fetch_desired_state", return_value=None
        )
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
        self, integration: ConcreteBindingsIntegration, mocker: MockerFixture
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

    def test_reconcile_no_error_no_exit(
        self, integration: ConcreteBindingsIntegration, mocker: MockerFixture
    ) -> None:
        """Test reconcile does not exit when no errors registered."""
        mock_ri = mocker.MagicMock(spec=ResourceInventory)
        mock_ri.has_error_registered.return_value = False
        mock_oc_map = mocker.MagicMock()
        mock_oc_map.clusters.return_value = ["test-cluster"]

        mocker.patch.object(integration, "fetch_desired_state", return_value=None)
        mocker.patch("reconcile.openshift_bindings.base.ob.publish_metrics")
        mocker.patch("reconcile.openshift_bindings.base.ob.realize_data")
        mock_exit = mocker.patch("reconcile.openshift_bindings.base.sys.exit")

        integration.reconcile(
            dry_run=False,
            ri=mock_ri,
            oc_map=mock_oc_map,
        )

        mock_exit.assert_not_called()
