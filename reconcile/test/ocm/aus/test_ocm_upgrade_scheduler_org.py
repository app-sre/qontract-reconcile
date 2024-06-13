from typing import Any

from pytest_mock import MockerFixture

from reconcile.aus.base import AdvancedUpgradeSchedulerBaseIntegrationParams
from reconcile.aus.healthchecks import AUSClusterHealth
from reconcile.aus.models import ClusterUpgradeSpec, OrganizationUpgradeSpec
from reconcile.aus.ocm_upgrade_scheduler_org import (
    OCMClusterUpgradeSchedulerOrgIntegration,
)
from reconcile.gql_definitions.common.ocm_env_telemeter import OCMEnvTelemeterQueryData
from reconcile.gql_definitions.fragments.aus_organization import (
    AUSOCMOrganization,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.test.ocm.aus.fixtures import (
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
    cluster = build_cluster_details("cluster-1", org_id=ORG_ID)
    setup_mocks(mocker, orgs=[org], clusters=[cluster])
    expected_cluster_upgrade_spec = ClusterUpgradeSpec(
        org=org,
        upgradePolicy=upgrade_policy_cluster.upgrade_policy,
        cluster=cluster.ocm_cluster,
        health=AUSClusterHealth(state={}),
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
