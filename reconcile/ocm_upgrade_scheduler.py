import sys
import logging
import copy

from datetime import datetime
from typing import Any, Mapping, Optional
from dateutil import parser
from croniter import croniter

from reconcile import queries

from reconcile.utils.ocm import OCM, OCM_PRODUCT_OSD, OCMMap
from reconcile.utils.state import State
from reconcile.utils.data_structures import get_or_init
from reconcile.utils.semver_helper import parse_semver, sort_versions
from reconcile.ocm.utils import cluster_disabled_integrations

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler"

SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


# consider first lower versions and lower soakdays (when versions are equal)
def sort_key(d: dict) -> tuple:
    return (
        parse_semver(d["current_version"]),
        d["conditions"].get("soakDays") or 0,
    )


def fetch_current_state(
    clusters: list[dict[str, Any]], ocm_map: OCMMap
) -> list[dict[str, Any]]:
    current_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        upgrade_policies = ocm.get_upgrade_policies(cluster_name)
        for upgrade_policy in upgrade_policies:
            upgrade_policy["cluster"] = cluster_name
            current_state.append(upgrade_policy)

    return current_state


def fetch_desired_state(
    clusters: list[dict[str, Any]], ocm_map: OCMMap
) -> list[dict[str, Any]]:
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        upgrade_policy = cluster["upgradePolicy"]
        upgrade_policy["cluster"] = cluster_name
        ocm: OCM = ocm_map.get(cluster_name)
        spec = ocm.clusters[cluster_name].spec
        upgrade_policy["current_version"] = spec.version
        upgrade_policy["channel"] = spec.channel
        desired_state.append(upgrade_policy)

    sorted_desired_state = sorted(desired_state, key=sort_key)

    return sorted_desired_state


def update_history(history, upgrade_policies):
    """Update history with information from clusters
    with upgrade policies.

    Args:
        history (dict): history in the following format:
        {
          "check_in": "2021-08-29 18:01:27.730441",
          "versions": {
            "version1": {
                "workloads": {
                    "workload1": {
                        "soak_days": 21,
                        "reporting": [
                            "cluster1",
                            "cluster2"
                        ]
                    },
                        "workload2": {
                        "soak_days": 6,
                        "reporting": [
                            "cluster3"
                        ]
                    }
                }
            }
          }
        }
        upgrade_policies (list): query results of clusters upgrade policies
    """
    default_workload_history = {
        "soak_days": 0.0,
        "reporting": [],
    }

    now = datetime.utcnow()
    check_in = parser.parse(get_or_init(history, "check_in", str(now)))
    versions = get_or_init(history, "versions", {})

    # we iterate over clusters upgrade policies and update the version history
    for item in upgrade_policies:
        current_version = item["current_version"]
        version_history = get_or_init(versions, current_version, {})
        version_workloads = get_or_init(version_history, "workloads", {})
        cluster = item["cluster"]
        workloads = item["workloads"]
        # we keep the version history per workload
        for w in workloads:
            workload_history = get_or_init(
                version_workloads, w, copy.deepcopy(default_workload_history)
            )

            reporting = workload_history["reporting"]
            # if the cluster is already reporting - accumulate it.
            # if not - add it to the reporting list (first report)
            if cluster in reporting:
                workload_history["soak_days"] += (
                    now - check_in
                ).total_seconds() / 86400  # seconds in day
            else:
                workload_history["reporting"].append(cluster)

    history["check_in"] = str(now)


def get_version_history(dry_run, upgrade_policies, ocm_map):
    """Get a summary of versions history per OCM instance

    Args:
        dry_run (bool): save updated history to remote state
        upgrade_policies (list): query results of clusters upgrade policies
        ocm_map (OCMMap): OCM clients per OCM instance

    Returns:
        dict: version history per OCM instance
    """
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    results = {}
    # we keep a remote state per OCM instance
    for ocm_name in ocm_map.instances():
        history = state.get(ocm_name, {})
        update_history(history, upgrade_policies)
        results[ocm_name] = history
        if not dry_run:
            state.add(ocm_name, history, force=True)

    return results


def version_conditions_met(version, history, ocm_name, workloads, upgrade_conditions):
    """Check that upgrade conditions are met for a version

    Args:
        version (string): version to check
        history (dict): history of versions per OCM instance
        ocm_name (string): name of OCM instance
        upgrade_conditions (dict): query results of upgrade conditions
        workloads (list): strings representing types of workloads

    Returns:
        bool: are version upgrade conditions met
    """
    conditions_met = True
    # check soak days condition is met for this version
    soak_days = upgrade_conditions.get("soakDays", None)
    if soak_days is not None:
        ocm_history = history[ocm_name]
        version_history = ocm_history["versions"].get(version, {})
        for w in workloads:
            workload_history = version_history.get("workloads", {}).get(w, {})
            if soak_days > workload_history.get("soak_days", 0.0):
                conditions_met = False

    return conditions_met


def gates_to_agree(version_prefix: str, cluster: str, ocm: OCM) -> list[str]:
    """Check via OCM if a version is agreed

    Args:
        version_prefix (string): major.minor version prefix
        cluster (string)
        ocm (OCM): used to fetch infos from OCM

    Returns:
        bool: true on missing agreement
    """
    agreements = {
        agreement["version_gate"]["id"]
        for agreement in ocm.get_version_agreement(cluster)
    }

    return [
        gate["id"]
        for gate in ocm.get_version_gates(version_prefix)
        if gate["id"] not in agreements
    ]


def get_version_prefix(version: str) -> str:
    semver = parse_semver(version)
    return f"{semver.major}.{semver.minor}"


def upgradeable_version(policy: Mapping, history: Mapping, ocm: OCM) -> Optional[str]:
    """Get the highest next version we can upgrade to, fulfilling all conditions"""
    upgrades = ocm.get_available_upgrades(policy["current_version"], policy["channel"])
    for version in reversed(sort_versions(upgrades)):
        if ocm.version_blocked(version):
            continue
        if version_conditions_met(
            version,
            history,
            ocm.name,
            policy["workloads"],
            policy["conditions"],
        ):
            return version
    return None


def cluster_mutexes(policy: dict) -> list[str]:
    """List all mutex locks for the given cluster"""
    return (policy.get("conditions") or {}).get("mutexes") or []


def calculate_diff(current_state, desired_state, ocm_map, version_history):
    """Check available upgrades for each cluster in the desired state
    according to upgrade conditions

    Args:
        current_state (list): current state of upgrade policies
        desired_state (list): desired state of upgrade policies
        ocm_map (OCMMap): OCM clients per OCM instance
        version_history (dict): version history per OCM instance

    Returns:
        list: upgrade policies to be applied
    """
    diffs = []

    # all clusters with a current upgradePolicy are considered locked
    locked = {}
    for policy in desired_state:
        if policy["cluster"] in [s["cluster"] for s in current_state]:
            for mutex in cluster_mutexes(policy):
                locked[mutex] = policy["cluster"]

    now = datetime.utcnow()
    for d in desired_state:
        # ignore clusters with an existing upgrade policy
        cluster = d["cluster"]
        ocm = ocm_map.get(cluster)
        c = [c for c in current_state if c["cluster"] == cluster]
        if c:
            # there can only be one upgrade policy per cluster
            if len(c) != 1:
                raise ValueError(f"[{cluster}] expected only one upgrade policy")
            [c] = c
            version = c.get("version")  # may not exist in automatic upgrades
            if version and ocm.version_blocked(version):
                next_run = c.get("next_run")
                if next_run and datetime.strptime(next_run, "%Y-%m-%dT%H:%M:%SZ") < now:
                    logging.warning(
                        f"[{cluster}] currently upgrading to blocked version '{version}'"
                    )
                    continue
                logging.debug(
                    f"[{ocm.name}/{cluster}] found planned upgrade policy "
                    + f"with blocked version {version}"
                )
                item = {
                    "action": "delete",
                    "cluster": cluster,
                    "version": version,
                    "id": c["id"],
                }
                diffs.append(item)
            else:
                logging.debug(
                    f"[{ocm.name}/{cluster}] skipping cluster with existing upgrade policy"
                )
                continue

        # ignore clusters with an upgrade schedule not within the next 2 hours
        schedule = d["schedule"]
        next_schedule = croniter(schedule).get_next(datetime)
        next_schedule_in_hours = (
            next_schedule - now
        ).total_seconds() / 3600  # seconds in hour
        if next_schedule_in_hours > 2:
            logging.debug(
                f"[{ocm.name}/{cluster}] skipping cluster with no upcoming upgrade"
            )
            continue

        if any(lock in locked for lock in cluster_mutexes(d)):
            locking = {
                lock: locked[lock] for lock in cluster_mutexes(d) if lock in locked
            }
            logging.debug(
                f"[{ocm.name}/{cluster}] skipping cluster: locked out by {locking}"
            )
            continue

        # choose version that meets the conditions and add it to the diffs
        version = upgradeable_version(d, version_history, ocm)
        if version:
            item = {
                "action": "create",
                "cluster": cluster,
                "version": version,
                "schedule_type": "manual",
                "next_run": next_schedule.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gates_to_agree": gates_to_agree(
                    get_version_prefix(version), cluster, ocm
                ),
            }
            for mutex in cluster_mutexes(d):
                locked[mutex] = cluster
            diffs.append(item)

    return diffs


def sort_diffs(diff):
    if diff["action"] == "delete":
        return 1
    else:
        return 2


def act(dry_run, diffs, ocm_map):
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        action = diff.pop("action")
        cluster = diff.pop("cluster")
        ocm = ocm_map.get(cluster)
        if action == "create":
            gates_to_agree = diff.pop("gates_to_agree")
            logging.info([action, cluster, diff["version"], diff["next_run"]])
            if not dry_run:
                for gate in gates_to_agree:
                    logging.info(
                        [
                            action,
                            cluster,
                            diff["version"],
                            f"Creating version agreement for gate {gate}",
                        ]
                    )
                    agreement = ocm.create_version_agreement(gate, cluster)
                    if agreement.get("version_gate") is None:
                        logging.error(
                            f"Unexpected response while creating version "
                            f"agreement with id {gate} for cluster {cluster}"
                        )
                ocm.create_upgrade_policy(cluster, diff)
        elif action == "delete":
            logging.info([action, cluster, diff["version"]])
            if not dry_run:
                ocm.delete_upgrade_policy(cluster, diff)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return (
        cluster.get("ocm") is not None
        and cluster.get("upgradePolicy") is not None
        and cluster["spec"]["product"] in SUPPORTED_OCM_PRODUCTS
    )


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    clusters = queries.get_clusters()
    settings = queries.get_app_interface_settings()

    clusters = [
        c
        for c in clusters
        if QONTRACT_INTEGRATION not in cluster_disabled_integrations(c)
        and _cluster_is_compatible(c)
    ]

    if not clusters:
        logging.debug("No upgradePolicy definitions found in app-interface")
        sys.exit(0)

    ocm_map = OCMMap(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        init_version_gates=True,
    )
    current_state = fetch_current_state(clusters, ocm_map)
    desired_state = fetch_desired_state(clusters, ocm_map)
    version_history = get_version_history(dry_run, desired_state, ocm_map)
    diffs = calculate_diff(current_state, desired_state, ocm_map, version_history)
    act(dry_run, diffs, ocm_map)
