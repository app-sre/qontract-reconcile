import logging
import sys
import base64
import json

import anymarkup
import semver

import utils.gql as gql
import utils.vault_client as vault_client

from utils.oc import OC, StatusCodeError
from utils.openshift_resource import (OpenshiftResource,
                                      ResourceInventory,
                                      ResourceKeyExistsError)
from multiprocessing.dummy import Pool as ThreadPool
from functools import partial
from threading import Lock

"""
+-----------------------+-------------------------+-------------+
|   Current \ Desired   |         Present         | Not Present |
+=======================+=========================+=============+
| Present               | Apply if sha256sum      | Delete      |
| (with annotations)    | is different or if      |             |
|                       | sha256sum is stale      |             |
|                       | (due to manual changes) |             |
+-----------------------+-------------------------+-------------+
| Present               | Skip (exit 1)           | Skip        |
| (without annotations) |                         |             |
+-----------------------+-------------------------+-------------+
| Not Present           | Apply                   | Skip        |
+-----------------------+-------------------------+-------------+
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedResourceTypes
    openshiftResources {
      provider
      ... on NamespaceOpenshiftResourceResource_v1 {
        path
      }
      ... on NamespaceOpenshiftResourceVaultSecret_v1 {
        path
        version
        name
        labels
        annotations
        type
      }
      ... on NamespaceOpenshiftResourceRoute_v1 {
        path
        vault_tls_secret_path
        vault_tls_secret_version
      }
    }
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

QONTRACT_INTEGRATION = 'openshift_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 8, 2)
QONTRACT_BASE64_SUFFIX = '_qb64'

_log_lock = Lock()


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + str(msg)
        )


class FetchVaultSecretError(Exception):
    def __init__(self, msg):
        super(FetchVaultSecretError, self).__init__(
            "error fetching vault secret: " + str(msg)
        )


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


class StateSpec(object):
    def __init__(self, type, oc, cluster, namespace, resource):
        self.type = type
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.resource = resource


def obtain_oc_client(oc_map, cluster_info):
    cluster = cluster_info['name']
    if oc_map.get(cluster) is not None:
        return oc_map[cluster]

    oc_map[cluster] = False
    at = cluster_info.get('automationToken')
    if at is None:
        return oc_map[cluster]

    token = vault_client.read(at['path'], at['field'])
    jh = cluster_info.get('jumpHost')
    oc_map[cluster] = OC(cluster_info['serverUrl'], token, jh)

    return oc_map[cluster]


def fetch_provider_resource(path):
    gqlapi = gql.get_api()

    # get resource data
    try:
        resource = gqlapi.get_resource(path)
    except gql.GqlApiError as e:
        raise FetchResourceError(e.message)

    try:
        resource['body'] = anymarkup.parse(
            resource['content'],
            force_types=None
        )
    except anymarkup.AnyMarkupError:
        e_msg = "Could not parse data. Skipping resource: {}"
        raise FetchResourceError(e_msg.format(path))

    openshift_resource = OR(resource['body'])

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise FetchResourceError(e_msg.format(k, path))

    return openshift_resource


def fetch_provider_vault_secret(path, version, name,
                                labels, annotations, type):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": type,
        "metadata": {
            "name": name,
            "annotations": annotations
        },
        "data": {}
    }
    if labels:
        body['metadata']['labels'] = labels

    # get the fields from vault
    raw_data = vault_client.read_all_v2(path, version)
    for k, v in raw_data.items():
        if v == "":
            v = None
        if k.lower().endswith(QONTRACT_BASE64_SUFFIX):
            k = k[:-len(QONTRACT_BASE64_SUFFIX)]
        elif v is not None:
            v = base64.b64encode(v)
        body['data'][k] = v

    openshift_resource = OR(body)

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise FetchVaultSecretError(e_msg.format(k, path))

    return openshift_resource


def fetch_provider_route(path, tls_path, tls_version):
    global _log_lock

    openshift_resource = fetch_provider_resource(path)

    if tls_path is None or tls_version is None:
        return openshift_resource

    # override existing tls fields from vault secret
    openshift_resource.body['spec'].setdefault('tls', {})
    tls = openshift_resource.body['spec']['tls']
    # get tls fields from vault
    raw_data = vault_client.read_all_v2(tls_path, tls_version)
    valid_keys = ['termination', 'insecureEdgeTerminationPolicy',
                  'certificate', 'key',
                  'caCertificate', 'destinationCACertificate']
    for k, v in raw_data.items():
        if k in valid_keys:
            tls[k] = v
            continue

        msg = "Route secret '{}' key '{}' not in valid keys {}".format(
            tls_path, k, valid_keys
        )
        _log_lock.acquire()
        logging.info(msg)
        _log_lock.release()

    return openshift_resource


def fetch_openshift_resource(resource):
    global _log_lock

    provider = resource['provider']
    path = resource['path']
    msg = "Fetching {}: {}".format(provider, path)
    _log_lock.acquire()
    logging.debug(msg)
    _log_lock.release()

    if provider == 'resource':
        openshift_resource = fetch_provider_resource(path)
    elif provider == 'vault-secret':
        version = resource['version']
        rn = resource['name']
        name = path.split('/')[-1] if rn is None else rn
        rl = resource['labels']
        labels = {} if rl is None else json.loads(rl)
        ra = resource['annotations']
        annotations = {} if ra is None else json.loads(ra)
        rt = resource['type']
        type = 'Opaque' if rt is None else rt
        try:
            openshift_resource = \
                fetch_provider_vault_secret(path, version, name,
                                            labels, annotations, type)
        except vault_client.SecretVersionNotFound as e:
            raise FetchVaultSecretError(e)
    elif provider == 'route':
        tls_path = resource['vault_tls_secret_path']
        tls_version = resource['vault_tls_secret_version']
        openshift_resource = fetch_provider_route(path, tls_path, tls_version)
    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(oc, ri, cluster, namespace, resource_type):
    for item in oc.get_items(resource_type, namespace=namespace):
        openshift_resource = OR(item)
        ri.add_current(
            cluster,
            namespace,
            resource_type,
            openshift_resource.name,
            openshift_resource
        )


def fetch_desired_state(ri, cluster, namespace, resource):
    global _log_lock

    try:
        openshift_resource = fetch_openshift_resource(resource)
    except (FetchResourceError,
            FetchVaultSecretError,
            UnknownProviderError) as e:
        ri.register_error()
        msg = "[{}/{}] {}".format(cluster, namespace, e.message)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return

    # add to inventory
    try:
        ri.add_desired(
            cluster,
            namespace,
            openshift_resource.kind,
            openshift_resource.name,
            openshift_resource
        )
    except KeyError:
        # This is failing because in the managed_type loop (where the
        # `initialize_resource_type` method was called), this specific
        # combination was not initialized, meaning that it shouldn't be
        # managed. But someone is trying to add it via app-interface
        ri.register_error()
        msg = "[{}/{}] unknown kind: {}.".format(
            cluster, namespace, openshift_resource.kind)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return
    except ResourceKeyExistsError:
        # This is failing because an attempt to add
        # a desired resource with the same name and
        # the same type was already added previously
        ri.register_error()
        msg = (
            "[{}/{}] desired item already exists: {}/{}."
        ).format(cluster, namespace, openshift_resource.kind,
                 openshift_resource.name)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return


def fetch_states(spec, ri):
    if spec.type == "current":
        fetch_current_state(spec.oc, ri, spec.cluster,
                            spec.namespace, spec.resource)
    if spec.type == "desired":
        fetch_desired_state(ri, spec.cluster, spec.namespace, spec.resource)


def init_specs_to_fetch(ri, oc_map, namespaces_query,
                        override_managed_types=None,
                        managed_types_key='managedResourceTypes'):
    state_specs = []

    for namespace_info in namespaces_query:
        if override_managed_types is None:
            managed_types = namespace_info.get(managed_types_key)
        else:
            managed_types = override_managed_types

        if not managed_types:
            continue

        cluster_info = namespace_info['cluster']
        cluster = cluster_info['name']
        namespace = namespace_info['name']

        oc = obtain_oc_client(oc_map, cluster_info)
        if oc is False:
            ri.register_error()
            msg = (
                "[{}/{}] cluster has no automationToken."
            ).format(cluster, namespace)
            logging.error(msg)
            continue

        # Initialize current state specs
        for resource_type in managed_types:
            ri.initialize_resource_type(cluster, namespace, resource_type)
            c_spec = StateSpec("current", oc, cluster, namespace,
                               resource_type)
            state_specs.append(c_spec)

        # Initialize desired state specs
        openshift_resources = namespace_info.get('openshiftResources') or []
        for openshift_resource in openshift_resources:
            d_spec = StateSpec("desired", None, cluster, namespace,
                               openshift_resource)
            state_specs.append(d_spec)

    return state_specs


def fetch_data(namespaces_query, thread_pool_size):
    ri = ResourceInventory()
    oc_map = {}

    state_specs = init_specs_to_fetch(ri, oc_map, namespaces_query)

    pool = ThreadPool(thread_pool_size)

    fetch_states_partial = partial(fetch_states, ri=ri)
    pool.map(fetch_states_partial, state_specs)

    return oc_map, ri


def apply(dry_run, oc_map, cluster, namespace, resource_type, resource):
    logging.info(['apply', cluster, namespace, resource_type, resource.name])

    if not dry_run:
        annotated = resource.annotate()
        oc_map[cluster].apply(namespace, annotated.toJSON())


def delete(dry_run, oc_map, cluster, namespace, resource_type, name):
    logging.info(['delete', cluster, namespace, resource_type, name])

    if not dry_run:
        oc_map[cluster].delete(namespace, resource_type, name)


def realize_data(dry_run, oc_map, ri):
    for cluster, namespace, resource_type, data in ri:
        # desired items
        for name, d_item in data['desired'].items():
            c_item = data['current'].get(name)

            if c_item is not None:
                # don't apply if it doesn't have annotations
                if not c_item.has_qontract_annotations():
                    ri.register_error()
                    msg = (
                        "[{}/{}] resource '{}/{}' present "
                        "w/o annotations, skipping."
                    ).format(cluster, namespace, resource_type, name)
                    logging.error(msg)
                    continue

                # don't apply if sha256sum hashes match
                if c_item.sha256sum() == d_item.sha256sum():
                    if c_item.has_valid_sha256sum():
                        msg = (
                            "[{}/{}] resource '{}/{}' present "
                            "and hashes match, skipping."
                        ).format(cluster, namespace, resource_type, name)
                        logging.debug(msg)
                        continue
                    else:
                        msg = (
                            "[{}/{}] resource '{}/{}' present "
                            "and has stale sha256sum due to manual changes."
                        ).format(cluster, namespace, resource_type, name)
                        logging.info(msg)

                logging.debug("CURRENT: " +
                              OR.serialize(OR.canonicalize(c_item.body)))
                logging.debug("DESIRED: " +
                              OR.serialize(OR.canonicalize(d_item.body)))
            else:
                logging.debug("CURRENT: None")

            try:
                apply(dry_run, oc_map, cluster, namespace,
                      resource_type, d_item)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, e.message)
                logging.error(msg)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)
            if d_item is not None:
                continue

            if not c_item.has_qontract_annotations():
                continue

            try:
                delete(dry_run, oc_map, cluster, namespace,
                       resource_type, name)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, e.message)
                logging.error(msg)


def cleanup(oc_map):
    for oc in oc_map.values():
        oc.cleanup()


def run(dry_run=False, thread_pool_size=10):
    gqlapi = gql.get_api()

    namespaces_query = gqlapi.query(NAMESPACES_QUERY)['namespaces']

    oc_map, ri = fetch_data(namespaces_query, thread_pool_size)
    try:
        realize_data(dry_run, oc_map, ri)
    finally:
        cleanup(oc_map)

    if ri.has_error_registered():
        sys.exit(1)
