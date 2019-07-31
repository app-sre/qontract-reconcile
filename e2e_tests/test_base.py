import datetime
import logging

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources

CLUSTERS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    managedGroups
    jumpHost {
      hostname
      knownHosts
      user
      port
      identity {
        path
        field
        format
      }
    }
    unManaged
    automationToken {
      path
      field
      format
    }
  }
}
"""


def get_oc_map():
    gqlapi = gql.get_api()
    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    oc_map = {}

    for cluster_info in clusters:
        cluster = cluster_info['name']
        if cluster_info['unManaged']:
            logging.debug("Skipping {} (unmanaged cluster).".format(cluster))
            continue

        openshift_resources.obtain_oc_client(oc_map, cluster_info)

    return {k: v  for k, v in oc_map.iteritems()
            if v is not False}

def get_test_namespace_name():
    return 'e2e-test-namespace-{}'.format(
        datetime.datetime.utcnow().strftime('%Y%m%d%H%M')
    )
