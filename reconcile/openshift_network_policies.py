import logging
import sys
from textwrap import indent

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    delete
    clusterAdmin
    cluster {
      name
      serverUrl
      insecureSkipTLSVerify
      jumpHost {
        %s
      }
      automationToken {
        path
        field
        version
        format
      }
      clusterAdminAutomationToken {
        path
        field
        version
        format
      }
      internal
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
""" % (indent(queries.JUMPHOST_FIELDS, 8 * " "),)

QONTRACT_INTEGRATION = "openshift-network-policies"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_oc_resource(name, source_ns):
    body = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name},
        "spec": {
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": source_ns
                                }
                            }
                        }
                    ]
                }
            ],
            "podSelector": {},
            "policyTypes": ["Ingress"],
        },
    }
    return OR(
        body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
    )


def fetch_desired_state(namespaces, ri, oc_map):
    for namespace_info in namespaces:
        namespace = namespace_info["name"]
        cluster = namespace_info["cluster"]["name"]
        if not oc_map.get(cluster):
            continue
        source_namespaces = namespace_info["networkPoliciesAllow"]
        for source_namespace_info in source_namespaces:
            source_namespace = source_namespace_info["name"]
            source_cluster = source_namespace_info["cluster"]["name"]
            if cluster != source_cluster:
                ri.register_error()
                msg = f"[{cluster}/{namespace}] Network Policy from cluster '{source_cluster}' not allowed."
                logging.error(msg)
                continue
            resource_name = f"allow-from-{source_namespace}-namespace"
            oc_resource = construct_oc_resource(resource_name, source_namespace)
            ri.add_desired(
                cluster,
                namespace,
                "NetworkPolicy",
                resource_name,
                oc_resource,
                privileged=namespace_info.get("clusterAdmin") or False,
            )


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
    gqlapi = gql.get_api()

    namespaces = []
    for namespace_info in gqlapi.query(NAMESPACES_QUERY)["namespaces"]:
        if not namespace_info.get("networkPoliciesAllow"):
            continue
        if ob.is_namespace_deleted(namespace_info):
            continue

        shard_key = f"{namespace_info['cluster']['name']}/{namespace_info['name']}"

        if not is_in_shard(shard_key):
            continue

        namespaces.append(namespace_info)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["NetworkPolicy"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
