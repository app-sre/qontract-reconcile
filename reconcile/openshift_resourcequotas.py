import collections
import logging
import sys


from reconcile import queries
import reconcile.openshift_base as ob

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR


QONTRACT_INTEGRATION = "openshift-resourcequotas"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


# Copied with love from https://stackoverflow.com/questions/6027558
def flatten(d, parent_key="", sep="."):
    items = []
    for k, v in d.items():
        if v is None:
            continue
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, str(v)))
    return dict(items)


def construct_resource(quota):
    body = {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {"name": quota["name"]},
        "spec": {
            "hard": flatten(quota["resources"]),
        },
    }
    if quota["scopes"]:
        body["spec"]["scopes"] = quota["scopes"]
    return OR(
        body,
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        error_details=quota["name"],
    )


def fetch_desired_state(namespaces, ri, oc_map):
    for namespace_info in namespaces:
        namespace = namespace_info["name"]
        cluster = namespace_info["cluster"]["name"]
        if not oc_map.get(cluster):
            continue
        quotas = namespace_info["quota"]["quotas"]
        for quota in quotas:
            quota_name = quota["name"]
            quota_resource = construct_resource(quota)
            ri.add_desired(
                cluster, namespace, "ResourceQuota", quota_name, quota_resource
            )


@defer
def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    take_over=True,
    defer=None,
):

    namespaces = [
        namespace_info
        for namespace_info in queries.get_namespaces()
        if namespace_info.get("quota")
    ]

    if not namespaces:
        logging.debug("No ResourceQuota definition found in app-interface!")
        sys.exit(0)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["ResourceQuota"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
