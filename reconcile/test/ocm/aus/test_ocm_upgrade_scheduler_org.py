from typing import Any

from pytest_mock import MockerFixture

from reconcile.aus.base import AdvancedUpgradeSchedulerBaseIntegrationParams
from reconcile.aus.healthchecks import AUSClusterHealth
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    NodePoolSpec,
    OrganizationUpgradeSpec,
)
from reconcile.aus.ocm_addons_upgrade_scheduler_org import (
    OCMAddonsUpgradeSchedulerOrgIntegration,
)
from reconcile.aus.ocm_upgrade_scheduler_org import (
    OCMClusterUpgradeSchedulerOrgIntegration,
)
from reconcile.gql_definitions.common.ocm_env_telemeter import OCMEnvTelemeterQueryData
from reconcile.gql_definitions.fragments.aus_organization import (
    AUSOCMOrganization,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.test.ocm.aus.fixtures import (
    build_addon_upgrade_spec,
    build_organization,
    build_upgrade_policy_cluster,
)
from reconcile.test.ocm.fixtures import build_cluster_details
from reconcile.utils.ocm.base import ClusterDetails

ORG_ID = "org-id"


def setup_mocks(
    mocker: MockerFixture,
    orgs: list[AUSOCMOrganization],
    clusters: list[ClusterDetails],
    node_pool_specs_by_org_cluster: dict[str, dict[str, list[NodePoolSpec]]]
    | None = None,
) -> dict[str, Any]:
    return {
        "gql": mocker.patch("reconcile.aus.base.gql"),
        "get_orgs_for_environment": mocker.patch(
            "reconcile.aus.base.get_orgs_for_environment",
            return_value=orgs,
        ),
        "init_ocm_base_client": mocker.patch(
            "reconcile.aus.ocm_upgrade_scheduler_org.init_ocm_base_client",
        ),
        "init_ocm_base_client_for_org": mocker.patch(
            "reconcile.aus.ocm_addons_upgrade_scheduler_org.init_ocm_base_client_for_org",
        ),
        "get_version_data_map": mocker.patch(
            "reconcile.aus.base.get_version_data_map",
        ),
        "discover_clusters_for_organizations": mocker.patch(
            "reconcile.aus.ocm_upgrade_scheduler_org.discover_clusters_for_organizations",
            return_value=clusters,
        ),
        "get_app_interface_vault_settings": mocker.patch(
            "reconcile.utils.runtime.integration.get_app_interface_vault_settings",
        ),
        "create_secret_reader": mocker.patch(
            "reconcile.utils.runtime.integration.create_secret_reader"
        ),
        "ocm_env_telemeter_query": mocker.patch(
            "reconcile.aus.base.ocm_env_telemeter_query",
            return_value=OCMEnvTelemeterQueryData(ocm_envs=[]),
        ),
        "get_node_pool_specs_by_org_cluster": mocker.patch(
            "reconcile.aus.ocm_upgrade_scheduler_org.get_node_pool_specs_by_org_cluster",
            return_value=node_pool_specs_by_org_cluster or {},
        ),
    }


def test_get_ocm_env_upgrade_specs_when_no_orgs(
    mocker: MockerFixture,
    ocm_env: OCMEnvironment,
) -> None:
    setup_mocks(mocker, orgs=[], clusters=[])
    integration = OCMClusterUpgradeSchedulerOrgIntegration(
        params=AdvancedUpgradeSchedulerBaseIntegrationParams(
            ocm_organization_ids={ORG_ID},
            excluded_ocm_organization_ids=set(),
        ),
    )

    upgrade_specs = integration.get_ocm_env_upgrade_specs(ocm_env)

    assert upgrade_specs == {}


def test_get_ocm_env_upgrade_specs(
    mocker: MockerFixture,
    ocm_env: OCMEnvironment,
) -> None:
    org = build_organization(org_id=ORG_ID)
    upgrade_policy_cluster = build_upgrade_policy_cluster(name="cluster-1")
    org.upgrade_policy_clusters = [upgrade_policy_cluster]
    cluster = build_cluster_details("cluster-1", org_id=ORG_ID, hypershift=True)
    node_pool_spec = NodePoolSpec(id="np1", version="4.15.17")
    setup_mocks(
        mocker,
        orgs=[org],
        clusters=[cluster],
        node_pool_specs_by_org_cluster={
            ORG_ID: {cluster.ocm_cluster.id: [node_pool_spec]}
        },
    )
    expected_cluster_upgrade_spec = ClusterUpgradeSpec(
        org=org,
        upgradePolicy=upgrade_policy_cluster.upgrade_policy,
        cluster=cluster.ocm_cluster,
        cluster_labels=cluster.labels,
        health=AUSClusterHealth(state={}),
        nodePools=[node_pool_spec],
    )
    expected_upgrade_specs = {
        org.name: OrganizationUpgradeSpec(
            org=org,
            specs=[expected_cluster_upgrade_spec],
        )
    }
    integration = OCMClusterUpgradeSchedulerOrgIntegration(
        params=AdvancedUpgradeSchedulerBaseIntegrationParams(
            ocm_organization_ids={ORG_ID},
            excluded_ocm_organization_ids=set(),
        ),
    )

    upgrade_specs = integration.get_ocm_env_upgrade_specs(ocm_env)

    assert upgrade_specs == expected_upgrade_specs
    assert upgrade_specs[org.name].specs[0] == expected_cluster_upgrade_spec


def test_get_ocm_env_upgrade_specs_for_org_without_clusters(
    mocker: MockerFixture,
    ocm_env: OCMEnvironment,
) -> None:
    org = build_organization(org_id=ORG_ID)
    setup_mocks(
        mocker,
        orgs=[org],
        clusters=[],
        node_pool_specs_by_org_cluster={},
    )
    expected_upgrade_specs = {
        org.name: OrganizationUpgradeSpec(
            org=org,
            specs=[],
        )
    }
    integration = OCMClusterUpgradeSchedulerOrgIntegration(
        params=AdvancedUpgradeSchedulerBaseIntegrationParams(
            ocm_organization_ids={ORG_ID},
            excluded_ocm_organization_ids=set(),
        ),
    )

    upgrade_specs = integration.get_ocm_env_upgrade_specs(ocm_env)

    assert upgrade_specs == expected_upgrade_specs


def test_addons_upgrade_scheduler_process_upgrade_policies_in_org(
    mocker: MockerFixture,
    ocm_env: OCMEnvironment,
) -> None:
    org = build_organization(org_id=ORG_ID)
    addon1 = build_addon_upgrade_spec(cluster_name="cluster-1", addon_id="addon-1")
    addon2 = build_addon_upgrade_spec(cluster_name="cluster-1", addon_id="addon-2")
    org_upgrade_spec = OrganizationUpgradeSpec(
        org=org,
        specs=[
            addon1,
            addon2,
        ],
    )
    setup_mocks(
        mocker,
        orgs=[org],
        clusters=[],
    )
    integration = OCMAddonsUpgradeSchedulerOrgIntegration(
        params=AdvancedUpgradeSchedulerBaseIntegrationParams(
            ocm_organization_ids={ORG_ID},
            excluded_ocm_organization_ids=set(),
        ),
    )
    expose_remaining_soak_day_metrics = mocker.patch.object(
        integration, "expose_remaining_soak_day_metrics"
    )

    integration.process_upgrade_policies_in_org(
        dry_run=True,
        org_upgrade_spec=org_upgrade_spec,
    )

    assert expose_remaining_soak_day_metrics.call_count == 2
    assert (
        len(
            expose_remaining_soak_day_metrics.call_args_list[0]
            .kwargs["org_upgrade_spec"]
            .specs
        )
        == 1
    )
    assert (
        len(
            expose_remaining_soak_day_metrics.call_args_list[1]
            .kwargs["org_upgrade_spec"]
            .specs
        )
        == 1
    )
