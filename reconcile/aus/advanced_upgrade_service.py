import logging
from collections import defaultdict
from typing import Optional

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    validator,
)

from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.aus.ocm_upgrade_scheduler_org import (
    OCMClusterUpgradeSchedulerOrgIntegration,
)
from reconcile.gql_definitions.fragments.aus_organization import (
    AUSOCMOrganization,
    OpenShiftClusterManagerSectorDependenciesV1,
    OpenShiftClusterManagerSectorV1,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.upgrade_policy import (
    ClusterUpgradePolicy,
    ClusterUpgradePolicyConditionsV1,
)
from reconcile.utils.models import (
    CSV,
    cron_validator,
    data_default_none,
)
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import (
    LabelContainer,
    OCMOrganizationLabel,
    build_label_container,
    get_organization_labels,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.sre_capability_labels import (
    build_labelset,
    labelset_groupfield,
    sre_capability_label_key,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)

QONTRACT_INTEGRATION = "advanced-upgrade-scheduler"


class AdvancedUpgradeServiceIntegration(OCMClusterUpgradeSchedulerOrgIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        # organizations have no name in OCM (just in app-interface), but the
        # org_name parameter can still be used to filter by organization ID
        org_id = org_name
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters_by_org = discover_clusters(ocm_api=ocm_api, org_id=org_id)
        labels_by_org = get_org_labels(ocm_api=ocm_api, org_id=org_id)

        org_upgrade_specs = build_org_upgrade_specs_for_ocm_env(
            ocm_env=ocm_env,
            clusters_by_org=clusters_by_org,
            labels_by_org=labels_by_org,
        )
        for org_id, org_spec in org_upgrade_specs.items():
            if org_spec.cluster_errors:
                logging.error(
                    f"Errors found in {ocm_env.name} org {org_id}: "
                    f"{org_spec.cluster_errors}"
                )
                # todo create service logs

            if org_spec.org_errors:
                logging.error(
                    f"Errors found in {ocm_env.name} org {org_id}: "
                    f"{org_spec.org_errors}"
                )
                # todo create service logs

        # return only flawless org specs
        return {
            org_id: org_spec
            for org_id, org_spec in org_upgrade_specs.items()
            if not org_spec.org_errors and not org_spec.cluster_errors
        }


def discover_clusters(
    ocm_api: OCMBaseClient, org_id: Optional[str] = None
) -> dict[str, list[ClusterDetails]]:
    clusters = discover_clusters_by_labels(
        ocm_api=ocm_api,
        label_filter=Filter().like("key", aus_label_key("%")),
    )

    # group by org and filter if org_id is specified
    clusters_by_org: dict[str, list[ClusterDetails]] = defaultdict(list)
    for c in clusters:
        if org_id is None or c.organization_id == org_id:
            clusters_by_org[c.organization_id].append(c)

    return clusters_by_org


def get_org_labels(
    ocm_api: OCMBaseClient, org_id: Optional[str]
) -> dict[str, LabelContainer]:
    filter = Filter().like("key", aus_label_key("%"))
    if org_id is not None:
        filter = filter.eq("organization_id", org_id)
    labels_by_org: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
    for label in get_organization_labels(ocm_api, filter):
        labels_by_org[label.organization_id].append(label)
    return {
        org_id: build_label_container(labels)
        for org_id, labels in labels_by_org.items()
    }


def build_org_upgrade_specs_for_ocm_env(
    ocm_env: OCMEnvironment,
    clusters_by_org: dict[str, list[ClusterDetails]],
    labels_by_org: dict[str, LabelContainer],
) -> dict[str, OrganizationUpgradeSpec]:
    org_upgrade_specs = {}
    for org_id, clusters in clusters_by_org.items():
        org_spec = build_org_upgrade_spec(
            ocm_env,
            org_id,
            clusters,
            labels_by_org.get(org_id) or build_label_container(),
        )

        # if there is at least one valid cluster upgrade policy spec
        # and no organization validation errors, the organization will
        # be passed on
        org_upgrade_specs[org_id] = org_spec

    return org_upgrade_specs


def aus_label_key(config_atom: str) -> str:
    """
    Generates label keys for aus, compliant with the naming schema defined in
    https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
    """
    return sre_capability_label_key("aus", config_atom)


class OrganizationLabelSet(BaseModel):
    """
    Parses, represents and validates a set of organization labels for AUS.
    """

    blocked_versions: Optional[CSV] = Field(alias=aus_label_key("blocked-versions"))

    sector_deps: dict[str, CSV] = labelset_groupfield(
        group_prefix=aus_label_key("sector-deps.")
    )
    """
    Each sector with dependencies is represented as a `sector-deps.<sector-name>` label
    with a CSV formatted list of dependant sectors. The custom `labelset_groupfield``
    FieldMeta combined with the CSV field type takes care of grouping and parsing
    labels into a dict where each sector is a key and their dependencies are the value.
    """

    def sector_dependencies(self) -> list[OpenShiftClusterManagerSectorV1]:
        """
        Transforms the sector dependencies into the appropriate dataclasses
        required by the upgrade policy spec.
        """
        all_sectors = set()
        for s, deps in self.sector_deps.items():
            all_sectors.add(s)
            all_sectors.update(deps)
        return [
            OpenShiftClusterManagerSectorV1(
                name=s,
                dependencies=[
                    OpenShiftClusterManagerSectorDependenciesV1(name=d, ocm=None)
                    for d in self.sector_deps.get(s, [])
                ],
            )
            for s in all_sectors
        ]


def build_org_upgrade_spec(
    ocm_env: OCMEnvironment,
    org_id: str,
    clusters: list[ClusterDetails],
    org_labels: LabelContainer,
) -> OrganizationUpgradeSpec:
    """
    Build a upgrade policy spec for each cluster in the organization that
    has a valid set of labels. Clusters without a set of labels are ignored. Clusters
    with an invalid/incomplete set of labels are reported as an error.
    """
    org_labelset = build_labelset(org_labels, OrganizationLabelSet)
    org_upgrade_spec = OrganizationUpgradeSpec(
        org=AUSOCMOrganization(
            **data_default_none(
                AUSOCMOrganization,
                dict(
                    name=org_id,
                    orgId=org_id,
                    blockedVersions=org_labelset.blocked_versions,
                    environment=ocm_env,
                    addonManagedUpgrades=False,
                    sectors=org_labelset.sector_dependencies(),
                ),
            )
        )
    )

    for c in clusters:
        try:
            upgrade_policy = build_policy_from_labels(c.labels)
            org_upgrade_spec.specs.append(
                ClusterUpgradeSpec(
                    name=c.ocm_cluster.name,
                    ocm=org_upgrade_spec.org,
                    upgradePolicy=upgrade_policy,
                )
            )
        except ValidationError as validation_error:
            for e in validation_error.errors():
                org_upgrade_spec.add_cluster_error(
                    c.ocm_cluster.id, f"label {e['loc'][0]}: {e['msg']}"
                )

    return org_upgrade_spec


class ClusterUpgradePolicyLabelSet(BaseModel):
    """
    Parses, represents and validates a set of subscription labels for AUS.
    """

    soak_days: int = Field(alias=aus_label_key("soak-days"), ge=0)
    workloads: CSV = Field(alias=aus_label_key("workloads"), csv_min_items=1)
    schedule: str = Field(alias=aus_label_key("schedule"))
    mutexes: Optional[CSV] = Field(alias=aus_label_key("mutexes"))
    sector: Optional[str] = Field(alias=aus_label_key("sector"))
    _schedule_validator = validator("schedule", allow_reuse=True)(cron_validator)


def build_policy_from_labels(labels: LabelContainer) -> ClusterUpgradePolicy:
    """
    Build a cluster upgrade policy object from a set of OCM labels. Parsing
    and validation of the labels is delegated to the pydantic dataclass
    ClusterUpgradePolicyLabelSet.
    """
    policy_labelset = build_labelset(labels, ClusterUpgradePolicyLabelSet)
    return ClusterUpgradePolicy(
        workloads=policy_labelset.workloads,
        schedule=policy_labelset.schedule,
        conditions=ClusterUpgradePolicyConditionsV1(
            soakDays=policy_labelset.soak_days,
            mutexes=policy_labelset.mutexes,
            sector=policy_labelset.sector,
        ),
    )
