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
    cast,
)

import semver
from croniter import croniter
from pydantic import BaseModel
from semver import VersionInfo

from reconcile.aus.cluster_version_data import (
    VersionData,
    VersionDataMap,
    WorkloadHistory,
    get_version_data,
)
from reconcile.aus.metrics import (
    AUSClusterUpgradePolicyInfoMetric,
    AUSOrganizationErrorRate,
    AUSOrganizationValidationErrorsGauge,
)
from reconcile.aus.models import (
    ClusterAddonUpgradeSpec,
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
    Sector,
)
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicyV1
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.defer import defer
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
    create_version_agreement,
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
    parse_semver,
    sort_versions,
)
from reconcile.utils.state import init_state

MIN_DELTA_MINUTES = 6


class AdvancedUpgradeSchedulerBaseIntegrationParams(PydanticRunParams):
    ocm_environment: Optional[str] = None
    ocm_organization_ids: Optional[set[str]] = None
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
                f"Skip org {org_name} in {ocm_env} because it defines no upgrade policies"
            )

    def get_upgrade_specs(self) -> dict[str, dict[str, OrganizationUpgradeSpec]]:
        return {
            ocm_env.name: self.get_ocm_env_upgrade_specs(
                ocm_env,
                self.params.ocm_organization_ids,
            )
            for ocm_env in self.get_ocm_environments()
        }

    def get_ocm_environments(self, filter: bool = True) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment and filter
            else None,
        ).environments

    @abstractmethod
    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ...

    @abstractmethod
    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        ...

    def signal_validation_issues(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ...

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
                ),
            )


class GateAgreement(BaseModel):
    gate: OCMVersionGate

    def create(self, ocm_api: OCMBaseClient, cluster: OCMCluster) -> None:
        logging.info(
            f"create agreement for gate {self.gate.id} on cluster {cluster.name} (id={cluster.id})"
        )
        agreement = create_version_agreement(ocm_api, self.gate.id, cluster.id)
        if agreement.get("version_gate") is None:
            logging.error(
                "Unexpected response while creating version "
                f"agreement with id {self.gate.id} for cluster {cluster.name} (id={cluster.id})"
            )


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


class UpgradePolicyHandler(BaseModel):
    """Class to handle upgrade policy actions"""

    action: str
    policy: AbstractUpgradePolicy

    gates_to_agree: Optional[list[GateAgreement]]

    def _create_gate_agreements(self, ocm_api: OCMBaseClient) -> None:
        for gate in self.gates_to_agree or []:
            gate.create(ocm_api, self.policy.cluster)

    def act(self, dry_run: bool, ocm_api: OCMBaseClient) -> None:
        logging.info(f"{self.action} {self.policy.summarize()}")
        if dry_run:
            return

        if not self.action:
            pass
        elif self.action == "delete":
            self.policy.delete(ocm_api)
        elif self.action == "create":
            self._create_gate_agreements(ocm_api)
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
    defer: Optional[Callable] = None,
) -> VersionDataMap:
    """Get a summary of versions history per OCM instance

    Args:
        dry_run (bool): save updated history to remote state
        org_upgrade_spec (OrganizationUpgradeSpec): organization upgrade spec
        addon_id (str): optional addon id to get & store the addon specific state,
          additionally to the ocm org name
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
        ).aggregate(other_ocm_data, f"{other_ocm.environment.name}/{other_ocm.org_id}")

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


def gates_to_agree(
    gates: list[OCMVersionGate],
    version_prefix: str,
    cluster: OCMCluster,
    ocm_api: OCMBaseClient,
) -> list[OCMVersionGate]:
    """Check via OCM if a version is agreed

    Args:
        gates: list of OCMVersionGate objects
        version_prefix (string): major.minor version prefix
        cluster (string)
        cluster_version (string): current version of the cluster
        sts (bool): is the cluster a STS cluster
        ocm_api (OCMBaseClient): used to fetch infos from OCM

    Returns:
        list[OCMVersionGate]: list of gates to agree
    """
    semver_cluster = parse_semver(f"{cluster.version.raw_id}")

    applicable_gates = [
        g
        for g in gates
        if g.version_raw_id_prefix == version_prefix
        # todo: sts version gates need special handling - https://issues.redhat.com/browse/APPSRE-7949
        #       until this is solved, we can't do automated upgrades for STS clusters that cross a version gate
        #       once we have proper and secure handling get gate agreements for STS clusters, we can use this condition:
        #       `and (not g.sts_only or g.sts_only == cluster.is_sts())`
        and not g.sts_only and semver_cluster.match(f"<{g.version_raw_id_prefix}.0")
    ]

    if applicable_gates:
        current_agreements = {
            agreement["version_gate"]["id"]
            for agreement in get_version_agreement(ocm_api, cluster.id)
        }
        return [gate for gate in applicable_gates if gate.id not in current_agreements]
    return []


def get_version_prefix(version: str) -> str:
    semver = parse_semver(version)
    return f"{semver.major}.{semver.minor}"


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
    current_state: list[AbstractUpgradePolicy],
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
                f"[{desired.org.org_id}/{desired.cluster.name}] currently upgrading to blocked version '{version}'"
            )
            return True, None
        logging.debug(
            f"[{desired.org.org_id}/{desired.cluster.name}] found planned upgrade policy "
            + f"with blocked version {version}"
        )
        return False, UpgradePolicyHandler(action="delete", policy=current)

    # else
    logging.debug(
        f"[{desired.org.org_id}/{desired.cluster.name}] skipping cluster with existing upgrade policy"
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
            f"[{desired.org.org_id}/{desired.cluster.name}] skipping cluster with no upcoming upgrade"
        )
        return None
    return next_schedule.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_lock_should_skip(
    desired: ClusterUpgradeSpec, locked: dict[str, str]
) -> bool:
    mutexes = desired.upgrade_policy.conditions.mutexes or []
    if any(lock in locked for lock in mutexes):
        locking = {lock: locked[lock] for lock in mutexes if lock in locked}
        logging.debug(
            f"[{desired.org.org_id}/{desired.cluster.name}] skipping cluster: locked out by {locking}"
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
    current_state: list[AbstractUpgradePolicy],
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
        locked: dict[str, str], cluster_id: str, mutexes: Optional[list[str]] = None
    ) -> None:
        for mutex in mutexes or []:
            locked[mutex] = cluster_id

    diffs: list[UpgradePolicyHandler] = []

    # all clusters IDs with a current upgradePolicy are considered locked
    locked: dict[str, str] = {}
    for spec in desired_state.specs:
        if spec.cluster.id in [s.cluster.id for s in current_state]:
            for mutex in spec.upgrade_policy.conditions.mutexes or []:
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
                set_mutex(
                    locked, spec.cluster.id, spec.upgrade_policy.conditions.mutexes
                )
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
                diffs.append(
                    UpgradePolicyHandler(
                        action="create",
                        policy=_create_upgrade_policy(next_schedule, spec, version),
                        gates_to_agree=[
                            GateAgreement(gate=g)
                            for g in gates_to_agree(
                                gates,
                                get_version_prefix(version),
                                spec.cluster,
                                ocm_api,
                            )
                        ],
                    )
                )
            set_mutex(locked, spec.cluster.id, spec.upgrade_policy.conditions.mutexes)

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
