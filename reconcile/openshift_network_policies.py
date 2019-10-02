import logging
import semver

import utils.gql as gql
import utils.threaded as threaded
import reconcile.openshift_resources as openshift_resources

from utils.openshift_resource import ResourceInventory, OpenshiftResource
from utils.oc import OC_Map
from utils.defer import defer


class OR(OpenshiftResource):
    def __init__(self, body, integration, integration_version):
        super(OR, self).__init__(
            body, integration, integration_version
        )


class ConstructResourceError(Exception):
    def __init__(self, msg):
        super(ConstructResourceError, self).__init__(
            "error construction openshift resource: " + str(msg)
        )


NAMESPACES_QUERY = """
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
    networkPoliciesAllow {
        name
        cluster {
            name
        }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-network-policies'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def populate_current_state(spec, ri):
    if spec.oc is None:
        return
    for item in spec.oc.get_items(spec.resource,
                                  namespace=spec.namespace):
        openshift_resource = OR(item,
                                QONTRACT_INTEGRATION,
                                QONTRACT_INTEGRATION_VERSION)
        ri.add_current(
            spec.cluster,
            spec.namespace,
            spec.resource,
            openshift_resource.name,
            openshift_resource
        )


def fetch_current_state(namespaces, thread_pool_size):
    ri = ResourceInventory()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION)
    state_specs = \
        openshift_resources.init_specs_to_fetch(
            ri,
            oc_map,
            namespaces,
            override_managed_types=['NetworkPolicy']
        )
    threaded.run(populate_current_state, state_specs, thread_pool_size, ri=ri)

    return ri, oc_map


def construct_oc_resource(name, source_ns):
    body = {
        "apiVersion": "extensions/v1beta1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": name
        },
        "spec": {
            "ingress": [{
                "from": [{
                   "namespaceSelector": {
                       "matchLabels": {
                           "name": source_ns
                       }
                   }
                }]
            }],
            "podSelector": {},
            "policyTypes": [
                "Ingress"
            ]
        }
    }
    openshift_resource = OR(body,
                            QONTRACT_INTEGRATION,
                            QONTRACT_INTEGRATION_VERSION)

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise ConstructResourceError(e_msg.format(k, name))
    return openshift_resource


def fetch_desired_state(namespaces, ri):
    for namespace_info in namespaces:
        namespace = namespace_info['name']
        cluster = namespace_info['cluster']['name']
        source_namespaces = namespace_info['networkPoliciesAllow']
        for source_namespace_info in source_namespaces:
            source_namespace = source_namespace_info['name']
            source_cluster = source_namespace_info['cluster']['name']
            if cluster != source_cluster:
                msg = (
                    "[{}/{}] Network Policy from cluster '{}' not allowed."
                ).format(cluster, namespace, source_cluster)
                logging.error(msg)
                continue
            resource_name = "allow-from-{}-namespace".format(source_namespace)
            oc_resource = \
                construct_oc_resource(resource_name, source_namespace)
            ri.add_desired(
                cluster,
                namespace,
                'NetworkPolicy',
                resource_name,
                oc_resource
            )


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    gqlapi = gql.get_api()
    namespaces = [namespace_info for namespace_info
                  in gqlapi.query(NAMESPACES_QUERY)['namespaces']
                  if namespace_info.get('networkPoliciesAllow')]
    ri, oc_map = fetch_current_state(namespaces, thread_pool_size)
    defer(lambda: oc_map.cleanup())
    fetch_desired_state(namespaces, ri)
    openshift_resources.realize_data(dry_run, oc_map, ri)
