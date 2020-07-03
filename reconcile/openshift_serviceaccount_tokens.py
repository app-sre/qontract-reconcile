import sys
import semver
import base64

import utils.vault_client as vault_client
import reconcile.queries as queries
import reconcile.openshift_base as ob

from utils.openshift_resource import OpenshiftResource as OR
from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-serviceaccount-tokens'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def construct_sa_token_oc_resource(name, sa_name, sa_token):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name,
        },
        "data": {
            "token": base64.b64encode(sa_token).decode('utf-8')
        }
    }
    return OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION,
              error_details=name)


def fetch_desired_state(namespaces, ri, oc_map):
    for namespace_info in namespaces:
        if not namespace_info.get('openshiftServiceAccountTokens'):
            continue
        namespace_name = namespace_info['name']
        cluster_name = namespace_info['cluster']['name']
        for sat in namespace_info['openshiftServiceAccountTokens']:
            sa_name = sat['serviceAccountName']
            sa_namespace_info = sat['namespace']
            sa_namespace_name = sa_namespace_info['name']
            sa_cluster_name = sa_namespace_info['cluster']['name']
            oc = oc_map.get(sa_cluster_name)
            sa_token = oc.sa_get_token(sa_namespace_name, sa_name)
            oc_resource_name = \
                f"{sa_cluster_name}-{sa_namespace_name}-{sa_name}"
            oc_resource = construct_sa_token_oc_resource(
                oc_resource_name, sa_name, sa_token)
            ri.add_desired(
                cluster_name,
                namespace_name,
                'Secret',
                oc_resource_name,
                oc_resource
            )


def write_outputs_to_vault(vault_path, ri):
    integration_name = QONTRACT_INTEGRATION.replace('_', '-')
    for cluster, namespace, _, data in ri:
        for name, d_item in data['desired'].items():
            secret_path = \
              f"{vault_path}/{integration_name}/{cluster}/{namespace}/{name}"
            secret = {'path': secret_path, 'data': d_item.body['data']}
            vault_client.write(secret)


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, vault_output_path='', defer=None):
    namespaces = [namespace_info for namespace_info
                  in queries.get_namespaces()
                  if namespace_info.get('openshiftServiceAccountTokens')]
    for namespace_info in namespaces:
        if not namespace_info.get('openshiftServiceAccountTokens'):
            continue
        for sat in namespace_info['openshiftServiceAccountTokens']:
            namespaces.append(sat['namespace'])

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=['Secret'],
        internal=internal,
        use_jump_host=use_jump_host)
    defer(lambda: oc_map.cleanup())
    fetch_desired_state(namespaces, ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri)
    if not dry_run and vault_output_path:
        write_outputs_to_vault(vault_output_path, ri)

    if ri.has_error_registered():
        sys.exit(1)
