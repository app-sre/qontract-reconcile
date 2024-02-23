import datetime as dt
import logging
import sys
from abc import (
    ABC,
    abstractmethod,
)
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    Callable,
    Optional,
    Protocol,
    Sequence,
    cast,
)

import semver
from croniter import croniter
from pydantic import BaseModel, Extra
from semver import VersionInfo

from reconcile.aus.cluster_version_data import (
    VersionData,
    VersionDataMap,
    WorkloadHistory,
    get_version_data,
)
from reconcile.aus.metrics import (
    UPGRADE_BLOCKED_METRIC_VALUE,
    UPGRADE_LONG_RUNNING_METRIC_VALUE,
    UPGRADE_SCHEDULED_METRIC_VALUE,
    UPGRADE_STARTED_METRIC_VALUE,
    AUSClusterUpgradePolicyInfoMetric,
    AUSOCMEnvironmentError,
    AUSOrganizationErrorRate,
    AUSOrganizationValidationErrorsGauge,
)
from reconcile.aus.models import (
    ClusterAddonUpgradeSpec,
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
    Sector,
)
from reconcile.aus.version_gates import HANDLERS
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicyV1
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.filtering import remove_none_values_from_dict
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    get_node_pools,
    get_version,
)
from reconcile.utils.ocm.upgrades import (
    OCMVersionGate,
    create_addon_upgrade_policy,
    create_control_plane_upgrade_policy,
    create_node_pool_upgrade_policy,
    create_upgrade_policy,
    delete_addon_upgrade_policy,
    delete_control_plane_upgrade_policy,
    delete_upgrade_policy,
    get_addon_upgrade_policies,
    get_control_plane_upgrade_policies,
    get_node_pool_upgrade_policies,
    get_upgrade_policies,
    get_version_agreement,
    get_version_gates,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import (
    get_version_prefix,
    parse_semver,
    sort_versions,
)
from reconcile.utils.state import init_state

MIN_DELTA_MINUTES = 6


class AdvancedUpgradeSchedulerBaseIntegrationParams(PydanticRunParams):
    ocm_environment: Optional[str] = None
    ocm_organization_ids: Optional[set[str]] = None
    excluded_ocm_organization_ids: Optional[set[str]] = None
    ignore_sts_clusters: bool = False


class ReconcileErrorSummary(Exception):
    def __init__(self, exceptions: list[str]) -> None:
        self.exceptions = exceptions

    def __str__(self) -> str:
        formatted_exceptions = "\n".join([f"- {e}" for e in self.exceptions])
        return f"Reconcile exceptions:\n{ formatted_exceptions }"


class AdvancedUpgradeSchedulerBaseIntegration(
    QontractReconcileIntegration[AdvancedUpgradeSchedulerBaseIntegrationParams]
):
    def run(self, dry_run: bool) -> None:
        with metrics.transactional_metrics(self.name):
            upgrade_specs = self.get_upgrade_specs()
            unhandled_exceptions = []
            for ocm_env, env_upgrade_specs in upgrade_specs.items():
                for org_upgrade_spec in env_upgrade_specs.values():
                    try:
                        with AUSOrganizationErrorRate(
                            integration=self.name,
                            ocm_env=ocm_env,
                            org_id=org_upgrade_spec.org.org_id,
                        ):
                            self.process_org(dry_run, ocm_env, org_upgrade_spec)
                    except Exception as e:
                        if not self.signal_reconcile_issues(
                            dry_run, org_upgrade_spec, e
                        ):
                            unhandled_exceptions.append(
                                f"{ocm_env}/{org_upgrade_spec.org.name}: {e}"
                            )

        if unhandled_exceptions:
            raise ReconcileErrorSummary(unhandled_exceptions)
        sys.exit(0)

    def get_orgs_for_environment(
        self, ocm_env: OCMEnvironment, only_addon_managed_upgrades: bool = False
    ) -> list[AUSOCMOrganization]:
        return get_orgs_for_environment(
            integration=self.name,
            ocm_env_name=ocm_env.name,
            query_func=gql.get_api().query,
            ocm_organization_ids=self.params.ocm_organization_ids,
            excluded_ocm_organization_ids=self.params.excluded_ocm_organization_ids,
            only_addon_managed_upgrades=only_addon_managed_upgrades,
        )

    def process_org(
        self, dry_run: bool, ocm_env: str, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        org_name = org_upgrade_spec.org.name
        self.expose_org_upgrade_spec_metrics(ocm_env, org_upgrade_spec)
        if org_upgrade_spec.has_validation_errors:
            self.signal_validation_issues(dry_run, org_upgrade_spec)
        elif org_upgrade_spec.specs:
            self.process_upgrade_policies_in_org(dry_run, org_upgrade_spec)
        else:
            logging.debug(
                f"Skip org {org_upgrade_spec.org.org_id}/{org_name} in {ocm_env} because it defines no upgrade policies"
            )

    def get_upgrade_specs(self) -> dict[str, dict[str, OrganizationUpgradeSpec]]:
        envs_org_upgrade_specs: dict[str, dict[str, OrganizationUpgradeSpec]] = {}
        for ocm_env in self.get_ocm_environments():
            try:
                envs_org_upgrade_specs[ocm_env.name] = self.get_ocm_env_upgrade_specs(
                    ocm_env=ocm_env
                )
            except Exception as e:
                logging.exception(
                    "Failed to get org upgrade specs for OCM environment %s. Skipping. %s",
                    ocm_env.name,
                    e,
                )
                metrics.inc_counter(
                    AUSOCMEnvironmentError(
                        integration=self.name,
                        ocm_env=ocm_env.name,
                    )
                )
        return envs_org_upgrade_specs

    def get_ocm_environments(self, filter: bool = True) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment and filter
            else None,
        ).environments

    def expose_remaining_soak_day_metrics(
        self,
        org_upgrade_spec: OrganizationUpgradeSpec,
        version_data: VersionData,
        current_state: Sequence["AbstractUpgradePolicy"],
        metrics_builder: "RemainingSoakDayMetricsBuilder",
    ) -> None:
        current_cluster_upgrade_policies = {
            p.cluster.external_id: p for p in current_state
        }
        for spec in org_upgrade_spec.specs:
            upgrades = spec.get_available_upgrades()
            if not upgrades:
                continue

            # calculate the amount every version has soaked. if a version has soaked for
            # multiple workloads, we will pick the minimum soak day value of all workloads
            # relevant on the cluster.
            soaked_versions: dict[str, float] = {}
            for workload in spec.upgrade_policy.workloads:
                for version, soak_days in soaking_days(
                    version_data, upgrades, workload, False
                ).items():
                    soaked_versions[version] = min(
                        soak_days, soaked_versions.get(version, soak_days)
                    )

            current_upgrade = current_cluster_upgrade_policies.get(spec.cluster_uuid)
            for version, metric_value in remaining_soak_day_metric_values_for_cluster(
                spec, soaked_versions, current_upgrade
            ).items():
                metrics.set_gauge(
                    metrics_builder(
                        cluster_uuid=spec.cluster.external_id, soaking_version=version
                    ),
                    metric_value,
                )

    @abstractmethod
    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None: ...

    @abstractmethod
    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment
    ) -> dict[str, OrganizationUpgradeSpec]: ...

    def signal_validation_issues(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None: ...

    def signal_reconcile_issues(
        self,
        dry_run: bool,
        org_upgrade_spec: OrganizationUpgradeSpec,
        exception: Exception,
    ) -> bool:
        """
        The bool return value is used to indicate if the exception was properly handled.

        The default behaviour returns False, indicating that the exception was not
        handled so that it can bubble up and potentially fail the integration.

        This function can be overridden to handle exceptions in a custom way.
        """
        return False

    def expose_org_upgrade_spec_metrics(
        self, ocm_env: str, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        metrics.set_gauge(
            AUSOrganizationValidationErrorsGauge(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_upgrade_spec.org.org_id,
            ),
            org_upgrade_spec.nr_of_validation_errors,
        )
        for cluster_upgrade_spec in org_upgrade_spec.specs:
            mutexes = cluster_upgrade_spec.upgrade_policy.conditions.mutexes
            metrics.set_info(
                AUSClusterUpgradePolicyInfoMetric(
                    integration=self.name,
                    ocm_env=ocm_env,
                    cluster_uuid=cluster_upgrade_spec.cluster_uuid,
                    org_id=cluster_upgrade_spec.org.org_id,
                    org_name=org_upgrade_spec.org.name,
                    channel=cluster_upgrade_spec.cluster.version.channel_group,
                    current_version=cluster_upgrade_spec.current_version,
                    cluster_name=cluster_upgrade_spec.name,
                    schedule=cluster_upgrade_spec.upgrade_policy.schedule,
                    sector=cluster_upgrade_spec.upgrade_policy.conditions.sector or "",
                    mutexes=",".join(mutexes) if mutexes else "",
                    soak_days=str(
                        cluster_upgrade_spec.upgrade_policy.conditions.soak_days or 0
                    ),
                    workloads=",".join(cluster_upgrade_spec.upgrade_policy.workloads),
                    product=cluster_upgrade_spec.cluster.product.id,
                    hypershift=cluster_upgrade_spec.cluster.hypershift.enabled,
                ),
            )


class RemainingSoakDayMetricsBuilder(Protocol):
    def __call__(
        self, cluster_uuid: str, soaking_version: str
    ) -> metrics.GaugeMetric: ...


class AbstractUpgradePolicy(ABC, BaseModel):
    """Abstract class for upgrade policies
    Used to create and delete upgrade policies in OCM."""

    cluster: OCMCluster

    id: Optional[str]
    next_run: Optional[str]
    schedule: Optional[str]
    schedule_type: str
    version: str
    state: Optional[str]

    @abstractmethod
    def create(self, ocm_api: OCMBaseClient) -> None:
        pass

    @abstractmethod
    def delete(self, ocm_api: OCMBaseClient) -> None:
        pass

    @abstractmethod
    def summarize(self) -> str:
        pass


class AddonUpgradePolicy(AbstractUpgradePolicy):
    """Class to create and delete Addon upgrade policies in OCM"""

    addon_id: str

    def create(self, ocm_api: OCMBaseClient) -> None:
        item = {
            "version": self.version,
            "schedule_type": "manual",
            "addon_id": self.addon_id,
            "cluster_id": self.cluster.id,
            "upgrade_type": "ADDON",
        }
        create_addon_upgrade_policy(ocm_api, self.cluster.id, item)

    def delete(self, ocm_api: OCMBaseClient) -> None:
        if not self.id:
            raise ValueError(
                "Cannot delete addon upgrade policy without id (not created yet)"
            )
        delete_addon_upgrade_policy(ocm_api, self.cluster.id, self.id)

    def summarize(self) -> str:
        details = {
            "cluster": self.cluster.name,
            "cluster_id": self.cluster.id,
            "version": self.version,
            "next_run": self.next_run,
            "addon_id": self.addon_id,
        }
        return f"addon upgrade policy - {remove_none_values_from_dict(details)}"


class ClusterUpgradePolicy(AbstractUpgradePolicy):
    """Class to create and delete ClusterUpgradePolicies in OCM"""

    def create(self, ocm_api: OCMBaseClient) -> None:
        policy = {
            "version": self.version,
            "schedule_type": "manual",
            "next_run": self.next_run,
        }
        create_upgrade_policy(ocm_api, self.cluster.id, policy)

    def delete(self, ocm_api: OCMBaseClient) -> None:
        if not self.id:
            raise ValueError(
                "Cannot delete cluster upgrade policy without id (not created yet)"
            )
        delete_upgrade_policy(ocm_api, self.cluster.id, self.id)

    def summarize(self) -> str:
        details = {
            "cluster": self.cluster.name,
            "cluster_id": self.cluster.id,
            "version": self.version,
            "next_run": self.next_run,
        }
        return f"cluster upgrade policy - {remove_none_values_from_dict(details)}"


class ControlPlaneUpgradePolicy(AbstractUpgradePolicy):
    """Class to create and delete ControlPlanUpgradePolicies in OCM"""

    def create(self, ocm_api: OCMBaseClient) -> None:
        policy = {
            "version": self.version,
            "schedule_type": "manual",
            "upgrade_type": "ControlPlane",
            "cluster_id": self.cluster.id,
            "next_run": self.next_run,
        }
        create_control_plane_upgrade_policy(ocm_api, self.cluster.id, policy)

    def delete(self, ocm_api: OCMBaseClient) -> None:
        if not self.id:
            raise ValueError(
                "Cannot delete controlplane upgrade policy without id (not created yet)"
            )
        delete_control_plane_upgrade_policy(ocm_api, self.cluster.id, self.id)

    def summarize(self) -> str:
        details = {
            "cluster": self.cluster.name,
            "cluster_id": self.cluster.id,
            "version": self.version,
            "next_run": self.next_run,
        }
        return f"cluster upgrade policy - {remove_none_values_from_dict(details)}"


class NodePoolUpgradePolicy(AbstractUpgradePolicy):
    node_pool: str
    """Class to create and delete NodePoolUpgradePolicies in OCM"""

    def create(self, ocm_api: OCMBaseClient) -> None:
        policy = {
            "version": self.version,
            "schedule_type": "manual",
            "upgrade_type": "NodePool",
            "cluster_id": self.cluster.id,
            "next_run": self.next_run,
        }
        create_node_pool_upgrade_policy(
            ocm_api, self.cluster.id, self.node_pool, policy
        )

    def delete(self, ocm_api: OCMBaseClient) -> None:
        raise NotImplementedError("NodePoolUpgradePolicy.delete() not implemented")

    def summarize(self) -> str:
        details = {
            "cluster": self.cluster.name,
            "cluster_id": self.cluster.id,
            "node_pool": self.node_pool,
            "version": self.version,
            "next_run": self.next_run,
        }
        return f"node pool upgrade policy - {remove_none_values_from_dict(details)}"


class UpgradePolicyHandler(BaseModel, extra=Extra.forbid):
    """Class to handle upgrade policy actions"""

    action: str
    policy: AbstractUpgradePolicy

    def act(self, dry_run: bool, ocm_api: OCMBaseClient) -> None:
        logging.info(f"{self.action} {self.policy.summarize()}")
        if dry_run:
            return

        if not self.action:
            pass
        elif self.action == "delete":
            self.policy.delete(ocm_api)
        elif self.action == "create":
            self.policy.create(ocm_api)


def fetch_current_state(
    ocm_api: OCMBaseClient,
    org_upgrade_spec: OrganizationUpgradeSpec,
    addons: bool = False,
) -> list[AbstractUpgradePolicy]:
    current_state: list[AbstractUpgradePolicy] = []
    for spec in org_upgrade_spec.specs:
        if addons and isinstance(spec, ClusterAddonUpgradeSpec):
            addon_spec = cast(ClusterAddonUpgradeSpec, spec)
            upgrade_policies = get_addon_upgrade_policies(
                ocm_api, spec.cluster.id, addon_id=addon_spec.addon.addon.id
            )
            for upgrade_policy in upgrade_policies:
                upgrade_policy["cluster"] = spec.cluster
                current_state.append(AddonUpgradePolicy(**upgrade_policy))
        elif spec.cluster.is_rosa_hypershift():
            upgrade_policies = get_control_plane_upgrade_policies(
                ocm_api, spec.cluster.id
            )
            for upgrade_policy in upgrade_policies:
                upgrade_policy["cluster"] = spec.cluster
                current_state.append(ControlPlaneUpgradePolicy(**upgrade_policy))
            for node_pool in get_node_pools(ocm_api, spec.cluster.id):
                node_upgrade_policies = get_node_pool_upgrade_policies(
                    ocm_api, spec.cluster.id, node_pool["id"]
                )
                for upgrade_policy in node_upgrade_policies:
                    upgrade_policy["cluster"] = spec.cluster
                    upgrade_policy["node_pool"] = node_pool["id"]
                    current_state.append(NodePoolUpgradePolicy(**upgrade_policy))
        else:
            upgrade_policies = get_upgrade_policies(ocm_api, spec.cluster.id)
            for upgrade_policy in upgrade_policies:
                upgrade_policy["cluster"] = spec.cluster
                current_state.append(ClusterUpgradePolicy(**upgrade_policy))

    return current_state


# consider first lower versions and lower soakdays (when versions are equal)
def sort_key(spec: ClusterUpgradeSpec) -> tuple:
    return (
        parse_semver(spec.cluster.version.raw_id),
        spec.upgrade_policy.conditions.soak_days or 0,
    )


def update_history(
    version_data: VersionData, org_upgrade_spec: OrganizationUpgradeSpec
) -> None:
    """Update history with information from clusters with upgrade policies.

    Args:
        version_data (VersionData): version data, including history of soakdays
        upgrade_policies (list): query results of clusters upgrade policies
    """
    now = datetime.utcnow()
    check_in = version_data.check_in or now

    # we iterate over clusters upgrade policies and update the version history
    for spec in org_upgrade_spec.specs:
        current_version = spec.current_version
        cluster = spec.cluster.name
        workloads = spec.upgrade_policy.workloads
        # we keep the version history per workload
        for w in workloads:
            workload_history = version_data.workload_history(
                current_version, w, WorkloadHistory()
            )

            # if the cluster is already reporting - accumulate it.
            # if not - add it to the reporting list (first report)
            if cluster in workload_history.reporting:
                workload_history.soak_days += (
                    now - check_in
                ).total_seconds() / 86400  # seconds in day
            else:
                workload_history.reporting.append(cluster)

    version_data.update_stats(org_upgrade_spec)

    version_data.check_in = now


def version_data_state_key(ocm_env: str, org_id: str, addon_id: Optional[str]) -> str:
    return f"{ocm_env}/{org_id}/{addon_id}" if addon_id else f"{ocm_env}/{org_id}"


@defer
def get_version_data_map(
    dry_run: bool,
    org_upgrade_spec: OrganizationUpgradeSpec,
    integration: str,
    addon_id: str = "",
    inherit_version_data: bool = True,
    defer: Optional[Callable] = None,
) -> VersionDataMap:
    """Get a summary of versions history per OCM instance

    Args:
        dry_run (bool): save updated history to remote state
        org_upgrade_spec (OrganizationUpgradeSpec): organization upgrade spec
        addon_id (str): optional addon id to get & store the addon specific state,
          additionally to the ocm org name
        inherit_version_data: whether to inherit version data from other OCM orgs
        defer (Optional<Callable>): defer function

    Returns:
        dict: version data per OCM organization keyed by the organization ID
    """
    state = init_state(integration=integration)
    if defer:
        defer(state.cleanup)
    result = VersionDataMap()

    # we keep a remote state per OCM org
    state_key = version_data_state_key(
        org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id, addon_id
    )
    version_data = get_version_data(state, state_key)
    update_history(version_data, org_upgrade_spec)
    result.add(
        org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id, version_data
    )
    if not dry_run:
        version_data.save(state, state_key)

    # aggregate data from other ocm orgs
    # this is done *after* saving the state: we do not store the other orgs data in our state.
    if inherit_version_data:
        for other_ocm in org_upgrade_spec.org.inherit_version_data or []:
            if org_upgrade_spec.org.org_id == other_ocm.org_id:
                raise ValueError(
                    f"[{org_upgrade_spec.org.name} - {org_upgrade_spec.org.org_id}] OCM organization inherits version data from itself"
                )
            if org_upgrade_spec.org.org_id not in [
                o.org_id for o in other_ocm.publish_version_data or []
            ]:
                raise ValueError(
                    f"[{org_upgrade_spec.org.name} - {org_upgrade_spec.org.org_id}] OCM organization inherits version data from "
                    f"{other_ocm.org_id}, but this data is not published to it: "
                    f"missing publishVersionData in {other_ocm.org_id}"
                )
            other_ocm_data = get_version_data(
                state,
                version_data_state_key(
                    other_ocm.environment.name, other_ocm.org_id, addon_id
                ),
            )
            result.get(
                org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
            ).aggregate(
                other_ocm_data, f"{other_ocm.environment.name}/{other_ocm.org_id}"
            )

    return result


def workload_sector_versions(sector: Sector, workload: str) -> list[VersionInfo]:
    """
    get all versions of clusters running the specified workload in that sector
    """
    versions = []
    for spec in sector.specs:
        # clusters within a sector always have workloads (mandatory in schema)
        workloads = spec.upgrade_policy.workloads
        if workload in workloads:
            versions.append(parse_semver(spec.cluster.version.raw_id))
    return versions


def workload_sector_dependencies(sector: Sector, workload: str) -> set[Sector]:
    """
    get the list of first dependency sectors with non-empty versions for that workload in the
    sector dependency tree. This goes down recursively through the dependency tree.
    """
    deps = set()
    for dep in sector.dependencies:
        if workload_sector_versions(dep, workload):
            deps.add(dep)
        else:
            deps.update(workload_sector_dependencies(dep, workload))
    return deps


def version_conditions_met(
    version: str,
    version_data: VersionData,
    upgrade_policy: ClusterUpgradePolicyV1,
    sector: Optional[Sector],
) -> bool:
    """Check that upgrade conditions are met for a version

    Args:
        version (string): version to check
        version_data (VersionData): history of versions of an OCM organization
        workloads (list): strings representing types of workloads
        upgrade_policy (ClusterUpgradePolicy): the upgrade policy to validate


    Returns:
        bool: are version upgrade conditions met
    """
    if sector:
        # check that inherited orgs run at least that version for our workloads
        if not version_data.validate_against_inherited(
            version, upgrade_policy.workloads
        ):
            return False

        # check if previous sectors run at least this version for that workload
        # we will check dependencies recursively until there are versions for the given workload
        # or no more dependencies to check
        for w in upgrade_policy.workloads:
            for dep in workload_sector_dependencies(sector, w):
                dep_versions = workload_sector_versions(dep, w)
                if not dep_versions:
                    continue
                if min(dep_versions) < parse_semver(version):
                    return False

    # check soak days condition is met for this version
    soak_days = upgrade_policy.conditions.soak_days
    if soak_days is not None:
        for w in upgrade_policy.workloads:
            workload_history = version_data.workload_history(version, w)
            if soak_days > workload_history.soak_days:
                return False

    return True


def gates_for_minor_version(
    gates: list[OCMVersionGate],
    target_version_prefix: str,
) -> list[OCMVersionGate]:
    return [g for g in gates if g.version_raw_id_prefix == target_version_prefix]


def is_gate_applicable_to_cluster(gate: OCMVersionGate, cluster: OCMCluster) -> bool:
    # check that the cluster has an upgrade path that crosses the gate version
    minor_version_upgrade_paths = {
        get_version_prefix(version) for version in cluster.available_upgrades()
    }
    if gate.version_raw_id_prefix not in minor_version_upgrade_paths:
        return False

    # consider only gates after the clusters current minor version
    # OCM onls supports creating gate agreements for later minor versions than the
    # current cluster version
    if not semver.match(
        f"{cluster.minor_version()}.0", f"<{gate.version_raw_id_prefix}.0"
    ):
        return False

    # check the handler for the gate type if it is responsible for this kind
    # of cluster
    handler = HANDLERS.get(gate.label)
    if handler:
        return handler.gate_applicable_to_cluster(cluster)
    return False


def gates_to_agree(
    gates: list[OCMVersionGate],
    cluster: OCMCluster,
    acked_gate_ids: set[str],
) -> list[OCMVersionGate]:
    """Check via OCM if a version is agreed

    Args:
        gates (OCMVersionGate): list of OCMVersionGate objects to check for agreements
        cluster_id (str): the cluster that needs gate agreements
        ocm_api (OCMBaseClient): used to fetch infos from OCM

    Returns:
        list[OCMVersionGate]: list of gates a cluster has not agreed on yet
    """
    applicable_gates = [g for g in gates if is_gate_applicable_to_cluster(g, cluster)]

    if applicable_gates:
        return [gate for gate in applicable_gates if gate.id not in acked_gate_ids]
    return []


def upgradeable_version(
    spec: ClusterUpgradeSpec,
    version_data: VersionData,
    sector: Optional[Sector],
) -> Optional[str]:
    """Get the highest next version we can upgrade to, fulfilling all conditions"""
    for version in reversed(sort_versions(spec.get_available_upgrades())):
        if spec.version_blocked(version):
            continue
        if version_conditions_met(
            version,
            version_data,
            spec.upgrade_policy,
            sector,
        ):
            return version
    return None


def verify_current_should_skip(
    current_state: Sequence[AbstractUpgradePolicy],
    desired: ClusterUpgradeSpec,
    now: datetime,
    addon_id: str = "",
) -> tuple[bool, Optional[UpgradePolicyHandler]]:
    current_policies = [c for c in current_state if c.cluster.id == desired.cluster.id]
    if not current_policies:
        return False, None

    # there can only be one upgrade policy per cluster
    if len(current_policies) != 1:
        raise ValueError(
            f"[{desired.org.org_id}/{desired.cluster.name}] expected only one upgrade policy"
        )
    current = current_policies[0]
    version = current.version  # may not exist in automatic upgrades
    if version and not addon_id and desired.version_blocked(version):
        next_run = current.next_run
        if next_run and datetime.strptime(next_run, "%Y-%m-%dT%H:%M:%SZ") < now:
            logging.warning(
                f"[{desired.org.org_id}/{desired.org.name}/{desired.cluster.name}] currently upgrading to blocked version '{version}'"
            )
            return True, None
        logging.debug(
            f"[{desired.org.org_id}/{desired.org.name}/{desired.cluster.name}] found planned upgrade policy "
            + f"with blocked version {version}"
        )
        return False, UpgradePolicyHandler(action="delete", policy=current)

    # else
    logging.debug(
        f"[{desired.org.org_id}/{desired.org.name}/{desired.cluster.name}] skipping cluster with existing upgrade policy"
    )
    return True, None


def verify_schedule_should_skip(
    desired: ClusterUpgradeSpec,
    now: datetime,
    addon_id: str = "",
) -> Optional[str]:
    schedule = desired.upgrade_policy.schedule
    iter = croniter(schedule)
    # ClusterService refuses scheduling upgrades less than 5m in advance
    # Let's find the next schedule that is at least 5m ahead.
    # We do not need that much delay for addon upgrades since they run
    # immediately
    delay_minutes = 1 if addon_id else MIN_DELTA_MINUTES
    next_schedule = iter.get_next(
        dt.datetime, start_time=now + timedelta(minutes=delay_minutes)
    )
    next_schedule_in_seconds = (next_schedule - now).total_seconds()
    next_schedule_in_hours = next_schedule_in_seconds / 3600  # seconds in hour

    # ignore clusters with an upgrade schedule not within the next 2 hours
    within_upgrade_timeframe = next_schedule_in_hours <= 2
    if addon_id:
        # addons upgrade cannot be scheduled in advance as the "next_run" field
        # is not supported. So we run this only 10min before schedule to be somewhat
        # correct
        within_upgrade_timeframe = next_schedule_in_seconds / 60 <= 10
    if not within_upgrade_timeframe:
        logging.debug(
            f"[{desired.org.org_id}/{desired.org.name}/{desired.cluster.name}] skipping cluster with no upcoming upgrade"
        )
        return None
    return next_schedule.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_lock_should_skip(
    desired: ClusterUpgradeSpec, locked: dict[str, str]
) -> bool:
    mutexes = desired.effective_mutexes
    if any(lock in locked for lock in mutexes):
        locking = {lock: locked[lock] for lock in mutexes if lock in locked}
        logging.debug(
            f"[{desired.org.org_id}/{desired.org.name}/{desired.cluster.name}] skipping cluster: locked out by {locking}"
        )
        return True
    return False


def _create_upgrade_policy(
    next_schedule: str, spec: ClusterUpgradeSpec, version: str
) -> AbstractUpgradePolicy:
    if spec.cluster.is_rosa_hypershift():
        return ControlPlaneUpgradePolicy(
            cluster=spec.cluster,
            version=version,
            schedule_type="manual",
            next_run=next_schedule,
        )
    return ClusterUpgradePolicy(
        cluster=spec.cluster,
        version=version,
        schedule_type="manual",
        next_run=next_schedule,
    )


def _calculate_node_pool_diffs(
    ocm_api: OCMBaseClient, spec: ClusterUpgradeSpec, now: datetime
) -> Optional[UpgradePolicyHandler]:
    node_pools = get_node_pools(ocm_api, spec.cluster.id)
    if node_pools:
        for pool in node_pools:
            pool_version_id = pool.get("version", {}).get("id")
            pool_version = get_version(ocm_api, pool_version_id)["raw_id"]
            if semver.match(pool_version, f"<{spec.current_version}"):
                next_schedule = (now + timedelta(minutes=MIN_DELTA_MINUTES)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                return UpgradePolicyHandler(
                    action="create",
                    policy=NodePoolUpgradePolicy(
                        cluster=spec.cluster,
                        version=spec.current_version,
                        schedule_type="manual",
                        next_run=next_schedule,
                        node_pool=pool["id"],
                    ),
                )
    return None


def calculate_diff(
    current_state: Sequence[AbstractUpgradePolicy],
    desired_state: OrganizationUpgradeSpec,
    ocm_api: OCMBaseClient,
    version_data: VersionData,
    addon_id: str = "",
) -> list[UpgradePolicyHandler]:
    """Check available upgrades for each cluster in the desired state
    according to upgrade conditions

    Args:
        current_state (list): currently existing upgrade policies
        desired_state (OrganizationUpgradeSpec): organization upgrade spec
        ocm_api (OCMBaseClient): OCM API client
        version_data (VersionData): version data history of the org
        addon_id (str): optional addonid to calculate diffs for

    Returns:
        list: upgrade policies to be applied
    """

    def set_mutex(
        locked: dict[str, str], cluster_id: str, mutexes: Optional[set[str]] = None
    ) -> None:
        for mutex in mutexes or set():
            locked[mutex] = cluster_id

    diffs: list[UpgradePolicyHandler] = []

    # all clusters IDs with a current upgradePolicy are considered locked
    locked: dict[str, str] = {}
    for spec in desired_state.specs:
        if spec.cluster.id in [s.cluster.id for s in current_state]:
            for mutex in spec.effective_mutexes:
                locked[mutex] = spec.cluster.id

    now = datetime.utcnow()
    gates = get_version_gates(ocm_api)
    for spec in desired_state.specs:
        # Upgrading node pools, only required for Hypershift clusters
        # do this in the same loop, to skip cluster on node pool upgrade
        if spec.cluster.is_rosa_hypershift():
            if verify_lock_should_skip(spec, locked):
                continue

            node_pool_update = _calculate_node_pool_diffs(ocm_api, spec, now)
            if node_pool_update:  # node pool update policy not yet created
                diffs.append(node_pool_update)
                set_mutex(locked, spec.cluster.id, spec.effective_mutexes)
                continue

        # ignore clusters with an existing upgrade policy
        skip, delete_policy = verify_current_should_skip(
            current_state, spec, now, addon_id
        )
        if skip:
            continue
        if delete_policy:
            diffs.append(delete_policy)

        next_schedule = verify_schedule_should_skip(spec, now, addon_id)
        if not next_schedule:
            continue

        if verify_lock_should_skip(spec, locked):
            continue

        sector_name = spec.upgrade_policy.conditions.sector
        sector = None
        if sector_name:
            sector = desired_state.sectors[sector_name]
        version = upgradeable_version(spec, version_data, sector)
        if version:
            if addon_id:
                diffs.append(
                    UpgradePolicyHandler(
                        action="create",
                        policy=AddonUpgradePolicy(
                            action="create",
                            cluster=spec.cluster,
                            version=version,
                            schedule_type="manual",
                            addon_id=addon_id,
                            upgrade_type="ADDON",
                        ),
                    )
                )
            else:
                target_version_prefix = get_version_prefix(version)
                minor_version_gates = gates_for_minor_version(
                    gates=gates,
                    target_version_prefix=target_version_prefix,
                )
                # skipping upgrades when there are no version gates is a safety
                # precaution to prevent cluster upgrades being scheduled.
                # missing version gates are an indicator that the version has not yet gone
                # through SREP gap analysis and is not yet ready for upgrades.
                #
                # this might change in the future - revisite for 4.16
                if not minor_version_gates:
                    logging.debug(
                        f"[{spec.org.org_id}/{spec.org.name}/{spec.cluster.name}] no gates found for {target_version_prefix}. "
                        "Skip creation of an upgrade policy."
                    )
                    continue
                gates = gates_to_agree(
                    gates=minor_version_gates,
                    cluster=spec.cluster,
                    acked_gate_ids={
                        agreement["version_gate"]["id"]
                        for agreement in get_version_agreement(ocm_api, spec.cluster.id)
                    },
                )
                if gates:
                    gate_ids = [gate.id for gate in gates]
                    logging.debug(
                        f"[{spec.org.org_id}/{spec.org.name}/{spec.cluster.name}] found gates for {target_version_prefix} - {gate_ids} "
                        "Skip creation of an upgrade policy until all of them have been acked by the version-gate-approver integration or a user."
                    )
                diffs.append(
                    UpgradePolicyHandler(
                        action="create",
                        policy=_create_upgrade_policy(next_schedule, spec, version),
                    )
                )
            set_mutex(locked, spec.cluster.id, spec.effective_mutexes)

    return diffs


def sort_diffs(diff: UpgradePolicyHandler) -> int:
    if diff.action == "delete":
        return 1
    return 2


def act(
    dry_run: bool,
    diffs: list[UpgradePolicyHandler],
    ocm_api: OCMBaseClient,
    addon_id: Optional[str] = None,
) -> None:
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        policy = diff.policy
        if (
            addon_id
            and isinstance(policy, AddonUpgradePolicy)
            and addon_id != policy.addon_id
        ):
            continue
        diff.act(dry_run, ocm_api)


def soaking_days(
    version_data: VersionData,
    upgrades: list[str],
    workload: str,
    only_soaking: bool,
) -> dict[str, float]:
    soaking = {}
    for version in upgrades:
        workload_history = version_data.workload_history(version, workload)
        soaking[version] = round(workload_history.soak_days, 2)
        if not only_soaking and version not in soaking:
            soaking[version] = 0
    return soaking


def get_orgs_for_environment(
    integration: str,
    ocm_env_name: str,
    query_func: Callable,
    ocm_organization_ids: Optional[set[str]] = None,
    excluded_ocm_organization_ids: Optional[set[str]] = None,
    only_addon_managed_upgrades: bool = False,
) -> list[AUSOCMOrganization]:
    """
    Returns a list of organizations for the given OCM environment, applying
    filters based on the provided arguments.

    Args:
        ocm_env_name (str): OCM environment name to filter
        ocm_organization_ids (Optional[set[str]]): if any organization IDs are provided, any other organizations are excluded from the results
        excluded_ocm_organization_ids (Optional[set[str]]): if any organization IDs are provided, these organizations are excluded from the results
        only_addon_managed_upgrades (bool): if True, organizations without enabled addon management are excluded from the results
        query_func (Callable): function to query organizations via GQL

    Returns:
        list[AUSOCMOrganization]: list of organizations matching the given filters
    """
    orgs = aus_organizations_query(query_func=query_func).organizations or []
    return [
        org
        for org in orgs or []
        if org.environment.name == ocm_env_name
        and integration_is_enabled(integration, org)
        and (not only_addon_managed_upgrades or org.addon_managed_upgrades)
        and (not ocm_organization_ids or org.org_id in ocm_organization_ids)
        and (
            not excluded_ocm_organization_ids
            or org.org_id not in excluded_ocm_organization_ids
        )
    ]


def remaining_soak_day_metric_values_for_cluster(
    spec: ClusterUpgradeSpec,
    soaked_versions: dict[str, float],
    current_upgrade: Optional[AbstractUpgradePolicy],
) -> dict[str, float]:
    """
    Calculate what versions and metric values to report for `AUS*VersionRemainingSoakDaysGauge` metrics.
    Usually, the remaining soak days for a version are reported but there are some special cases
    where we report negative values to indicate that a version is blocked or an upgrade has been
    scheduled or started.

    Additionally certain versions are not reported when it is not meaningful (e.g. an upgrade will never happen)
    to prevent metric clutter.
    """
    upgrades = spec.get_available_upgrades()
    if not upgrades:
        return {}

    # calculate the remaining soakdays for each upgrade version candidate of the cluster.
    # when a version is soaking, it has a value > 0 and when it soaked enough, the value is 0.
    remaining_soakdays: list[float] = [
        max(
            (spec.upgrade_policy.conditions.soak_days or 0) - soaked_versions.get(v, 0),
            0,
        )
        for v in upgrades
    ]

    # under certain conditions, the remaining soak day value for a version needs to be
    # replaced with special marker values
    version_metrics: dict[str, float] = {}
    for idx, version in reversed(list(enumerate(upgrades))):
        # if an upgrade is `scheduled` or `started`` for the specific version, their respective negative
        # marker values will be used instead of their actual soak days. there are other states than `scheduled`
        # and `started` but the `UpgradePolicy` vanishes too quickly to observe them reliably, when such
        # states are reached.
        if current_upgrade and current_upgrade.version == version:
            if current_upgrade.state == "scheduled":
                remaining_soakdays[idx] = UPGRADE_SCHEDULED_METRIC_VALUE
            elif current_upgrade.state in {"started", "delayed"}:
                remaining_soakdays[idx] = UPGRADE_STARTED_METRIC_VALUE
                if current_upgrade.next_run:
                    # if an upgrade runs for over 6 hours, we mark it as a long running upgrade
                    next_run = datetime.strptime(
                        current_upgrade.next_run, "%Y-%m-%dT%H:%M:%SZ"
                    )
                    now = datetime.utcnow()
                    hours_ago = (now - next_run).total_seconds() / 3600
                    if hours_ago >= 6:
                        remaining_soakdays[idx] = UPGRADE_LONG_RUNNING_METRIC_VALUE
        elif spec.version_blocked(version):
            # if a version is blocked, we will still report it but with a dedicated negative marker value
            remaining_soakdays[idx] = UPGRADE_BLOCKED_METRIC_VALUE

        # we are intentionally not reporting versions that still soak or soaked enough when
        # there is a later version that also soaked enough. the later one will be picked
        # for an upgrade over the older one anyways.
        if remaining_soakdays[idx] >= 0 and any(
            later_version_remaining_soak_days
            in {
                0,
                UPGRADE_SCHEDULED_METRIC_VALUE,
                UPGRADE_STARTED_METRIC_VALUE,
                UPGRADE_LONG_RUNNING_METRIC_VALUE,
            }
            for later_version_remaining_soak_days in remaining_soakdays[idx + 1 :]
        ):
            continue
        version_metrics[version] = remaining_soakdays[idx]

    return version_metrics
