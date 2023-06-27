from typing import Optional

from pydantic import BaseModel

from reconcile import queries
from reconcile.aus import base as aus
from reconcile.aus.base import (
    AbstractUpgradePolicy,
    AddonUpgradePolicy,
)
from reconcile.aus.cluster_version_data import VersionDataMap
from reconcile.aus.metrics import AUSOrganizationReconcileCounter
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.ocm import OCMMap
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    discover_clusters_for_organizations,
)
from reconcile.utils.ocm_base_client import init_ocm_base_client

QONTRACT_INTEGRATION = "ocm-addons-upgrade-scheduler-org"


class AUSOrgAddonUpgradeState(BaseModel):
    addon_id: str
    current_state: list[aus.AbstractUpgradePolicy]
    upgrade_policies: list[aus.ConfiguredUpgradePolicy]


class OCMAddonsUpgradeSchedulerOrgIntegration(
    aus.AdvancedUpgradeSchedulerBaseIntegration
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ocm_map, addon_states = get_state_for_org_spec_per_addon(
            org_upgrade_spec, fetch_current_state=True
        )
        for addon_state in addon_states:
            version_data_map = aus.get_version_data_map(
                dry_run=dry_run,
                upgrade_policies=addon_state.upgrade_policies,
                ocm_map=ocm_map,
                addon_id=addon_state.addon_id,
                integration=self.name,
            )
            diffs = calculate_diff(
                addon_state.current_state,
                addon_state.upgrade_policies,
                ocm_map,
                version_data_map,
                addon_id=addon_state.addon_id,
            )
            aus.act(dry_run, diffs, ocm_map, addon_id=addon_state.addon_id)

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        # query all OCM organizations from app-interface and filter by and orgs
        organizations = [
            org
            for org in aus_organizations_query(
                query_func=gql.get_api().query
            ).organizations
            or []
            if org.environment.name == ocm_env.name
            and org.addon_managed_upgrades
            and (org_ids is None or org.org_id in org_ids)
        ]
        if not organizations:
            return {}

        # lookup cluster in OCM to figure out if they exist
        # and to get their UUID
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters = discover_clusters_for_organizations(
            ocm_api, [org.org_id for org in organizations]
        )

        return {
            org.name: OrganizationUpgradeSpec(
                org=org,
                specs=self._build_addon_upgrade_spec(
                    org,
                    {
                        c.ocm_cluster.name: c.ocm_cluster
                        for c in clusters
                        if c.organization_id == org.org_id
                    },
                ),
            )
            for org in organizations
        }

    def _build_addon_upgrade_spec(
        self, org: AUSOCMOrganization, clusters_by_name: dict[str, OCMCluster]
    ) -> list[ClusterUpgradeSpec]:
        return [
            ClusterUpgradeSpec(
                name=cluster.name,
                cluster_uuid=clusters_by_name[cluster.name].external_id,
                current_version=clusters_by_name[cluster.name].version.raw_id,
                ocm=org,
                upgradePolicy=cluster.upgrade_policy,
            )
            for cluster in org.upgrade_policy_clusters or []
            # clusters that are not in the UUID dict will be ignored because
            # they don't exist in the OCM organization (or have been deprovisioned)
            if cluster.name in clusters_by_name
        ]

    def expose_org_upgrade_spec_metrics(
        self, ocm_env: str, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        metrics.inc_counter(
            AUSOrganizationReconcileCounter(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_upgrade_spec.org.org_id,
            )
        )


def get_state_for_org_spec(
    org_upgrade_spec: OrganizationUpgradeSpec, fetch_current_state: bool
) -> tuple[OCMMap, list[aus.AbstractUpgradePolicy], list[aus.ConfiguredUpgradePolicy]]:
    settings = queries.get_app_interface_settings()
    cluster_like_objects = [
        policy.dict(by_alias=True) for policy in org_upgrade_spec.specs
    ]
    ocm_map = OCMMap(
        clusters=cluster_like_objects,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        init_version_gates=True,
        init_addons=True,
    )
    desired_state = aus.fetch_upgrade_policies(
        org_upgrade_spec.specs, ocm_map, addons=True
    )
    current_state: list[aus.AbstractUpgradePolicy] = []
    if fetch_current_state:
        current_state = aus.fetch_current_state(
            org_upgrade_spec.specs,
            ocm_map,
            addons=True,
        )

    return (ocm_map, current_state, desired_state)


def get_state_for_org_spec_per_addon(
    org_upgrade_spec: OrganizationUpgradeSpec, fetch_current_state: bool
) -> tuple[OCMMap, list[AUSOrgAddonUpgradeState]]:
    ocm_map, current_state, desired_state = get_state_for_org_spec(
        org_upgrade_spec, fetch_current_state
    )
    result = []
    for addon_id in set(
        a.addon_id
        for a in desired_state
        if isinstance(a, aus.ConfiguredAddonUpgradePolicy)
    ):
        addon_current_state = [
            c
            for c in current_state
            if isinstance(c, aus.AddonUpgradePolicy) and c.addon_id == addon_id
        ]
        addon_desired_state = [
            d
            for d in desired_state
            if isinstance(d, aus.ConfiguredAddonUpgradePolicy)
            and d.addon_id == addon_id
        ]
        result.append(
            AUSOrgAddonUpgradeState(
                addon_id=addon_id,
                current_state=addon_current_state,
                upgrade_policies=addon_desired_state,
            )
        )
    return ocm_map, result


def calculate_diff(
    addon_current_state: list[AbstractUpgradePolicy],
    addon_upgrade_policies: list[aus.ConfiguredUpgradePolicy],
    ocm_map: OCMMap,
    version_data_map: VersionDataMap,
    addon_id: str = "",
) -> list[aus.UpgradePolicyHandler]:
    diffs = aus.calculate_diff(
        addon_current_state,
        addon_upgrade_policies,
        ocm_map,
        version_data_map,
        addon_id=addon_id,
    )
    for current in addon_current_state:
        if (
            isinstance(current, AddonUpgradePolicy)
            and addon_id == current.addon_id
            and current.schedule_type == "automatic"
        ):
            diffs.append(
                aus.UpgradePolicyHandler(
                    action="delete",
                    policy=aus.AddonUpgradePolicy(
                        **{
                            "cluster": current.cluster,
                            "version": current.schedule_type,
                            "id": current.id,
                            "addon_id": current.addon_id,
                            "schedule_type": current.schedule_type,
                        }
                    ),
                )
            )
    return diffs
