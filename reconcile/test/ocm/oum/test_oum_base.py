from typing import Optional
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.oum import base
from reconcile.oum.base import (
    OCMUserManagementIntegration,
    OCMUserManagementIntegrationParams,
    build_specs_from_config,
    reconcile_cluster_roles,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationActionCounter as ReconcileActionCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationReconcileCounter as ReconcileCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationReconcileErrorCounter as ReconcileErrorCounter,
)
from reconcile.oum.metrics import (
    OCMUserManagementOrganizationValidationErrorsGauge as ValidationErrorsGauge,
)
from reconcile.oum.models import (
    ClusterError,
    ClusterRoleReconcileResult,
    ClusterUserManagementConfiguration,
    ClusterUserManagementSpec,
    ExternalGroupRef,
    OrganizationUserManagementConfiguration,
)
from reconcile.oum.providers import GroupMemberProvider
from reconcile.test.ocm.fixtures import build_cluster_details
from reconcile.utils import metrics
from reconcile.utils.ocm.cluster_groups import (
    OCMClusterGroup,
    OCMClusterGroupId,
    OCMClusterUser,
    OCMClusterUserList,
)
from reconcile.utils.ocm.clusters import (
    CAPABILITY_MANAGE_CLUSTER_ADMIN,
    PRODUCT_ID_OSD,
    PRODUCT_ID_ROSA,
    ClusterDetails,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_ocm_cluster_group(
    id: OCMClusterGroupId, user_ids: set[str]
) -> OCMClusterGroup:
    return OCMClusterGroup(
        id=id,
        href="xxx",
        users=OCMClusterUserList(
            items=[OCMClusterUser(id=user_id) for user_id in user_ids]
        ),
    )


@pytest.fixture
def org_id() -> str:
    return "123456"


@pytest.fixture
def cluster(org_id: str) -> ClusterDetails:
    return build_cluster_details(
        cluster_name="cluster-1",
        org_id=org_id,
    )


@pytest.fixture
def cluster_with_cluster_admin_capability(org_id: str) -> ClusterDetails:
    return build_cluster_details(
        cluster_name="cluster-1",
        org_id=org_id,
        capabilitites={CAPABILITY_MANAGE_CLUSTER_ADMIN: "true"},
    )


#
# test reconciling
#


def test_reconcile_cluster_add_and_remove(
    ocm_api: OCMBaseClient, org_id: str, cluster: ClusterDetails, mocker: MockerFixture
) -> None:
    mocker.patch.object(base, "get_cluster_groups").return_value = {
        OCMClusterGroupId.CLUSTER_ADMINS: build_ocm_cluster_group(
            OCMClusterGroupId.CLUSTER_ADMINS, {"user-1", "user-2"}
        )
    }
    add_user_mock = mocker.patch.object(base, "add_user_to_cluster_group")
    add_user_mock.return_value = None
    remove_user_mock = mocker.patch.object(base, "delete_user_from_cluster_group")
    remove_user_mock.return_value = None

    result = reconcile_cluster_roles(
        dry_run=False,
        ocm_api=ocm_api,
        org_id=org_id,
        spec=ClusterUserManagementSpec(
            cluster=cluster,
            roles={
                OCMClusterGroupId.CLUSTER_ADMINS: {
                    "user-2",
                    "user-3",
                },
            },
            errors=[],
        ),
    )
    assert result.users_added == 1
    add_user_mock.assert_called_with(
        ocm_api=ocm_api,
        cluster_id=cluster.ocm_cluster.id,
        user_name="user-3",
        group=OCMClusterGroupId.CLUSTER_ADMINS,
    )
    assert result.users_removed == 1
    remove_user_mock.assert_called_with(
        ocm_api=ocm_api,
        cluster_id=cluster.ocm_cluster.id,
        user_name="user-1",
        group=OCMClusterGroupId.CLUSTER_ADMINS,
    )
    assert result.error is None


def test_reconcile_cluster_only_touch_defined_groups(
    ocm_api: OCMBaseClient, org_id: str, cluster: ClusterDetails, mocker: MockerFixture
) -> None:
    """
    Test if a group undefined by the spec is not touched in OCM.
    In this case the spec does not mention dedicated-admins but
    the current state defines users. The expected behaviour is to
    not touch the dedicated-admins group in OCM.
    """
    mocker.patch.object(base, "get_cluster_groups").return_value = {
        OCMClusterGroupId.CLUSTER_ADMINS: build_ocm_cluster_group(
            OCMClusterGroupId.CLUSTER_ADMINS, {"user-1", "user-2"}
        ),
        OCMClusterGroupId.DEDICATED_ADMINS: build_ocm_cluster_group(
            OCMClusterGroupId.CLUSTER_ADMINS, {"user-3", "user-4"}
        ),
    }
    remove_user_mock = mocker.patch.object(base, "delete_user_from_cluster_group")
    remove_user_mock.return_value = None

    result = reconcile_cluster_roles(
        dry_run=False,
        ocm_api=ocm_api,
        org_id=org_id,
        spec=ClusterUserManagementSpec(
            cluster=cluster,
            roles={
                OCMClusterGroupId.CLUSTER_ADMINS: set(),
            },
            errors=[],
        ),
    )
    assert result.users_added == 0
    assert result.users_removed == 2
    assert remove_user_mock.call_count == 2
    remove_user_mock.assert_any_call(
        ocm_api=ocm_api,
        cluster_id=cluster.ocm_cluster.id,
        user_name="user-1",
        group=OCMClusterGroupId.CLUSTER_ADMINS,
    )
    remove_user_mock.assert_any_call(
        ocm_api=ocm_api,
        cluster_id=cluster.ocm_cluster.id,
        user_name="user-2",
        group=OCMClusterGroupId.CLUSTER_ADMINS,
    )
    assert result.error is None


def test_reconcile_cluster_error(
    ocm_api: OCMBaseClient, org_id: str, cluster: ClusterDetails, mocker: MockerFixture
) -> None:
    mocker.patch.object(base, "get_cluster_groups").side_effect = Exception(
        "something went wrong"
    )

    org_id = "123456"
    result = reconcile_cluster_roles(
        dry_run=False,
        ocm_api=ocm_api,
        org_id=org_id,
        spec=ClusterUserManagementSpec(
            cluster=cluster,
            roles={
                OCMClusterGroupId.CLUSTER_ADMINS: set(),
            },
            errors=[],
        ),
    )

    assert result.error is not None


#
# test build spec from config
#


class MockGroupMemberProvider(GroupMemberProvider):
    def __init__(self, groups: dict[str, set[str]]):
        self.groups = groups

    def resolve_groups(self, group_ids: set[str]) -> dict[str, set[str]]:
        return {
            group_id: self.groups[group_id]
            for group_id in group_ids
            if group_id in self.groups
        }


@pytest.fixture
def mock_group_member_provider() -> MockGroupMemberProvider:
    return MockGroupMemberProvider(
        {
            "group-1": {"user-1", "user-2"},
            "group-2": {"user-3", "user-4"},
            "group-3": {"user-5", "user-6"},
            "group-4": {"user-7", "user-8"},
        }
    )


def build_org_config(
    cluster: ClusterDetails, roles: dict[OCMClusterGroupId, list[ExternalGroupRef]]
) -> OrganizationUserManagementConfiguration:
    return OrganizationUserManagementConfiguration(
        org_id=cluster.organization_id,
        cluster_configs=[
            ClusterUserManagementConfiguration(
                cluster=cluster,
                roles=roles,
            )
        ],
    )


def test_build_spec_from_config(
    cluster: ClusterDetails,
    mock_group_member_provider: MockGroupMemberProvider,
) -> None:
    """
    Happy path
    """
    provider = "mock"
    org_config = build_org_config(
        cluster=cluster,
        roles={
            OCMClusterGroupId.DEDICATED_ADMINS: [
                ExternalGroupRef(
                    group_id="group-1",
                    provider=provider,
                )
            ]
        },
    )

    specs = build_specs_from_config(
        org_config=org_config,
        group_member_providers={
            provider: mock_group_member_provider,
        },
    )
    assert len(specs) == 1
    assert specs[0].roles[OCMClusterGroupId.DEDICATED_ADMINS] == {"user-1", "user-2"}
    assert specs[0].cluster == cluster
    assert len(specs[0].errors) == 0


def test_build_spec_from_config_missing_group(
    cluster: ClusterDetails,
    mock_group_member_provider: MockGroupMemberProvider,
) -> None:
    """
    A group defined on a cluster role is missing. The expected behaviour
    is an exposed error and the role not being listed in the spec.
    """
    provider = "mock"
    org_config = build_org_config(
        cluster=cluster,
        roles={
            OCMClusterGroupId.DEDICATED_ADMINS: [
                ExternalGroupRef(
                    group_id="missing-group",
                    provider=provider,
                )
            ]
        },
    )

    specs = build_specs_from_config(
        org_config=org_config,
        group_member_providers={
            provider: mock_group_member_provider,
        },
    )
    assert len(specs) == 1
    assert specs[0].roles == {}
    assert specs[0].cluster == cluster
    assert len(specs[0].errors) == 1


@pytest.mark.parametrize(
    "cluster_product, errors, expected_groups",
    [
        (PRODUCT_ID_OSD, True, {}),
        (
            PRODUCT_ID_ROSA,
            False,
            {OCMClusterGroupId.CLUSTER_ADMINS: {"user-1", "user-2"}},
        ),
    ],
)
def test_build_spec_from_config_osd_cluster_admin_without_capability(
    cluster: ClusterDetails,
    mock_group_member_provider: MockGroupMemberProvider,
    cluster_product: str,
    errors: int,
    expected_groups: dict[str, set[str]],
) -> None:
    """
    An OSD cluster without the manage cluster admin capability should NOT be able to
    have cluster admins defined. But for ROSA clusters, this is allowed.
    """
    cluster.ocm_cluster.product.id = cluster_product
    provider = "mock"
    org_config = build_org_config(
        cluster=cluster,
        roles={
            OCMClusterGroupId.CLUSTER_ADMINS: [
                ExternalGroupRef(
                    group_id="group-1",
                    provider=provider,
                )
            ]
        },
    )
    specs = build_specs_from_config(
        org_config=org_config,
        group_member_providers={
            provider: mock_group_member_provider,
        },
    )
    assert len(specs) == 1
    assert len(specs[0].errors) == errors
    assert specs[0].roles == expected_groups


def test_build_spec_from_config_cluster_admin_with_capability(
    cluster_with_cluster_admin_capability: ClusterDetails,
    mock_group_member_provider: MockGroupMemberProvider,
) -> None:
    """
    A cluster with the manage cluster admin capability should be able to
    have cluster admins defined.
    """
    provider = "mock"
    org_config = build_org_config(
        cluster=cluster_with_cluster_admin_capability,
        roles={
            OCMClusterGroupId.CLUSTER_ADMINS: [
                ExternalGroupRef(
                    group_id="group-1",
                    provider=provider,
                )
            ]
        },
    )
    specs = build_specs_from_config(
        org_config=org_config,
        group_member_providers={
            provider: mock_group_member_provider,
        },
    )
    assert len(specs) == 1
    assert specs[0].roles[OCMClusterGroupId.CLUSTER_ADMINS] == {"user-1", "user-2"}
    assert specs[0].cluster == cluster_with_cluster_admin_capability
    assert len(specs[0].errors) == 0


#
# test reconcile OCM organization
#


class MockOCMUserManagementIntegration(OCMUserManagementIntegration):
    def get_user_mgmt_config_for_ocm_env(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUserManagementConfiguration]:
        return {}

    @property
    def name(self) -> str:
        return "mock-ocm-user-management-integration"

    def signal_cluster_reconcile_success(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        message: str,
    ) -> None:
        ...

    def signal_cluster_validation_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        ...

    def signal_cluster_reconcile_error(
        self,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        spec: ClusterUserManagementSpec,
        error: Exception,
    ) -> None:
        ...


@pytest.fixture
def reconcile_cluster_roles_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(base, "reconcile_cluster_roles", autospec=True)


@pytest.fixture
def signal_cluster_validation_error_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(
        MockOCMUserManagementIntegration,
        "signal_cluster_validation_error",
        autospec=True,
    )


@pytest.fixture
def signal_cluster_reconcile_error_mock(mocker: MockerFixture) -> MagicMock:
    return mocker.patch.object(
        MockOCMUserManagementIntegration,
        "signal_cluster_reconcile_error",
        autospec=True,
    )


def test_reconcile_ocm_organization_validation_error(
    cluster: ClusterDetails,
    ocm_api: OCMBaseClient,
    org_id: str,
    reconcile_cluster_roles_mock: MagicMock,
    signal_cluster_validation_error_mock: MagicMock,
    signal_cluster_reconcile_error_mock: MagicMock,
) -> None:
    """
    Verify that a spec with validation errors is not reconciled but the error
    is exposed as a metric.
    """
    metrics_container = metrics.MetricsContainer()
    integration = MockOCMUserManagementIntegration(
        OCMUserManagementIntegrationParams(group_provider_specs=[])
    )
    with metrics.transactional_metrics(integration.name, metrics_container):
        integration.reconcile_ocm_organization(
            dry_run=False,
            ocm_api=ocm_api,
            org_id=org_id,
            ocm_env="production",
            cluster_specs=[
                ClusterUserManagementSpec(
                    cluster=cluster,
                    roles={
                        OCMClusterGroupId.DEDICATED_ADMINS: {"user-1", "user-2"},
                    },
                    errors=[ClusterError(message="an error occured")],
                )
            ],
        )

    # verify exposed metrics
    assert metrics_container.get_metric_value(ReconcileCounter, org_id=org_id) == 1
    assert metrics_container.get_metric_value(ReconcileErrorCounter, org_id=org_id) == 0
    assert metrics_container.get_metric_value(ValidationErrorsGauge, org_id=org_id) == 1

    # verify cluster has not been reconciled
    reconcile_cluster_roles_mock.assert_not_called()

    # verify issue signaling
    signal_cluster_validation_error_mock.assert_called()
    signal_cluster_reconcile_error_mock.assert_not_called()


def test_reconcile_ocm_organization_successful_cluster_reconcile(
    cluster: ClusterDetails,
    ocm_api: OCMBaseClient,
    org_id: str,
    reconcile_cluster_roles_mock: MagicMock,
    signal_cluster_validation_error_mock: MagicMock,
    signal_cluster_reconcile_error_mock: MagicMock,
) -> None:
    """
    Verify that a valid spec that reconciles successfully, exposes corret metrics
    and does not signal any issues.
    """
    metrics_container = metrics.MetricsContainer()
    integration = MockOCMUserManagementIntegration(
        OCMUserManagementIntegrationParams(group_provider_specs=[])
    )
    reconcile_cluster_roles_mock.return_value = ClusterRoleReconcileResult(
        users_added=2,
        users_removed=3,
        errors=[],
    )
    with metrics.transactional_metrics(integration.name, metrics_container):
        integration.reconcile_ocm_organization(
            dry_run=False,
            ocm_api=ocm_api,
            org_id=org_id,
            ocm_env="production",
            cluster_specs=[
                ClusterUserManagementSpec(
                    cluster=cluster,
                    roles={
                        OCMClusterGroupId.DEDICATED_ADMINS: {"user-1", "user-2"},
                    },
                )
            ],
        )

    # verify exposed metrics
    assert metrics_container.get_metric_value(ReconcileCounter, org_id=org_id) == 1
    assert metrics_container.get_metric_value(ReconcileErrorCounter, org_id=org_id) == 0
    assert metrics_container.get_metric_value(ValidationErrorsGauge, org_id=org_id) == 0
    assert (
        metrics_container.get_metric_value(
            ReconcileActionCounter,
            org_id=org_id,
            action=ReconcileActionCounter.Action.AddUser,
        )
        == 2
    )
    assert (
        metrics_container.get_metric_value(
            ReconcileActionCounter,
            org_id=org_id,
            action=ReconcileActionCounter.Action.RemoveUser,
        )
        == 3
    )

    # verify cluster has been reconciled
    reconcile_cluster_roles_mock.assert_called_once()

    # verify issue signaling
    signal_cluster_validation_error_mock.assert_not_called()
    signal_cluster_reconcile_error_mock.assert_not_called()


def test_reconcile_ocm_organization_failed_cluster_reconcile(
    cluster: ClusterDetails,
    ocm_api: OCMBaseClient,
    org_id: str,
    reconcile_cluster_roles_mock: MagicMock,
    signal_cluster_validation_error_mock: MagicMock,
    signal_cluster_reconcile_error_mock: MagicMock,
) -> None:
    """
    Verify that a valid spec that fails reconciling reports metrics
    and signals errors correctly.
    """
    metrics_container = metrics.MetricsContainer()
    integration = MockOCMUserManagementIntegration(
        OCMUserManagementIntegrationParams(group_provider_specs=[])
    )
    reconcile_cluster_roles_mock.return_value = ClusterRoleReconcileResult(
        users_added=1,
        users_removed=0,
        error=Exception("an error occured"),
    )
    with metrics.transactional_metrics(integration.name, metrics_container):
        integration.reconcile_ocm_organization(
            dry_run=False,
            ocm_api=ocm_api,
            org_id=org_id,
            ocm_env="production",
            cluster_specs=[
                ClusterUserManagementSpec(
                    cluster=cluster,
                    roles={
                        OCMClusterGroupId.DEDICATED_ADMINS: {"user-1", "user-2"},
                    },
                )
            ],
        )

    # verify exposed metrics
    assert metrics_container.get_metric_value(ReconcileCounter, org_id=org_id) == 1
    assert metrics_container.get_metric_value(ReconcileErrorCounter, org_id=org_id) == 1
    assert metrics_container.get_metric_value(ValidationErrorsGauge, org_id=org_id) == 0
    assert (
        metrics_container.get_metric_value(
            ReconcileActionCounter,
            org_id=org_id,
            action=ReconcileActionCounter.Action.AddUser,
        )
        == 1
    )
    assert (
        metrics_container.get_metric_value(
            ReconcileActionCounter,
            org_id=org_id,
            action=ReconcileActionCounter.Action.RemoveUser,
        )
        == 0
    )

    # verify cluster has been reconciled
    reconcile_cluster_roles_mock.assert_called_once()

    # verify issue signaling
    signal_cluster_validation_error_mock.assert_not_called()
    signal_cluster_reconcile_error_mock.assert_called_once()
