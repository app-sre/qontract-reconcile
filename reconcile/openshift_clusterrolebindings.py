import semver

import utils.gql as gql
import reconcile.openshift_base as ob

from utils.defer import defer
from utils.openshift_resource import OpenshiftResource as OR


CLUSTERROLEBINDINGS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
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
    automationToken {
      path
      field
      format
    }
    disable {
      integrations
    }
    clusterRoleBindings {
      name
      roleRef {
        name
      }
      subjects {
        kind
        name
        namespace
      }
      userNames
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-clusterrolebindings'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def fetch_desired_state(clusters, ri):
    for cluster in clusters:
        cluster_name = cluster['name']
        crbs = cluster['clusterRoleBindings']
        for crb in crbs:
            manifest = {
                'apiVersion': '',
                'kind': 'ClusterRoleBinding',
                'metadata': {
                    'name': crb['name']
                },
                'roleRef': crb['roleRef'],
                'subjects': crb['subjects'],
                'userNames': crb['userNames']
            }
            oc_resource = OR(manifest,
                             QONTRACT_INTEGRATION_VERSION,
                             QONTRACT_INTEGRATION,
                             error_details=crb['name'])
            ri.add_desired(
                cluster_name,
                None,
                'ClusterRoleBinding',
                crb['name'],
                oc_resource
            )


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    gqlapi = gql.get_api()

    clusters = [cluster for cluster
                in gqlapi.query(CLUSTERROLEBINDINGS_QUERY)['clusters']
                if cluster.get('clusterRoleBindings')]

    if not clusters:
        return

    ri, oc_map = \
        ob.fetch_current_state(
            clusters=clusters,
            thread_pool_size=thread_pool_size,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            override_managed_types=['ClusterRoleBinding'])
    defer(lambda: oc_map.cleanup())
    fetch_desired_state(clusters, ri)
    ob.realize_data(dry_run, oc_map, ri)
