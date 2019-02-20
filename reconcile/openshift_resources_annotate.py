import sys
import logging

import reconcile.gql as gql
from reconcile.openshift_resources import OpenshiftResource

import utils.vault_client as vault_client
import utils.oc

QUERY = """
{
    clusters {
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
            token = vault_client.read(at['path'], at['field'])
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

    openshift_resource = OpenshiftResource(resource)

    if openshift_resource.has_qontract_annotations():
        logging.error('already annotated')
        sys.exit(1)

    openshift_resource.annotate()

    # Remove fields added by
    openshift_resource.body['metadata'].pop('creationTimestamp', None)
    openshift_resource.body['metadata'].pop('selfLink', None)

    body = OpenshiftResource.serialize(openshift_resource.body)
    oc.apply(namespace, body)
    logging.info('annotated')
