import sys
import logging

import utils.oc
import utils.gql as gql
import utils.vault_client as vault_client
from utils.openshift_resource import OpenshiftResource as OR

QUERY = """
{
    clusters: clusters_v1 {
      name
      serverUrl
      automationToken {
        path
        field
        format
      }
    }
}
"""


def get_oc(cluster):
    gqlapi = gql.get_api()
    clusters = gqlapi.query(QUERY)['clusters']

    for cluster_info in clusters:
        if cluster_info['name'] != cluster:
            continue

        at = cluster_info.get('automationToken')

        # Skip if cluster has no automationToken
        if at is None:
            return None
        else:
            token = vault_client.read(at)
            return utils.oc.OC(cluster_info['serverUrl'], token)

    return None


def run(dry_run, cluster, namespace, kind, name):
    oc = get_oc(cluster)

    try:
        resource = oc.get(namespace, kind, name)
    except utils.oc.StatusCodeError as e:
        if e.message.startswith('Error from server (NotFound):'):
            logging.error('Resource not found.')
            sys.exit(1)

    openshift_resource = OR(resource, '', '')

    if openshift_resource.has_qontract_annotations():
        logging.error('already annotated')
        sys.exit(1)

    openshift_resource = openshift_resource.annotate()
    # remove resourceVersion
    openshift_resource.body['metadata'].pop('resourceVersion', None)

    if not dry_run:
        oc.apply(namespace, openshift_resource.toJSON())

    logging.info('annotated')
