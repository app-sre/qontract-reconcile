import logging
import sys
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable
from datetime import (
    datetime,
    timedelta,
)
from typing import (
    Any,
    Callable,
    Optional,
)

from croniter import croniter
from pydantic import BaseModel
from semver import VersionInfo

from reconcile.aus.models import (
    ClusterUpgradeSpec,
    ConfiguredAddonUpgradePolicy,
    ConfiguredClusterUpgradePolicy,
    ConfiguredUpgradePolicy,
    ConfiguredUpgradePolicyConditions,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import gql
from reconcile.utils.cluster_version_data import (
    VersionData,
    WorkloadHistory,
    get_version_data,
)
from reconcile.utils.defer import defer
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
    Sector,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import (
    parse_semver,
    sort_versions,
)
from reconcile.utils.state import init_state


class AdvancedUpgradeSchedulerBaseIntegrationParams(PydanticRunParams):

    ocm_environment: Optional[str] = None
    ocm_organization: Optional[str] = None


class AdvancedUpgradeSchedulerBaseIntegration(
    QontractReconcileIntegration[AdvancedUpgradeSchedulerBaseIntegrationParams]
):
    def run(self, dry_run: bool) -> None:
        upgrade_specs = self.get_upgrade_specs()
        for ocm_env, env_upgrade_specs in upgrade_specs.items():
            for org_name, org_upgrade_spec in env_upgrade_specs.items():
                if org_upgrade_spec.specs:
                    self.process_upgrade_policies_in_org(dry_run, org_upgrade_spec)
                else:
                    logging.debug(
                        f"Skip org {org_name} in {ocm_env} because it defines no upgrade policies"
                    )
        sys.exit(0)

    def get_upgrade_specs(self) -> dict[str, dict[str, OrganizationUpgradeSpec]]:
        return {
            ocm_env.name: self.get_ocm_env_upgrade_specs(
                ocm_env,
                self.params.ocm_organization,
            )
            for ocm_env in self.get_ocm_environments()
        }

    def get_ocm_environments(self) -> list[OCMEnvironment]:
        return ocm_environment_query(
            gql.get_api().query,
            variables={"name": self.params.ocm_environment}
            if self.params.ocm_environment
            else None,
        ).environments

    @abstractmethod
    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ...

    @abstractmethod
    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        ...


class GateAgreement(BaseModel):
    id: str

    def create(self, ocm: OCM, cluster_name: str) -> None:
        action_log(
            "create",
            ocm.name,
            cluster_name,
            f"Creating version agreement for gate {self.id}",
        )
        agreement = ocm.create_version_agreement(self.id, cluster_name)
        if agreement.get("version_gate") is None:
            logging.error(
                "Unexpected response while creating version "
                f"agreement with id {self.id} for cluster {cluster_name}"
            )


class AbstractUpgradePolicy(ABC, BaseModel):
    """Abstract class for upgrade policies
    Used to create and delete upgrade policies in OCM."""

    cluster: str
    id: Optional[str]
    next_run: Optional[str]
    schedule: Optional[str]
    schedule_type: str
    version: str

    @abstractmethod
    def create(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def delete(self, ocm: OCM) -> None:
        pass


class AddonUpgradePolicy(AbstractUpgradePolicy):
    """Class to create and delete Addon upgrade policies in OCM"""

    addon_id: str

    def create(self, ocm: OCM) -> None:
        item = {
            "version": self.version,
            "schedule_type": "manual",
            "addon_id": self.addon_id,
            "cluster_id": ocm.cluster_ids[self.cluster],
            "upgrade_type": "ADDON",
        }
        ocm.create_addon_upgrade_policy(self.cluster, item)

    def delete(self, ocm: OCM) -> None:
        item = {
            "version": self.version,
            "id": self.id,
        }
        ocm.delete_addon_upgrade_policy(self.cluster, item)


class ClusterUpgradePolicy(AbstractUpgradePolicy):
    """Class to create and delete ClusterUpgradePolicies in OCM"""

    gates_to_agree: Optional[list[GateAgreement]]

    def _create_gate_agreements(self, ocm: OCM) -> None:
        for gate in self.gates_to_agree or []:
            gate.create(ocm, self.cluster)

    def create(self, ocm: OCM) -> None:
        self._create_gate_agreements(ocm)
        policy = {
            "version": self.version,
            "schedule_type": "manual",
            "next_run": self.next_run,
        }
        ocm.create_upgrade_policy(self.cluster, policy)

    def delete(self, ocm: OCM) -> None:
        item = {
            "version": self.version,
            "id": self.id,
        }
        ocm.delete_upgrade_policy(self.cluster, item)


class UpgradePolicyHandler(BaseModel):
    """Class to handle upgrade policy actions"""

    action: str
    policy: AbstractUpgradePolicy

    def act(self, dry_run: bool, ocm: OCM) -> None:
        action_log(
            self.action,
            ocm.name,
            self.policy.cluster,
            self.policy.version,
            self.policy.next_run,
        )
        if dry_run:
            return

        if not self.action:
            pass
        elif self.action == "delete":
            self.policy.delete(ocm)
        elif self.action == "create":
            self.policy.create(ocm)


def fetch_current_state(
    clusters: list[ClusterUpgradeSpec], ocm_map: OCMMap, addons: bool = False
) -> list[AbstractUpgradePolicy]:
    current_state: list[AbstractUpgradePolicy] = []
    for cluster in clusters:
        cluster_name = cluster.name
        ocm = ocm_map.get(cluster_name)
        if addons:
            upgrade_policies = ocm.get_addon_upgrade_policies(cluster_name)
            for upgrade_policy in upgrade_policies:
                upgrade_policy["cluster"] = cluster_name
                current_state.append(AddonUpgradePolicy(**upgrade_policy))
        else:
            upgrade_policies = ocm.get_upgrade_policies(cluster_name)
            for upgrade_policy in upgrade_policies:
                upgrade_policy["cluster"] = cluster_name
                current_state.append(ClusterUpgradePolicy(**upgrade_policy))

    return current_state


# consider first lower versions and lower soakdays (when versions are equal)
def sort_key(d: ConfiguredUpgradePolicy) -> tuple:
    return (
        parse_semver(d.current_version),
        d.conditions.soakDays or 0,
    )


def fetch_upgrade_policies(
    clusters: list[ClusterUpgradeSpec], ocm_map: OCMMap, addons: bool = False
) -> list[ConfiguredUpgradePolicy]:
    desired_state: list[ConfiguredUpgradePolicy] = []
    for cluster in clusters:
        cluster_name = cluster.name
        ocm: OCM = ocm_map.get(cluster_name)
        if not ocm.is_ready(cluster_name):
            # cluster has been deleted in OCM or is not ready yet
            continue
        # Replace sector names by their related OCM Sector object, including dependencies
        sector = None
        if cluster.upgrade_policy.conditions.sector:
            sector = ocm.sectors[cluster.upgrade_policy.conditions.sector]

        if addons:
            cluster_addons = ocm.get_cluster_addons(cluster_name, with_version=True)
            for addon in cluster_addons:
                ccaup = ConfiguredAddonUpgradePolicy.from_cluster_upgrade_spec(
                    cluster,
                    current_version=addon["version"],
                    addon_id=addon["id"],
                    sector=sector,
                )
                desired_state.append(ccaup)
        else:
            spec = ocm.clusters[cluster_name].spec
            ccup = ConfiguredClusterUpgradePolicy.from_cluster_upgrade_spec(
                cluster,
                current_version=spec.version,
                channel=spec.channel,
                available_upgrades=ocm.available_cluster_upgrades.get(cluster_name),
                sector=sector,
            )
            desired_state.append(ccup)

    return sorted(desired_state, key=sort_key)


def update_history(
    version_data: VersionData, upgrade_policies: list[ConfiguredUpgradePolicy]
) -> None:
    """Update history with information from clusters with upgrade policies.

    Args:
        version_data (VersionData): version data, including history of soakdays
        upgrade_policies (list): query results of clusters upgrade policies
    """
    now = datetime.utcnow()
    check_in = version_data.check_in or now

    # we iterate over clusters upgrade policies and update the version history
    for item in upgrade_policies:
        current_version = item.current_version
        cluster = item.cluster
        workloads = item.workloads
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

    version_data.update_stats(upgrade_policies)

    version_data.check_in = now


@defer
def get_version_data_map(
    dry_run: bool,
    upgrade_policies: list[ConfiguredUpgradePolicy],
    ocm_map: OCMMap,
    integration: str,
    addon_id: str = "",
    defer: Optional[Callable] = None,
) -> dict[str, VersionData]:
    """Get a summary of versions history per OCM instance

    Args:
        dry_run (bool): save updated history to remote state
        upgrade_policies (list): query results of clusters upgrade policies
        ocm_map (OCMMap): OCM clients per OCM instance
        addon_id (str): optional addon id to get & store the addon specific state,
          additionally to the ocm org name
        defer (Optional<Callable>): defer function

    Returns:
        dict: version data per OCM instance
    """
    state = init_state(integration=integration)
    if defer:
        defer(state.cleanup)
    results: dict[str, VersionData] = {}
    # we keep a remote state per OCM instance
    for ocm_name in ocm_map.instances():
        state_key = f"{ocm_name}/{addon_id}" if addon_id else ocm_name
        version_data = get_version_data(state, state_key)
        update_history(version_data, upgrade_policies)
        results[ocm_name] = version_data
        if not dry_run:
            version_data.save(state, state_key)

    # aggregate data from other ocm orgs
    # this is done *after* saving the state: we do not store the other orgs data in our state.
    for ocm_name in ocm_map.instances():
        ocm = ocm_map[ocm_name]
        for other_ocm in ocm.inheritVersionData:
            other_ocm_name = other_ocm["name"]
            if ocm_name == other_ocm_name:
                raise ValueError(
                    f"[{ocm_name}] OCM organization inherits version data from itself"
                )
            if ocm.name not in [
                o["name"] for o in other_ocm.get("publishVersionData") or []
            ]:
                raise ValueError(
                    f"[{ocm_name}] OCM organization inherits version data from {other_ocm_name}, but this data is not published to it: missing publishVersionData in {other_ocm_name}"
                )
            state_key = f"{other_ocm_name}/{addon_id}" if addon_id else other_ocm_name
            other_ocm_data = get_version_data(state, state_key)
            results[ocm_name].aggregate(other_ocm_data, other_ocm_name)

    return results


def workload_sector_versions(sector: Sector, workload: str) -> list[VersionInfo]:
    """
    get all versions of clusters running the specified workload in that sector
    """
    versions = []
    for cluster_info in sector.cluster_infos:
        # clusters within a sector always have workloads (mandatory in schema)
        workloads = cluster_info["upgradePolicy"]["workloads"]
        if workload in workloads:
            versions.append(
                parse_semver(sector.ocmspec(cluster_info["name"]).spec.version)
            )
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
    version_data_map: dict[str, VersionData],
    ocm_name: str,
    workloads: list[str],
    upgrade_conditions: ConfiguredUpgradePolicyConditions,
) -> bool:
    """Check that upgrade conditions are met for a version

    Args:
        version (string): version to check
        version_data_map (dict): history of versions per OCM instance
        ocm_name (string): name of OCM instance
        upgrade_conditions (dict): query results of upgrade conditions
        workloads (list): strings representing types of workloads

    Returns:
        bool: are version upgrade conditions met
    """
    sector = upgrade_conditions.sector
    if sector:
        version_data = version_data_map[ocm_name]
        # check that inherited orgs run at least that version for our workloads
        if not version_data.validate_against_inherited(version, workloads):
            return False

        # check if previous sectors run at least this version for that workload
        # we will check dependencies recursively until there are versions for the given workload
        # or no more dependencies to check
        for w in workloads:
            for dep in workload_sector_dependencies(sector, w):
                dep_versions = workload_sector_versions(dep, w)
                if not dep_versions:
                    continue
                if min(dep_versions) < parse_semver(version):
                    return False

    # check soak days condition is met for this version
    soak_days = upgrade_conditions.soakDays
    if soak_days is not None:
        version_data = version_data_map[ocm_name]
        for w in workloads:
            workload_history = version_data.workload_history(version, w)
            if soak_days > workload_history.soak_days:
                return False

    return True


def gates_to_agree(
    version_prefix: str, cluster: str, cluster_version: str, ocm: OCM
) -> list[str]:
    """Check via OCM if a version is agreed

    Args:
        version_prefix (string): major.minor version prefix
        cluster (string)
        cluster_version (string): current version of the cluster
        ocm (OCM): used to fetch infos from OCM

    Returns:
        list[str]: list of gate ids to agree
    """
    agreements = {
        agreement["version_gate"]["id"]
        for agreement in ocm.get_version_agreement(cluster)
    }
    semver_cluster = parse_semver(f"{cluster_version}")

    return [
        gate["id"]
        for gate in ocm.get_version_gates(version_prefix)
        if gate["id"] not in agreements and semver_cluster.match(f"<{version_prefix}.0")
    ]


def get_version_prefix(version: str) -> str:
    semver = parse_semver(version)
    return f"{semver.major}.{semver.minor}"


def upgradeable_version(
    policy: ConfiguredUpgradePolicy,
    version_data_map: dict[str, VersionData],
    ocm: OCM,
    upgrades: Iterable[str],
    addon_id: str = "",
) -> Optional[str]:
    """Get the highest next version we can upgrade to, fulfilling all conditions"""
    for version in reversed(sort_versions(upgrades)):
        if addon_id and ocm.addon_version_blocked(version, addon_id):
            continue
        if not addon_id and ocm.version_blocked(version):
            continue
        if version_conditions_met(
            version,
            version_data_map,
            ocm.name,
            policy.workloads,
            policy.conditions,
        ):
            return version
    return None


def verify_current_should_skip(
    current_state: list[AbstractUpgradePolicy],
    cluster: str,
    now: datetime,
    ocm: OCM,
    addon_id: str = "",
) -> tuple[bool, Optional[UpgradePolicyHandler]]:
    current_policies = [c for c in current_state if c.cluster == cluster]
    if not current_policies:
        return False, None

    # there can only be one upgrade policy per cluster
    if len(current_policies) != 1:
        raise ValueError(f"[{cluster}] expected only one upgrade policy")
    current = current_policies[0]
    version = current.version  # may not exist in automatic upgrades
    if version and not addon_id and ocm.version_blocked(version):
        next_run = current.next_run
        if next_run and datetime.strptime(next_run, "%Y-%m-%dT%H:%M:%SZ") < now:
            logging.warning(
                f"[{cluster}] currently upgrading to blocked version '{version}'"
            )
            return True, None
        logging.debug(
            f"[{ocm.name}/{cluster}] found planned upgrade policy "
            + f"with blocked version {version}"
        )
        return False, UpgradePolicyHandler(action="delete", policy=current)

    # else
    logging.debug(
        f"[{ocm.name}/{cluster}] skipping cluster with existing upgrade policy"
    )
    return True, None


def verify_schedule_should_skip(
    d: ConfiguredUpgradePolicy,
    cluster: str,
    now: datetime,
    ocm: OCM,
    addon_id: str = "",
) -> Optional[str]:
    schedule = d.schedule
    iter = croniter(schedule)
    # ClusterService refuses scheduling upgrades less than 5m in advance
    # Let's find the next schedule that is at least 5m ahead.
    # We do not need that much delay for addon upgrades since they run
    # immediately
    delay_minutes = 1 if addon_id else 5
    next_schedule = iter.get_next(
        datetime, start_time=now + timedelta(minutes=delay_minutes)
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
            f"[{ocm.name}/{cluster}] skipping cluster with no upcoming upgrade"
        )
        return None
    return next_schedule.strftime("%Y-%m-%dT%H:%M:%SZ")


def verify_lock_should_skip(
    d: ConfiguredUpgradePolicy, locked: dict[str, Any], ocm: OCM, cluster: str
) -> bool:
    mutexes = d.conditions.get_mutexes()
    if any(lock in locked for lock in mutexes):
        locking = {lock: locked[lock] for lock in mutexes if lock in locked}
        logging.debug(
            f"[{ocm.name}/{cluster}] skipping cluster: locked out by {locking}"
        )
        return True
    return False


def get_upgrades(addon_id: str, d: ConfiguredUpgradePolicy, ocm: OCM) -> list[str]:
    # choose version that meets the conditions and add it to the diffs
    upgrades = []
    if addon_id and isinstance(d, ConfiguredAddonUpgradePolicy):
        # an alternative is to find available upgrades for our current version from
        # ${API_CLUSTERS_MGMT}/addons/${addon_id}/versions
        # .items[] | select(.id == {current_version}) | .available_upgrades
        # but we will always want to get the one that is currently published normally
        upgrades = [
            a["version"]["id"]
            for a in ocm.addons
            if a["id"] == addon_id and a["version"]["id"] != d.current_version
        ]
    elif isinstance(d, ConfiguredClusterUpgradePolicy):
        upgrades = ocm.get_available_upgrades(d.current_version, d.channel)
    return upgrades


def calculate_diff(
    current_state: list[AbstractUpgradePolicy],
    upgrade_policies: list[ConfiguredUpgradePolicy],
    ocm_map: OCMMap,
    version_data_map: dict[str, VersionData],
    addon_id: str = "",
) -> list[UpgradePolicyHandler]:
    """Check available upgrades for each cluster in the desired state
    according to upgrade conditions

    Args:
        current_state (list): currently existing upgrade policies
        upgrade_policies (list): upgradePolicy in app interface
        ocm_map (OCMMap): OCM clients per OCM instance
        version_data_map (dict): version data history per OCM instance
        addon_id (str): optional addonid to calculate diffs for

    Returns:
        list: upgrade policies to be applied
    """
    diffs: list[UpgradePolicyHandler] = []

    # all clusters with a current upgradePolicy are considered locked
    locked = {}
    for policy in upgrade_policies:
        if policy.cluster in [s.cluster for s in current_state]:
            for mutex in policy.conditions.get_mutexes():
                locked[mutex] = policy.cluster

    now = datetime.utcnow()
    for p in upgrade_policies:
        # ignore clusters with an existing upgrade policy
        ocm = ocm_map.get(p.cluster)

        skip, delete_policy = verify_current_should_skip(
            current_state, p.cluster, now, ocm, addon_id
        )
        if skip:
            continue
        if delete_policy:
            diffs.append(delete_policy)

        next_schedule = verify_schedule_should_skip(p, p.cluster, now, ocm, addon_id)
        if not next_schedule:
            continue

        if verify_lock_should_skip(p, locked, ocm, p.cluster):
            continue

        upgrades = get_upgrades(addon_id, p, ocm)
        version = upgradeable_version(p, version_data_map, ocm, upgrades, addon_id)
        if version:
            if addon_id:
                diffs.append(
                    UpgradePolicyHandler(
                        action="create",
                        policy=AddonUpgradePolicy(
                            **{
                                "action": "create",
                                "cluster": p.cluster,
                                "version": version,
                                "schedule_type": "manual",
                                "addon_id": addon_id,
                                "upgrade_type": "ADDON",
                            }
                        ),
                    )
                )
            else:
                diffs.append(
                    UpgradePolicyHandler(
                        action="create",
                        policy=ClusterUpgradePolicy(
                            **{
                                "action": "create",
                                "cluster": p.cluster,
                                "version": version,
                                "schedule_type": "manual",
                                "next_run": next_schedule,
                                "gates_to_agree": [
                                    GateAgreement(id=g)
                                    for g in gates_to_agree(
                                        get_version_prefix(version),
                                        p.cluster,
                                        p.current_version,
                                        ocm,
                                    )
                                ],
                            }
                        ),
                    )
                )

            for mutex in p.conditions.get_mutexes():
                locked[mutex] = p.cluster

    return diffs


def sort_diffs(diff: UpgradePolicyHandler) -> int:
    if diff.action == "delete":
        return 1
    return 2


def action_log(*items: Optional[str]) -> None:
    # log all non-empty, non-null items
    logging.info([item for item in items if item])


def act(
    dry_run: bool,
    diffs: list[UpgradePolicyHandler],
    ocm_map: OCMMap,
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
        ocm = ocm_map.get(policy.cluster)
        diff.act(dry_run, ocm)
