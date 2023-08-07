from typing import Optional

import pytest
from pytest_mock import MockerFixture

from reconcile.oum import standalone
from reconcile.oum.base import OCMUserManagementIntegrationParams
from reconcile.oum.labelset import build_cluster_config_from_labels
from reconcile.oum.models import (
    ClusterUserManagementSpec,
    ExternalGroupRef,
)
from reconcile.test.ocm.fixtures import (
    build_cluster_details,
    build_label,
)
from reconcile.utils.ocm.base import (
    LabelContainer,
    build_label_container,
)
from reconcile.utils.ocm.cluster_groups import OCMClusterGroupId
from reconcile.utils.ocm.labels import build_container_for_prefix
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient

#
# test labelset
#


def build_provider_authz_labels(
    provider: str,
    dedicated_admins_groups: Optional[set[str]] = None,
    cluster_admins_groups: Optional[set[str]] = None,
) -> LabelContainer:
    labels = []
    if dedicated_admins_groups:
        labels.append(
            build_label(
                standalone.user_mgmt_label_key(f"{provider}.authz.dedicated-admins"),
                ",".join(dedicated_admins_groups),
            )
        )
    if cluster_admins_groups:
        labels.append(
            build_label(
                standalone.user_mgmt_label_key(f"{provider}.authz.cluster-admins"),
                ",".join(cluster_admins_groups),
            )
        )
    return build_label_container(labels)


def build_authz_labels(
    dedicated_admins_groups: Optional[set[str]] = None,
    cluster_admins_groups: Optional[set[str]] = None,
) -> LabelContainer:
    provider = "provider"
    label_container = build_provider_authz_labels(
        provider=provider,
        dedicated_admins_groups=dedicated_admins_groups,
        cluster_admins_groups=cluster_admins_groups,
    )
    return build_container_for_prefix(
        label_container, standalone.user_mgmt_label_key(f"{provider}."), True
    )


@pytest.mark.parametrize("labelsource", [("org"), ("sub")])
def test_authz_labels_single_source(labelsource: str) -> None:
    provider = "provider"
    labels = build_authz_labels({"da1", "da2"}, {"ca"})
    mappings = build_cluster_config_from_labels(
        provider=provider,
        org_labels=labels if labelsource == "org" else LabelContainer(),
        subscription_labels=labels if labelsource == "sub" else LabelContainer(),
    )
    assert OCMClusterGroupId.DEDICATED_ADMINS in mappings
    assert {
        (rm.provider, rm.group_id)
        for rm in mappings[OCMClusterGroupId.DEDICATED_ADMINS]
    } == {(provider, "da1"), (provider, "da2")}
    assert OCMClusterGroupId.CLUSTER_ADMINS in mappings
    assert {
        (rm.provider, rm.group_id) for rm in mappings[OCMClusterGroupId.CLUSTER_ADMINS]
    } == {(provider, "ca")}


def test_authz_org_and_sub_labels() -> None:
    provider = "provider"
    org_labels = build_authz_labels(
        {"da_from_org", "da_common"}, {"ca_from_org", "ca_common"}
    )
    sub_labels = build_authz_labels(
        {"da_from_sub", "da_common"}, {"ca_from_sub", "ca_common"}
    )
    mappings = build_cluster_config_from_labels(
        provider=provider,
        org_labels=org_labels,
        subscription_labels=sub_labels,
    )
    assert OCMClusterGroupId.DEDICATED_ADMINS in mappings
    assert {
        (rm.provider, rm.group_id)
        for rm in mappings[OCMClusterGroupId.DEDICATED_ADMINS]
    } == {(provider, "da_from_org"), (provider, "da_from_sub"), (provider, "da_common")}
    assert OCMClusterGroupId.CLUSTER_ADMINS in mappings
    assert {
        (rm.provider, rm.group_id) for rm in mappings[OCMClusterGroupId.CLUSTER_ADMINS]
    } == {(provider, "ca_from_org"), (provider, "ca_from_sub"), (provider, "ca_common")}


#
# test build_user_management_configurations
#


def test_build_user_management_configurations() -> None:
    org_id = "org_id"
    provider = "provider"
    org_config = standalone.build_user_management_configurations(
        org_id=org_id,
        clusters=[
            build_cluster_details(
                cluster_name="cluster",
                subscription_labels=build_provider_authz_labels(
                    provider=provider,
                    cluster_admins_groups={"ca"},
                ),
                organization_labels=build_provider_authz_labels(
                    provider=provider, dedicated_admins_groups={"da"}
                ),
                org_id=org_id,
            )
        ],
        providers={provider},
    )
    assert org_config.org_id == org_id
    assert org_config.cluster_configs[0].cluster.ocm_cluster.name == "cluster"
    assert org_config.cluster_configs[0].roles[OCMClusterGroupId.DEDICATED_ADMINS] == [
        ExternalGroupRef(provider=provider, group_id="da")
    ]
    assert org_config.cluster_configs[0].roles[OCMClusterGroupId.CLUSTER_ADMINS] == [
        ExternalGroupRef(provider=provider, group_id="ca")
    ]


def test_build_user_management_configurations_no_authz_labels() -> None:
    org_id = "org_id"
    provider = "provider"
    org_config = standalone.build_user_management_configurations(
        org_id=org_id,
        clusters=[
            build_cluster_details(
                cluster_name="cluster",
                subscription_labels=LabelContainer(
                    labels={
                        standalone.user_mgmt_label_key("some-other-label"): build_label(
                            standalone.user_mgmt_label_key("some-other-label"),
                            "some-value",
                        )
                    }
                ),
                org_id=org_id,
            )
        ],
        providers={provider},
    )
    assert org_config.org_id == org_id
    assert org_config.cluster_configs[0].cluster.ocm_cluster.name == "cluster"
    assert org_config.cluster_configs[0].roles == {}


#
# test discover clusters
#


@pytest.mark.parametrize(
    "org_id_filter,expected_cluster_names",
    [
        (None, {"org-id-1": {"cluster-1"}, "org-id-2": {"cluster-2"}}),
        ({"org-id-1"}, {"org-id-1": {"cluster-1"}}),
    ],
)
def test_discover_clusters(
    org_id_filter: Optional[set[str]],
    expected_cluster_names: dict[str, set[str]],
    ocm_api: OCMBaseClient,
    mocker: MockerFixture,
) -> None:
    org_id_1 = "org-id-1"
    cluster_name_1 = "cluster-1"
    org_id_2 = "org-id-2"
    cluster_name_2 = "cluster-2"

    discover_clusters_by_labels_mock = mocker.patch.object(
        standalone,
        "discover_clusters_by_labels",
        autospec=True,
    )
    discover_clusters_by_labels_mock.return_value = [
        build_cluster_details(
            cluster_name=cluster_name_1,
            subscription_labels=build_authz_labels({"group"}),
            org_id=org_id_1,
        ),
        build_cluster_details(
            cluster_name=cluster_name_2,
            subscription_labels=build_authz_labels({"group"}),
            org_id=org_id_2,
        ),
    ]

    clusters_by_org = standalone.discover_clusters(ocm_api, org_id_filter)

    discover_clusters_by_labels_mock.assert_called_once_with(
        ocm_api=ocm_api,
        label_filter=Filter().like("key", standalone.user_mgmt_label_key("%")),
    )

    assert {
        org: {c.ocm_cluster.name for c in clusters}
        for org, clusters in clusters_by_org.items()
    } == expected_cluster_names


#
# Test signals
#


@pytest.mark.parametrize(
    "dry_run",
    [True, False],
)
def test_signal_cluster_reconcile_success(
    dry_run: bool, ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    create_service_log_mock = mocker.patch.object(
        standalone,
        "create_service_log",
        autospec=True,
    )

    integration = standalone.OCMStandaloneUserManagementIntegration(
        OCMUserManagementIntegrationParams(group_provider_specs=[])
    )

    cluster = build_cluster_details(cluster_name="cluster")
    spec = ClusterUserManagementSpec(
        cluster=cluster,
        roles={
            OCMClusterGroupId.DEDICATED_ADMINS: {"user-1", "user-2"},
        },
        errors=[],
    )
    integration.signal_cluster_reconcile_success(
        dry_run=dry_run, ocm_api=ocm_api, spec=spec, message="profit!"
    )

    if dry_run:
        assert create_service_log_mock.call_count == 0
    else:
        assert create_service_log_mock.call_count == 1


@pytest.mark.parametrize(
    "dry_run",
    [True, False],
)
def test_signal_cluster_validation_error(
    dry_run: bool, ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    create_service_log_mock = mocker.patch.object(
        standalone,
        "create_service_log",
        autospec=True,
    )

    integration = standalone.OCMStandaloneUserManagementIntegration(
        OCMUserManagementIntegrationParams(group_provider_specs=[])
    )

    cluster = build_cluster_details(cluster_name="cluster")
    spec = ClusterUserManagementSpec(
        cluster=cluster,
        roles={
            OCMClusterGroupId.DEDICATED_ADMINS: {"user-1", "user-2"},
        },
        errors=[],
    )
    integration.signal_cluster_validation_error(
        dry_run=dry_run,
        ocm_api=ocm_api,
        spec=spec,
        error=Exception("something went wrong"),
    )

    if dry_run:
        assert create_service_log_mock.call_count == 0
    else:
        assert create_service_log_mock.call_count == 1
