import sys
import logging
import semver
import collections

import reconcile.queries as queries
import reconcile.openshift_base as ob

from utils.openshift_resource import OpenshiftResource as OR

from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-resourcequotas'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


# Copied with love from https://stackoverflow.com/questions/6027558
def flatten(d, parent_key='', sep='.'):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, collections.MutableMapping):
            items.extend(flatten(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def construct_resource(quota):
    body = {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {
            "name": quota['name']
        },
        "spec": {
            "hard": flatten(quota['resources']),
            "scopes": quota['scopes'] or []
        }
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION,
              error_details=quota['name'])


def fetch_desired_state(namespaces, ri, oc_map):
    for namespace_info in namespaces:
        namespace = namespace_info['name']
        cluster = namespace_info['cluster']['name']
        if not oc_map.get(cluster):
            continue
        quotas = namespace_info['quota']['quotas']
        for quota in quotas:
            quota_name = quota['name']
            quota_resource = construct_resource(quota)
            ri.add_desired(
                cluster,
                namespace,
                'ResourceQuota',
                quota_name,
                quota_resource
            )


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, take_over=True, defer=None):
    try:
        namespaces = [namespace_info for namespace_info
                      in queries.get_namespaces()
                      if namespace_info.get('quota')]
        ri, oc_map = ob.fetch_current_state(
            namespaces=namespaces,
            thread_pool_size=thread_pool_size,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            override_managed_types=['ResourceQuota'],
            internal=internal,
            use_jump_host=use_jump_host)
        defer(lambda: oc_map.cleanup())
        fetch_desired_state(namespaces, ri, oc_map)
        ob.realize_data(dry_run, oc_map, ri)

        if ri.has_error_registered():
            sys.exit(1)

    except Exception as e:
        logging.error(f"Error during execution. Exception: {str(e)}")
        sys.exit(1)
