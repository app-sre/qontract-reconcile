import logging
from collections import defaultdict
from datetime import timedelta
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
    subscription_label_filter,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.service_log import (
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
    create_service_log,
)
from reconcile.utils.ocm.sre_capability_labels import (
    build_labelset,
    labelset_groupfield,
    sre_capability_label_key,
)
from reconcile.utils.ocm.subscriptions import (
    OCMOrganization,
    get_organizations,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)

QONTRACT_INTEGRATION = "advanced-upgrade-scheduler"


class AdvancedUpgradeServiceIntegration(OCMClusterUpgradeSchedulerOrgIntegration):
    """
    A flavour of the OCM organization based upgrade scheduler, that uses
    OCM labels to discover clusters and their upgrade policies.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=org_ids,
            ignore_sts_clusters=self.params.ignore_sts_clusters,
        )
        orgs = (
            get_organizations(
                ocm_api=ocm_api, filter=Filter().is_in("id", clusters_by_org.keys())
            )
            if clusters_by_org
            else {}
        )
        labels_by_org = _get_org_labels(ocm_api=ocm_api, org_ids=org_ids)

        return _build_org_upgrade_specs_for_ocm_env(
            ocm_env=ocm_env,
            orgs=orgs,
            clusters_by_org=clusters_by_org,
            labels_by_org=labels_by_org,
        )

    def signal_validation_issues(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        if not dry_run:
            ocm_api = init_ocm_base_client(
                org_upgrade_spec.org.environment, self.secret_reader
            )
            _signal_validation_issues_for_org(
                ocm_api=ocm_api, org_upgrade_spec=org_upgrade_spec
            )

    def signal_reconcile_issues(
        self,
        dry_run: bool,
        org_upgrade_spec: OrganizationUpgradeSpec,
        exception: Exception,
    ) -> bool:
        """
        AUS will not fail on a reconcile issue. If issues should be noticed by an SRE team,
        alerts based on the metrics in the `reconcile.aus.metrics` module should be set up.

        The function is an override on the default behaviour to not ignore errors.
        It returns true to indicate that the exception was properly handled by logging it.
        Users / org owners will not be notified about the exception via service logs.
        AppSRE team members will be notified about the exception via the logs.

        """
        logging.error(
            f"Failed to reconcile cluster upgrades in OCM organization {org_upgrade_spec.org.org_id}",
            exc_info=exception,
        )
        return True


def discover_clusters(
    ocm_api: OCMBaseClient,
    org_ids: Optional[set[str]] = None,
    ignore_sts_clusters: bool = False,
) -> dict[str, list[ClusterDetails]]:
    """
    Discover all clusters that are part of the AUS service.
    Discovery is driven by OCM cluster labels.
    """
    clusters = discover_clusters_by_labels(
        ocm_api=ocm_api,
        label_filter=subscription_label_filter().like("key", aus_label_key("%")),
    )

    # group by org and filter if org_id is specified
    clusters_by_org: dict[str, list[ClusterDetails]] = defaultdict(list)
    for c in clusters:
        is_sts_cluster = c.ocm_cluster.aws and c.ocm_cluster.aws.sts_enabled
        passed_sts_filter = not ignore_sts_clusters or not is_sts_cluster
        passed_ocm_filters = org_ids is None or c.organization_id in org_ids
        if passed_ocm_filters and passed_sts_filter:
            clusters_by_org[c.organization_id].append(c)

    return clusters_by_org


def _get_org_labels(
    ocm_api: OCMBaseClient, org_ids: Optional[set[str]]
) -> dict[str, LabelContainer]:
    """
    Fetch all AUS OCM org labels from organizations. They hold config
    parameters like blocked versions etc.
    """
    filter = Filter().like("key", aus_label_key("%")).is_in("organization_id", org_ids)
    labels_by_org: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
    for label in get_organization_labels(ocm_api, filter):
        labels_by_org[label.organization_id].append(label)
    return {
        org_id: build_label_container(labels)
        for org_id, labels in labels_by_org.items()
    }


def _build_org_upgrade_specs_for_ocm_env(
    ocm_env: OCMEnvironment,
    orgs: dict[str, OCMOrganization],
    clusters_by_org: dict[str, list[ClusterDetails]],
    labels_by_org: dict[str, LabelContainer],
) -> dict[str, OrganizationUpgradeSpec]:
    """
    Builds the cluster upgrade specs for the given OCM environment.
    The specs are returned grouped by organization.
    """
    return {
        org_id: _build_org_upgrade_spec(
            ocm_env,
            orgs[org_id],
            clusters,
            labels_by_org.get(org_id) or build_label_container(),
        )
        for org_id, clusters in clusters_by_org.items()
    }


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


def _build_org_upgrade_spec(
    ocm_env: OCMEnvironment,
    org: OCMOrganization,
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
            name=org.name,
            orgId=org.id,
            blockedVersions=org_labelset.blocked_versions,
            environment=ocm_env,
            addonManagedUpgrades=False,
            sectors=org_labelset.sector_dependencies(),
            accessTokenClientId=None,
            accessTokenClientSecret=None,
            accessTokenUrl=None,
            addonUpgradeTests=None,
            inheritVersionData=None,
            upgradePolicyAllowedWorkloads=None,
            upgradePolicyClusters=None,
        )
    )

    # init policy for each cluster
    for c in clusters:
        try:
            upgrade_policy = _build_policy_from_labels(c.labels)
            org_upgrade_spec.specs.append(
                ClusterUpgradeSpec(
                    name=c.ocm_cluster.name,
                    cluster_uuid=c.ocm_cluster.external_id,
                    current_version=c.ocm_cluster.version.raw_id,
                    ocm=org_upgrade_spec.org,
                    upgradePolicy=upgrade_policy,
                )
            )
        except ValidationError as validation_error:
            for e in validation_error.errors():
                org_upgrade_spec.add_cluster_error(
                    c.ocm_cluster.external_id, f"label {e['loc'][0]}: {e['msg']}"
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


def _build_policy_from_labels(labels: LabelContainer) -> ClusterUpgradePolicy:
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


#
# Feedback mechanism
#


def _signal_validation_issues_for_org(
    ocm_api: OCMBaseClient,
    org_upgrade_spec: OrganizationUpgradeSpec,
) -> None:
    """
    Signal the validation errors of an organization to the users.
    Right now it uses OCM service logs, but it could be extended to use
    other mechanisms like slack etc.
    """
    org_id = org_upgrade_spec.org.org_id
    ocm_env_name = org_upgrade_spec.org.environment.name
    logging.warning(
        f"Errors found in {ocm_env_name} org {org_id}: "
        f"{org_upgrade_spec.cluster_errors}"
    )
    for cluster_error in org_upgrade_spec.cluster_errors:
        _expose_cluster_validation_errors_as_service_log(
            ocm_api=ocm_api,
            cluster_uuid=cluster_error.cluster_uuid,
            errors=cluster_error.messages,
        )


def _expose_cluster_validation_errors_as_service_log(
    ocm_api: OCMBaseClient, cluster_uuid: str, errors: list[str]
) -> None:
    """
    Highlight cluster upgrade policy validation errors to the cluster
    owners via OCM service logs.
    """
    description = "\n".join([f"- {e}" for e in errors])
    create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid=cluster_uuid,
            severity=OCMServiceLogSeverity.Warning,
            summary="Cluster upgrade policy validation errors",
            description=description,
            service_name=QONTRACT_INTEGRATION,
        ),
        dedup_interval=timedelta(days=1),
    )
