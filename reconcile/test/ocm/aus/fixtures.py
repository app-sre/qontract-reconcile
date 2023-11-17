from datetime import datetime
from typing import Optional

from reconcile.aus.base import ClusterUpgradePolicy
from reconcile.aus.models import (
    ClusterAddonUpgradeSpec,
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.fragments.aus_organization import (
    AUSOCMOrganization,
    OpenShiftClusterManagerSectorDependenciesV1,
    OpenShiftClusterManagerSectorV1,
    OpenShiftClusterManagerV1_OpenShiftClusterManagerV1,
    OpenShiftClusterManagerV1_OpenShiftClusterManagerV1_OpenShiftClusterManagerEnvironmentV1,
)
from reconcile.gql_definitions.fragments.disable import DisableAutomations
from reconcile.gql_definitions.fragments.minimal_ocm_organization import (
    MinimalOCMOrganization,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.upgrade_policy import (
    ClusterUpgradePolicyConditionsV1,
    ClusterUpgradePolicyV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.utils.ocm.base import (
    OCMAddonInstallation,
    OCMAddonVersion,
    OCMModelLink,
)
from reconcile.utils.ocm.clusters import OCMCluster


def build_upgrade_policy(
    soak_days: int = 0,
    workloads: Optional[list[str]] = None,
    schedule: Optional[str] = None,
    sector: Optional[str] = None,
    mutexes: Optional[list[str]] = None,
    blocked_versions: Optional[list[str]] = None,
) -> ClusterUpgradePolicyV1:
    return ClusterUpgradePolicyV1(
        schedule=schedule or "* * * * *",
        workloads=workloads or ["workload1"],
        conditions=ClusterUpgradePolicyConditionsV1(
            soakDays=soak_days,
            sector=sector,
            mutexes=mutexes,
            blockedVersions=blocked_versions,
        ),
    )


def build_ocm_environment(env_name: Optional[str] = None) -> OCMEnvironment:
    return OCMEnvironment(
        name=env_name or "env-name",
        accessTokenClientId="client-id",
        accessTokenUrl="https://token-url",
        accessTokenClientSecret=VaultSecret(
            path="secret/path", field="field", version=None, format=None
        ),
        url="https://ocm-url",
    )


def build_organization(
    org_id: Optional[str] = None,
    org_name: Optional[str] = None,
    env_name: Optional[str] = None,
    ocm_env: Optional[OCMEnvironment] = None,
    inherit_version_data_from_org_ids: Optional[list[tuple[str, str, bool]]] = None,
    publish_version_data_from_org_ids: Optional[list[str]] = None,
    blocked_versions: Optional[list[str]] = None,
    sector_dependencies: Optional[dict[str, Optional[list[str]]]] = None,
    addonManagedUpgrades: bool = False,
    disabled_integrations: Optional[list[str]] = None,
) -> AUSOCMOrganization:
    org_id = org_id or "org-1-id"
    disable = DisableAutomations(
        integrations=disabled_integrations
    ) if disabled_integrations else None
    return AUSOCMOrganization(
        name=org_name or "org-name",
        environment=ocm_env or build_ocm_environment(env_name or "env-name"),
        orgId=org_id,
        blockedVersions=blocked_versions,
        inheritVersionData=[
            OpenShiftClusterManagerV1_OpenShiftClusterManagerV1(
                environment=OpenShiftClusterManagerV1_OpenShiftClusterManagerV1_OpenShiftClusterManagerEnvironmentV1(
                    name=other_env,
                ),
                orgId=other_org_id,
                name=other_org_id,
                publishVersionData=[
                    MinimalOCMOrganization(name=org_name or org_id, orgId=org_id)
                ]
                if valid_peering
                else None,
            )
            for other_env, other_org_id, valid_peering in inherit_version_data_from_org_ids
            or []
        ],
        publishVersionData=[
            MinimalOCMOrganization(name=org_id or org_id, orgId=org_id)
            for org_id in publish_version_data_from_org_ids or []
        ],
        accessTokenClientId=None,
        accessTokenUrl=None,
        accessTokenClientSecret=None,
        upgradePolicyClusters=None,
        upgradePolicyAllowedWorkloads=None,
        addonManagedUpgrades=addonManagedUpgrades,
        addonUpgradeTests=None,
        disable=disable,
        sectors=[
            OpenShiftClusterManagerSectorV1(
                name=sector,
                dependencies=[
                    OpenShiftClusterManagerSectorDependenciesV1(
                        name=dep,
                        ocm=None,
                    )
                    for dep in dependencies
                ]
                if dependencies
                else None,
            )
            for sector, dependencies in sector_dependencies.items()
        ]
        if sector_dependencies
        else None,
    )


def build_organization_upgrade_spec(
    specs: list[tuple[OCMCluster, ClusterUpgradePolicyV1]],
    org: Optional[AUSOCMOrganization] = None,
) -> OrganizationUpgradeSpec:
    org = org or build_organization()
    return OrganizationUpgradeSpec(
        org=org,
        specs=[
            ClusterUpgradeSpec(
                org=org,
                cluster=cluster,
                upgradePolicy=upgrade_policy,
            )
            for cluster, upgrade_policy in specs
        ],
    )


def build_cluster_upgrade_spec(
    name: str,
    current_version: str = "4.13.0",
    workloads: Optional[list[str]] = None,
    soak_days: int = 0,
    org: Optional[AUSOCMOrganization] = None,
    available_upgrades: Optional[list[str]] = None,
    mutexes: Optional[list[str]] = None,
    blocked_versions: Optional[list[str]] = None,
) -> ClusterUpgradeSpec:
    return ClusterUpgradeSpec(
        org=org or build_organization(),
        cluster=build_ocm_cluster(
            name=name, version=current_version, available_upgrades=available_upgrades
        ),
        upgradePolicy=build_upgrade_policy(
            workloads=workloads,
            soak_days=soak_days,
            mutexes=mutexes,
            blocked_versions=blocked_versions,
        ),
    )


def build_addon_upgrade_spec(
    cluster_name: str,
    addon_id: str,
    current_cluster_version: str = "4.13.0",
    current_addon_version: str = "1.2.3",
    addon_state: str = "ready",
    workloads: Optional[list[str]] = None,
    soak_days: int = 0,
    org: Optional[AUSOCMOrganization] = None,
    available_cluster_upgrades: Optional[list[str]] = None,
    available_addon_upgrades: Optional[list[str]] = None,
) -> ClusterAddonUpgradeSpec:
    return ClusterAddonUpgradeSpec(
        org=org or build_organization(),
        cluster=build_ocm_cluster(
            name=cluster_name,
            version=current_cluster_version,
            available_upgrades=available_cluster_upgrades,
        ),
        upgradePolicy=build_upgrade_policy(workloads=workloads, soak_days=soak_days),
        addon=OCMAddonInstallation(
            id=addon_id,
            addon=OCMModelLink(
                id=addon_id,
                href=f"/api/addons/{addon_id}",
            ),
            addon_version=OCMAddonVersion(
                id=current_addon_version,
                href=f"/api/addon-versions/{current_addon_version}",
                available_upgrades=available_addon_upgrades or [],
            ),
            state=addon_state,
        ),
    )


def build_cluster_upgrade_policy(
    cluster: OCMCluster, version: str, state: str, next_run: Optional[datetime] = None
) -> ClusterUpgradePolicy:
    next_run_str = (next_run or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ClusterUpgradePolicy(
        cluster=cluster,
        id="1",
        version=version,
        state=state,
        next_run=next_run_str,
        schedule_type="manual",
        schedule=None,
    )
