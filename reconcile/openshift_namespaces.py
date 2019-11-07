import logging

import utils.gql as gql
import utils.threaded as threaded
import reconcile.openshift_base as ob
import reconcile.queries as queries

from utils.openshift_resource import ResourceInventory
from utils.oc import OC_Map
from utils.defer import defer

QUERY = """
{
  namespaces: namespaces_v1 {
    name
    cluster {
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
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-namespaces'


def get_desired_state():
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(QUERY)['namespaces']
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION,
                    settings=settings)
    ob.init_specs_to_fetch(
        ri,
        oc_map,
        namespaces,
        override_managed_types=['Namespace']
    )
    desired_state = [{"cluster": cluster, "namespace": namespace}
                     for cluster, namespace, _, _ in ri
                     if cluster in oc_map.clusters()]

    return oc_map, desired_state


def check_ns_exists(spec, oc_map):
    cluster = spec['cluster']
    namespace = spec['namespace']
    create = not oc_map.get(cluster).project_exists(namespace)

    return spec, create


def create_new_project(spec, oc_map):
    cluster = spec['cluster']
    namespace = spec['namespace']

    oc_map.get(cluster).new_project(namespace)


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    oc_map, desired_state = get_desired_state()
    defer(lambda: oc_map.cleanup())
    results = threaded.run(check_ns_exists, desired_state, thread_pool_size,
                           oc_map=oc_map)
    specs_to_create = [spec for spec, create in results if create]

    for spec in specs_to_create:
        logging.info(['create', spec['cluster'], spec['namespace']])

        if not dry_run:
            create_new_project(spec, oc_map)
