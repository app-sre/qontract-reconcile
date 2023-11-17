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
from pydantic.dataclasses import dataclass

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
    OpenShiftClusterManagerV1_OpenShiftClusterManagerV1,
    OpenShiftClusterManagerV1_OpenShiftClusterManagerV1_OpenShiftClusterManagerEnvironmentV1,
)
from reconcile.gql_definitions.fragments.minimal_ocm_organization import (
    MinimalOCMOrganization,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.upgrade_policy import (
    ClusterUpgradePolicyConditionsV1,
    ClusterUpgradePolicyV1,
)
from reconcile.utils.models import (
    CSV,
    cron_validator,
)
from reconcile.utils.ocm.base import (
    LabelContainer,
    OCMClusterServiceLogCreateModel,
    OCMOrganizationLabel,
    OCMServiceLogSeverity,
    build_label_container,
)
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import (
    get_org_labels,
    get_organization_labels,
    subscription_label_filter,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.service_log import create_service_log
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
    """
    A flavour of the OCM organization based upgrade scheduler, that uses
    OCM labels to discover clusters and their upgrade policies.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_upgrade_specs(self) -> dict[str, dict[str, OrganizationUpgradeSpec]]:
        inheritance_network = self.init_version_data_network()

        return {
            ocm_env.name: self._build_ocm_env_upgrade_specs(
                ocm_env=ocm_env,
                inheritance_network=inheritance_network,
            )
            for ocm_env in self.get_ocm_environments()
        }

    def init_version_data_network(self) -> dict["OrgRef", "VersionDataInheritance"]:
        # collect all version data labels from all OCM environments ...
        org_to_env: dict[str, OCMEnvironment] = {}
        labels_by_org: dict[str, list[OCMOrganizationLabel]] = defaultdict(list)
        for env in self.get_ocm_environments(filter=False):
            ocm_api = init_ocm_base_client(env, self.secret_reader)
            for label in get_organization_labels(
                ocm_api=ocm_api,
                filter=Filter().like("key", aus_label_key("version-data.%")),
            ):
                labels_by_org[label.organization_id].append(label)
                org_to_env[label.organization_id] = env

        # ... and build the inheritance network
        return build_version_data_inheritance_network(
            {
                OrgRef(
                    org_id=org_id, env_name=org_to_env[org_id].name
                ): build_label_container(labels)
                for org_id, labels in labels_by_org.items()
            }
        )

    def _build_ocm_env_upgrade_specs(
        self,
        ocm_env: OCMEnvironment,
        inheritance_network: dict["OrgRef", "VersionDataInheritance"],
    ) -> dict[str, OrganizationUpgradeSpec]:
        organizations = {
            org.org_id: org for org in self.get_orgs_for_environment(ocm_env)
        }
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters_by_org = discover_clusters(
            ocm_api=ocm_api,
            org_ids=set(organizations.keys()),
            ignore_sts_clusters=self.params.ignore_sts_clusters,
        )
        labels_by_org = _get_org_labels(
            ocm_api=ocm_api, org_ids=set(organizations.keys())
        )

        return _build_org_upgrade_specs_for_ocm_env(
            orgs=organizations,
            clusters_by_org=clusters_by_org,
            labels_by_org=labels_by_org,
            inheritance_network={
                org_ref.org_id: vdi for org_ref, vdi in inheritance_network.items()
            },
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
        passed_ocm_filters = not org_ids or c.organization_id in org_ids
        if passed_ocm_filters and passed_sts_filter:
            clusters_by_org[c.organization_id].append(c)

    return clusters_by_org


def _get_org_labels(
    ocm_api: OCMBaseClient, org_ids: Optional[set[str]]
) -> dict[str, LabelContainer]:
    """
    Fetch all AUS OCM org labels from organizations. They hold config
    parameters like blocked versions etc.

    The result is a dict with organization IDs as keys and label containers as values.
    """
    return get_org_labels(
        ocm_api=ocm_api,
        org_ids=org_ids or set(),
        label_filter=Filter().like("key", aus_label_key("%")),
    )


def _build_org_upgrade_specs_for_ocm_env(
    orgs: dict[str, AUSOCMOrganization],
    clusters_by_org: dict[str, list[ClusterDetails]],
    labels_by_org: dict[str, LabelContainer],
    inheritance_network: dict[str, "VersionDataInheritance"],
) -> dict[str, OrganizationUpgradeSpec]:
    """
    Builds the cluster upgrade specs for the given OCM environment.
    The specs are returned grouped by organization.
    """
    return {
        org_id: _build_org_upgrade_spec(
            orgs[org_id],
            clusters,
            labels_by_org.get(org_id) or build_label_container(),
            inheritance_network.get(org_id),
        )
        for org_id, clusters in clusters_by_org.items()
    }


def aus_label_key(config_atom: Optional[str] = None) -> str:
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
    org: AUSOCMOrganization,
    clusters: list[ClusterDetails],
    org_labels: LabelContainer,
    version_data_inheritance: Optional["VersionDataInheritance"],
) -> OrganizationUpgradeSpec:
    """
    Build a upgrade policy spec for each cluster in the organization that
    has a valid set of labels. Clusters without a set of labels are ignored. Clusters
    with an invalid/incomplete set of labels are reported as an error.
    """

    # build version inheritance config
    inherit_version_data = None
    if version_data_inheritance and version_data_inheritance.inherit_from_orgs:
        inherit_version_data = [
            OpenShiftClusterManagerV1_OpenShiftClusterManagerV1(
                name=source_org_ref.org_id,
                orgId=source_org_ref.org_id,
                environment=OpenShiftClusterManagerV1_OpenShiftClusterManagerV1_OpenShiftClusterManagerEnvironmentV1(
                    name=source_org_ref.env_name
                ),
                publishVersionData=[
                    MinimalOCMOrganization(orgId=org.org_id, name=org.name)
                ],
            )
            for source_org_ref in version_data_inheritance.inherit_from_orgs
        ]

    org_labelset = build_labelset(org_labels, OrganizationLabelSet)
    final_org = org.copy(deep=True)
    final_org.blocked_versions = org_labelset.blocked_versions
    final_org.sectors = org_labelset.sector_dependencies()
    final_org.inherit_version_data = inherit_version_data
    org_upgrade_spec = OrganizationUpgradeSpec(org=final_org)

    # init policy for each cluster
    for c in clusters:
        try:
            upgrade_policy = _build_policy_from_labels(c.labels)
            org_upgrade_spec.add_spec(
                ClusterUpgradeSpec(
                    org=org_upgrade_spec.org,
                    upgradePolicy=upgrade_policy,
                    cluster=c.ocm_cluster,
                )
            )
        except ValidationError as validation_error:
            for e in validation_error.errors():
                org_upgrade_spec.add_cluster_error(
                    c.ocm_cluster.external_id, f"label {e['loc'][0]}: {e['msg']}"
                )
        except Exception as ex:
            org_upgrade_spec.add_cluster_error(c.ocm_cluster.external_id, str(ex))

    # register organization errors
    if (
        version_data_inheritance
        and version_data_inheritance.unverified_inheritance_from_orgs
    ):
        unverified_org_ids = [
            org.org_id
            for org in version_data_inheritance.unverified_inheritance_from_orgs
        ]
        org_upgrade_spec.add_organization_error(
            f"Version data inheritance from organizations {', '.join(sorted(unverified_org_ids))} "
            f"are unverified. Ask the owner of these organizations to publish version data to the organization ID {org.org_id}. "
            "See https://source.redhat.com/groups/public/sre/wiki/advanced_upgrade_service_aus"
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
    blocked_versions: Optional[CSV] = Field(alias=aus_label_key("blocked-versions"))
    _schedule_validator = validator("schedule", allow_reuse=True)(cron_validator)

    def build_labels_dict(self) -> dict[str, str]:
        """
        Build a dictionary of all labels in this labelset.
        """
        labels = {}
        for k, v in self.dict(by_alias=True).items():
            if v is None:
                continue
            if isinstance(v, list):
                labels[k] = ",".join(sorted(v))
            else:
                labels[k] = str(v)
        return labels


def build_cluster_upgrade_policy_label_set(
    workloads: list[str],
    schedule: str,
    soak_days: int,
    mutexes: Optional[list[str]] = None,
    sector: Optional[str] = None,
    blocked_versions: Optional[list[str]] = None,
) -> ClusterUpgradePolicyLabelSet:
    return ClusterUpgradePolicyLabelSet(
        **{
            aus_label_key("workloads"): ",".join(workloads),
            aus_label_key("schedule"): schedule,
            aus_label_key("soak-days"): soak_days,
            aus_label_key("mutexes"): ",".join(mutexes) if mutexes else None,
            aus_label_key("sector"): sector,
            aus_label_key("blocked-versions"): ",".join(blocked_versions)
            if blocked_versions
            else None,
        }
    )


def _build_policy_from_labels(labels: LabelContainer) -> ClusterUpgradePolicyV1:
    """
    Build a cluster upgrade policy object from a set of OCM labels. Parsing
    and validation of the labels is delegated to the pydantic dataclass
    ClusterUpgradePolicyLabelSet.
    """
    policy_labelset = build_labelset(labels, ClusterUpgradePolicyLabelSet)
    return ClusterUpgradePolicyV1(
        workloads=policy_labelset.workloads,
        schedule=policy_labelset.schedule,
        conditions=ClusterUpgradePolicyConditionsV1(
            soakDays=policy_labelset.soak_days,
            mutexes=policy_labelset.mutexes,
            sector=policy_labelset.sector,
            blockedVersions=policy_labelset.blocked_versions,
        ),
    )


class VersionDataInheritanceLabelSet(BaseModel):
    inherit_version_data: Optional[CSV] = Field(
        alias=aus_label_key("version-data.inherit")
    )
    """
    A list of OCM organization IDs to inherit version data from. These organization also need
    to publish their version data via the `publish-version-data` label to the inheriting version.
    Version data publishing/inheritance can also be defined between OCM environments.
    """

    publish_version_data: Optional[CSV] = Field(
        alias=aus_label_key("version-data.publish")
    )
    """
    A list of OCM organization IDs to publish version data to. These organization also need
    to explicitely inherit version data via the `inherit-version-data` label from this organization.
    Version data publishing/inheritance can also be defined between OCM environments.
    """


@dataclass(frozen=True, eq=True)
class OrgRef:
    org_id: str
    env_name: str


class VersionDataInheritance(BaseModel):
    org_id: str
    inherit_from_orgs: set[OrgRef]
    unverified_inheritance_from_orgs: set[OrgRef]


def build_version_data_inheritance_network(
    labels_per_org: dict[OrgRef, LabelContainer]
) -> dict[OrgRef, VersionDataInheritance]:
    """
    Validates publish/inherit relationships between OCM organizations and environments from the
    provided label containers.

    This function returns a dictionary of OCM organizations and their version data
    inheritance relationships.
    """
    label_set_per_org = {
        org_ref: build_labelset(labels, VersionDataInheritanceLabelSet)
        for org_ref, labels in labels_per_org.items()
    }
    org_ref_lookup = {org_ref.org_id: org_ref for org_ref in labels_per_org}

    return {
        org_ref: _build_version_data_inheritance(
            org_ref,
            label_set,
            org_ref_lookup,
            label_set_per_org,
        )
        for org_ref, label_set in label_set_per_org.items()
        if label_set.inherit_version_data
    }


def _build_version_data_inheritance(
    org_ref: OrgRef,
    label_set: VersionDataInheritanceLabelSet,
    org_ref_lookup: dict[str, OrgRef],
    label_set_per_org: dict[OrgRef, VersionDataInheritanceLabelSet],
) -> VersionDataInheritance:
    inherit_from_orgs_org_ids = {
        source_org_id
        for source_org_id in label_set.inherit_version_data or []
        if source_org_id in org_ref_lookup
        and org_ref.org_id
        in (label_set_per_org[org_ref_lookup[source_org_id]].publish_version_data or [])
    }
    unverified_inheritance_from_orgs_org_ids = (
        set(label_set.inherit_version_data or []) - inherit_from_orgs_org_ids
    )

    return VersionDataInheritance(
        org_id=org_ref.org_id,
        inherit_from_orgs={
            org_ref_lookup[source_org_id] for source_org_id in inherit_from_orgs_org_ids
        },
        unverified_inheritance_from_orgs={
            org_ref_lookup.get(
                source_org_id, OrgRef(org_id=source_org_id, env_name="unknown")
            )
            for source_org_id in unverified_inheritance_from_orgs_org_ids
        },
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

    if org_upgrade_spec.cluster_errors:
        logging.warning(
            f"Cluster config errors found in {ocm_env_name} org {org_id}: "
            f"{org_upgrade_spec.cluster_errors}"
        )
        for cluster_error in org_upgrade_spec.cluster_errors:
            _expose_cluster_validation_errors_as_service_log(
                ocm_api=ocm_api,
                cluster_uuid=cluster_error.cluster_uuid,
                errors=cluster_error.messages,
            )

    if org_upgrade_spec.organization_errors:
        logging.warning(
            f"Organization config errors found in {ocm_env_name} org {org_id}: "
            f"{org_upgrade_spec.organization_errors}"
        )
        org_error_msg = "\n".join(
            o.message for o in org_upgrade_spec.organization_errors
        )
        for cluster in org_upgrade_spec.specs:
            create_service_log(
                ocm_api=ocm_api,
                service_log=OCMClusterServiceLogCreateModel(
                    cluster_uuid=cluster.cluster_uuid,
                    severity=OCMServiceLogSeverity.Warning,
                    summary="AUS configuration error on organization",
                    description=org_error_msg,
                    service_name=QONTRACT_INTEGRATION,
                ),
                dedup_interval=timedelta(days=1),
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
