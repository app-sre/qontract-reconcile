import base64
import logging
import sys


import reconcile.openshift_base as ob
import reconcile.queries as queries

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.ocm import OCMMap
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.status import ExitCodes


QONTRACT_INTEGRATION = 'kafka-clusters'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_oc_resource(data):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": "kafka",
            "annotations": {
                "qontract.recycle": "true"
            }
        },
        "data": {
            k: base64.b64encode(v.encode()).decode('utf-8')
            for k, v in data.items()
        }
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)


def fetch_desired_state(clusters):
    desired_state = []
    for cluster_info in clusters:
        item = {
            'name': cluster_info['name'],
            'cloud_provider': cluster_info['spec']['provider'],
            'region': cluster_info['spec']['region'],
            'multi_az': cluster_info['spec']['multi_az'],
        }
        desired_state.append(item)
    return desired_state


@defer
def run(dry_run, thread_pool_size=10,
        internal=None, use_jump_host=True, defer=None):
    kafka_clusters = queries.get_kafka_clusters()
    if not kafka_clusters:
        logging.debug("No Kafka clusters found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(clusters=kafka_clusters,
                     integration=QONTRACT_INTEGRATION,
                     settings=settings)
    namespaces = []
    for kafka_cluster in kafka_clusters:
        namespaces.extend(kafka_cluster['namespaces'])
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=['Secret'],
        internal=internal,
        use_jump_host=use_jump_host)
    defer(lambda: oc_map.cleanup())

    current_state = ocm_map.kafka_cluster_specs()
    desired_state = fetch_desired_state(kafka_clusters)
    kafka_service_accounts = ocm_map.kafka_service_account_specs()

    error = False
    for kafka_cluster in kafka_clusters:
        kafka_cluster_name = kafka_cluster['name']
        # get a service account for the cluster
        # we match cluster to service account by name
        service_accounts = [sa for sa in kafka_service_accounts
                            if sa['name'] == kafka_cluster_name]
        if service_accounts:
            service_account = service_accounts[0]
        else:
            service_account = {}
            logging.info(['create_service_account', kafka_cluster_name])
            if not dry_run:
                ocm = ocm_map.get(kafka_cluster_name)
                service_account = \
                    ocm.create_kafka_service_account(kafka_cluster_name)
        # the name was only needed for matching
        service_account.pop('name', None)
        desired_cluster = [c for c in desired_state
                           if kafka_cluster_name == c['name']][0]
        current_cluster = [c for c in current_state
                           if kafka_cluster_name == c['name']]
        # check if cluster exists. if not - create it
        if not current_cluster:
            logging.info(['create_cluster', kafka_cluster_name])
            if not dry_run:
                ocm = ocm_map.get(kafka_cluster_name)
                ocm.create_kafka_cluster(desired_cluster)
            continue
        # there should only be one cluster
        current_cluster = current_cluster[0]
        # check if desired cluster matches current cluster. if not - error
        if not all(k in current_cluster.keys()
                   for k in desired_cluster.keys()):
            logging.error(
                '[%s] desired spec %s is different ' +
                'from current spec %s',
                kafka_cluster_name, desired_cluster, current_cluster)
            error = True
            continue
        # check if cluster is ready. if not - wait
        if current_cluster['status'] != 'ready':
            continue
        # we have a ready cluster!
        # let's create a Secret in all referencing namespaces
        kafka_namespaces = kafka_cluster['namespaces']
        secret_fields = ['bootstrapServerHost']
        data = {k: v for k, v in current_cluster.items()
                if k in secret_fields}
        data.update(service_account)
        resource = construct_oc_resource(data)
        for namespace_info in kafka_namespaces:
            ri.add_desired(
                namespace_info['cluster']['name'],
                namespace_info['name'],
                resource.kind,
                resource.name,
                resource
            )

    ob.realize_data(dry_run, oc_map, ri)

    if error:
        sys.exit(ExitCodes.ERROR)
