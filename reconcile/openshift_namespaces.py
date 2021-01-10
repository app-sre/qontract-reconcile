import logging

import reconcile.utils.gql as gql
import reconcile.utils.threaded as threaded
import reconcile.openshift_base as ob
import reconcile.queries as queries

from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.oc import OC_Map
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.defer import defer
from reconcile.utils.sharding import is_in_shard


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
      internal
      disable {
        integrations
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-namespaces'


def get_desired_state(internal, use_jump_host, thread_pool_size):
    gqlapi = gql.get_api()
    all_namespaces = gqlapi.query(QUERY)['namespaces']

    namespaces = []
    for namespace in all_namespaces:
        shard_key = f'{namespace["cluster"]["name"]}/{namespace["name"]}'
        if is_in_shard(shard_key):
            namespaces.append(namespace)

    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size,
                    init_projects=True)
    ob.init_specs_to_fetch(
        ri,
        oc_map,
        namespaces=namespaces,
        override_managed_types=['Namespace']
    )

    desired_state = []
    for cluster, namespace, _, _ in ri:
        if cluster not in oc_map.clusters():
            continue
        desired_state.append({"cluster": cluster, "namespace": namespace})

    return oc_map, desired_state


def check_ns_exists(spec, oc_map):
    cluster = spec['cluster']
    namespace = spec['namespace']

    try:
        create = not oc_map.get(cluster).project_exists(namespace)
        return spec, create
    except StatusCodeError as e:
        msg = 'cluster: {},'
        msg += 'namespace: {},'
        msg += 'exception: {}'
        msg = msg.format(cluster,
                         namespace,
                         str(e))
        logging.error(msg)

    return spec, None


def create_new_project(spec, oc_map):
    cluster = spec['cluster']
    namespace = spec['namespace']

    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None
    oc.new_project(namespace)


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    oc_map, desired_state = get_desired_state(internal, use_jump_host,
                                              thread_pool_size)
    defer(lambda: oc_map.cleanup())
    results = threaded.run(check_ns_exists, desired_state, thread_pool_size,
                           oc_map=oc_map)
    specs_to_create = [spec for spec, create in results if create]

    for spec in specs_to_create:
        logging.info(['create', spec['cluster'], spec['namespace']])

        if not dry_run:
            create_new_project(spec, oc_map)
