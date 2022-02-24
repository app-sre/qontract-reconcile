import sys
import logging
import json

from reconcile import queries

from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-machine-pools"


def fetch_current_state(clusters):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )

    current_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        machine_pools = ocm.get_machine_pools(cluster_name)
        for machine_pool in machine_pools:
            machine_pool["cluster"] = cluster_name
            current_state.append(machine_pool)

    return ocm_map, current_state


def fetch_desired_state(clusters):
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        machine_pools = cluster["machinePools"]
        for machine_pool in machine_pools:
            machine_pool["cluster"] = cluster_name
            labels = machine_pool.pop("labels")
            if labels:
                machine_pool["labels"] = json.loads(labels)
            taints = machine_pool.pop("taints")
            if taints:
                machine_pool["taints"] = taints
            desired_state.append(machine_pool)

    return desired_state


def calculate_diff(current_state, desired_state):
    diffs = []
    err = False
    for d in desired_state:
        c = [
            c
            for c in current_state
            if d["cluster"] == c["cluster"] and d["id"] == c["id"]
        ]
        if not c:
            d["action"] = "create"
            diffs.append(d)
            continue
        if len(c) != 1:
            logging.error(f"duplicate id found in {d['cluster']}")
            err = True
            continue
        c = c[0]
        if c == d:
            continue
        if d["instance_type"] != c["instance_type"]:
            logging.error(
                f"can not update instance type for existing "
                f"machine pool {d['id']} in {d['cluster']}"
            )
            err = True
            continue
        d.pop("instance_type")
        for key in ["labels", "taints"]:
            if c.get(key, None) != d.get(key, None):
                # https://github.com/openshift/machine-api-operator/blob/master/FAQ.md
                logging.warning(
                    f"update {key} for machine pool {d['id']} "
                    f"will only be applied to new Nodes"
                )
        d["action"] = "update"
        diffs.append(d)

    for c in current_state:
        d = [
            d
            for d in desired_state
            if c["cluster"] == d["cluster"] and c["id"] == d["id"]
        ]
        if not d:
            c["action"] = "delete"
            diffs.append(c)

    return diffs, err


def act(dry_run, diffs, ocm_map):
    for diff in diffs:
        action = diff.pop("action")
        cluster = diff.pop("cluster")
        logging.info([action, cluster, diff["id"]])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if action == "create":
                ocm.create_machine_pool(cluster, diff)
            elif action == "update":
                ocm.update_machine_pool(cluster, diff)
            elif action == "delete":
                ocm.delete_machine_pool(cluster, diff)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get("machinePools") is not None]
    if not clusters:
        logging.debug("No machinePools definitions found in app-interface")
        sys.exit(0)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs, err = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(1)
