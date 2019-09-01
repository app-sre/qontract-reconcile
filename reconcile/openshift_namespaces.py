import logging

from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources

from utils.openshift_resource import ResourceInventory
from utils.oc import OC_Map


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
    }
  }
}
"""


def get_desired_state():
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(QUERY)['namespaces']
    ri = ResourceInventory()
    oc_map = OC_Map(namespaces=namespaces)
    openshift_resources.init_specs_to_fetch(
        ri,
        oc_map,
        namespaces,
        override_managed_types=['Namespace']
    )
    desired_state = [{"cluster": cluster, "namespace": namespace}
                     for cluster, namespace, _, _ in ri]

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


def run(dry_run=False, thread_pool_size=10):
    oc_map, desired_state = get_desired_state()

    pool = ThreadPool(thread_pool_size)
    check_ns_exists_partial = \
        partial(check_ns_exists, oc_map=oc_map)
    results = pool.map(check_ns_exists_partial, desired_state)
    specs_to_create = [spec for spec, create in results if create]

    for spec in specs_to_create:
        logging.info(['create', spec['cluster'], spec['namespace']])

        if not dry_run:
            create_new_project(spec, oc_map)
