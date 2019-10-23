import semver

import utils.gql as gql
import utils.threaded as threaded
import reconcile.openshift_base as ob

from utils.oc import OC_Map
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


def get_cluster_state(cluster, oc_map):
    results = []
    oc = oc_map.get(cluster["name"])
    crbs = oc.get_all('ClusterRoleBinding')
    for crb in crbs["items"]:
        results.append({
            "cluster": cluster['name'],
            "clusterrolebinding": crb,
        })
    return results


def fetch_current_state(clusters, thread_pool_size):
    current_state = []
    oc_map = OC_Map(clusters=clusters, integration=QONTRACT_INTEGRATION)
    results = threaded.run(get_cluster_state,
                           clusters,
                           thread_pool_size,
                           oc_map=oc_map)
    for sublist in results:
        for item in sublist:
            item['clusterrolebinding']['name'] = \
                item['clusterrolebinding']['metadata']['name']
            item['clusterrolebinding'].pop('kind')
            item['clusterrolebinding'].pop('apiVersion')
            item['clusterrolebinding'].pop('metadata')
            current_state.append({
                'cluster': item['cluster'],
                'clusterrolebinding': item['clusterrolebinding']
            })
    return oc_map, current_state


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


def obj_intersect_equal(obj1, obj2):
    if obj1.__class__ != obj2.__class__:
        return False

    if isinstance(obj1, dict):
        for k, v in obj1.items():
            if not obj_intersect_equal(v, obj2.get(k)):
                return False
    elif isinstance(obj1, list):
        if len(obj1) != len(obj2):
            return False

        for i in range(len(obj1)):
            if obj1[i] != obj2[i]:
                return False
    else:
        if obj1 != obj2:
            return False

    return True


def calculate_diff(current, desired):
    diff = []

    for d_state in desired:
        d_crb = d_state['clusterrolebinding']
        d_crb_name = d_crb['name']

        found = False
        for c_state in current:
            c_crb = c_state['clusterrolebinding']
            c_crb_name = c_crb['name']
            if c_crb_name != d_crb_name:
                continue
            found = True
            break
        if found:
            details = []
            if c_crb['roleRef']['name'] != d_crb['roleRef']['name']:
                details.extend([
                    'roleRef', [
                        'before', c_crb['roleRef']['name'],
                        'after', d_crb['roleRef']['name']
                    ]
                ])
            if not obj_intersect_equal(c_crb['subjects'], d_crb['subjects']):
                details.extend([
                    'subjects', [
                        'before', c_crb['subjects'],
                        'after', d_crb['subjects']
                    ]
                ])
            if not obj_intersect_equal(c_crb['userNames'], d_crb['userNames']):
                details.extend([
                    'userNames', [
                        'before', c_crb['userNames'],
                        'after', d_crb['userNames']
                    ]
                ])
            diff.append({
                'action': 'update_clusterrolebinding',
                'cluster': d_state['cluster'],
                'clusterrolebinding': d_state['clusterrolebinding'],
                'details': details
            })
        else:
            diff.append({
                'action': 'add_clusterrolebinding',
                'cluster': d_state['cluster'],
                'clusterrolebinding': d_state['clusterrolebinding'],
                'details': None
            })

    return diff


def has_duplicates(desired):
    clusters = {}
    for d in desired:
        d_cluster = d['cluster']
        if d['clusterrolebinding']['name'] in clusters.get(d_cluster, []):
            return {
                'cluster': d_cluster,
                'name': d['clusterrolebinding']['name']
            }
        clusters.setdefault(d_cluster, []).append(
            d['clusterrolebinding']['name']
        )
    return False


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    gqlapi = gql.get_api()

    clusters = [cluster for cluster
                in gqlapi.query(CLUSTERROLEBINDINGS_QUERY)['clusters']
                if cluster.get('clusterRoleBindings')]
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
