import base64
import copy
import logging
import sys

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.defer import defer
from reconcile.utils.ocm import (
    STATUS_FAILED,
    STATUS_READY,
    OCMMap,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import VaultClient

QONTRACT_INTEGRATION = "kafka-clusters"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_oc_resource(data):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {"name": "kafka", "annotations": {"qontract.recycle": "true"}},
        "data": {
            k: base64.b64encode(v.encode()).decode("utf-8") for k, v in data.items()
        },
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)


def fetch_desired_state(clusters):
    desired_state = []
    for cluster_info in clusters:
        item = {
            "name": cluster_info["name"],
            "cloud_provider": cluster_info["spec"]["provider"],
            "region": cluster_info["spec"]["region"],
            "multi_az": cluster_info["spec"]["multi_az"],
        }
        desired_state.append(item)
    return desired_state


def get_kafa_service_account(
    kafka_service_accounts, kafka_cluster_name, vault_throughput_path, dry_run, ocm_map
):
    """
    get a service account for the cluster
    we match cluster to service account by name
    """
    service_accounts = [
        sa for sa in kafka_service_accounts if sa["name"] == kafka_cluster_name
    ]
    if service_accounts:
        result_sa = copy.deepcopy(service_accounts[0])
        # since this is an existing service account
        # we do not get it's client_secret. read it from vault
        cs_key = "client_secret"
        result_sa[cs_key] = read_input_from_vault(
            vault_throughput_path, kafka_cluster_name, cs_key
        )
        # the name was only needed for matching
        result_sa.pop("name", None)
    else:
        result_sa = {}
        logging.info(["create_service_account", kafka_cluster_name])
        if not dry_run:
            ocm = ocm_map.get(kafka_cluster_name)
            sa_fields = ["client_id", "client_secret"]
            result_sa = ocm.create_kafka_service_account(
                kafka_cluster_name, fields=sa_fields
            )

    return result_sa


def read_input_from_vault(vault_path, name, field):
    integration_name = QONTRACT_INTEGRATION
    vault_client = VaultClient()
    secret_path = f"{vault_path}/{integration_name}/{name}"
    secret = {"path": secret_path, "field": field}
    return vault_client.read(secret)


def write_output_to_vault(vault_path, name, data):
    integration_name = QONTRACT_INTEGRATION
    vault_client = VaultClient()
    secret_path = f"{vault_path}/{integration_name}/{name}"
    secret = {"path": secret_path, "data": data}
    vault_client.write(secret)


@defer
def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    vault_throughput_path=None,
    defer=None,
):
    if not vault_throughput_path:
        logging.error("must supply vault throughput path")
        sys.exit(ExitCodes.ERROR)

    kafka_clusters = queries.get_kafka_clusters()
    if not kafka_clusters:
        logging.debug("No Kafka clusters found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=kafka_clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )
    namespaces = []
    for kafka_cluster in kafka_clusters:
        namespaces.extend(kafka_cluster["namespaces"])
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Secret"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)

    current_state = ocm_map.kafka_cluster_specs()
    desired_state = fetch_desired_state(kafka_clusters)
    kafka_service_accounts = ocm_map.kafka_service_account_specs()

    for kafka_cluster in kafka_clusters:
        kafka_cluster_name = kafka_cluster["name"]
        desired_cluster = [c for c in desired_state if kafka_cluster_name == c["name"]][
            0
        ]
        current_cluster = [c for c in current_state if kafka_cluster_name == c["name"]]
        # check if cluster exists. if not - create it
        if not current_cluster:
            logging.info(["create_cluster", kafka_cluster_name])
            if not dry_run:
                ocm = ocm_map.get(kafka_cluster_name)
                ocm.create_kafka_cluster(desired_cluster)
            continue
        # there should only be one cluster
        current_cluster = current_cluster[0]
        # check if desired cluster matches current cluster. if not - error
        if not all(k in current_cluster.keys() for k in desired_cluster.keys()):
            logging.error(
                "[%s] desired spec %s is different " + "from current spec %s",
                kafka_cluster_name,
                desired_cluster,
                current_cluster,
            )
            ri.register_error()
            continue
        # check if cluster is ready. if not - wait
        status = current_cluster["status"]
        if status != STATUS_READY:
            # check if cluster is failed
            if status == STATUS_FAILED:
                failed_reason = current_cluster["failed_reason"]
                logging.error(
                    f"[{kafka_cluster_name}] cluster status is {status}. "
                    f"reason: {failed_reason}"
                )
                ri.register_error()
            else:
                logging.warning(f"[{kafka_cluster_name}] cluster status is {status}")
            continue
        # we have a ready cluster!
        # get a service account for the cluster
        kafka_service_account = get_kafa_service_account(
            kafka_service_accounts,
            kafka_cluster_name,
            vault_throughput_path,
            dry_run,
            ocm_map,
        )
        # let's create a Secret in all referencing namespaces
        kafka_namespaces = kafka_cluster["namespaces"]
        secret_fields = ["bootstrap_server_host"]
        data = {k: v for k, v in current_cluster.items() if k in secret_fields}
        data.update(kafka_service_account)
        resource = construct_oc_resource(data)
        for namespace_info in kafka_namespaces:
            ri.add_desired(
                namespace_info["cluster"]["name"],
                namespace_info["name"],
                resource.kind,
                resource.name,
                resource,
            )
        if not dry_run:
            write_output_to_vault(
                vault_throughput_path, kafka_cluster_name, resource.body["data"]
            )

    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(ExitCodes.ERROR)
