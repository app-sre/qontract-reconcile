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

"""
+-----------------------+--------------------+-------------+
|   Current \ Desired   |      Present       | Not Present |
+=======================+====================+=============+
| Present               | Apply if sha256sum | Delete      |
| (with annotations)    | is different       |             |
+-----------------------+--------------------+-------------+
| Present               | Skip (exit 1)      | Skip        |
| (without annotations) |                    |             |
+-----------------------+--------------------+-------------+
| Not Present           | Apply              | Skip        |
+-----------------------+--------------------+-------------+
"""

NAMESPACES_QUERY = """
{
  namespaces {
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
      }
    }
    cluster {
      name
      serverUrl
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
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 1, 1)
QONTRACT_BASE64_SUFFIX = '_qb64'


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + msg
        )


class FetchVaultSecretError(Exception):
    def __init__(self, msg):
        super(FetchVaultSecretError, self).__init__(
            "error fetching vault secret: " + msg
        )


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + msg
        )


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


def obtain_oc_client(oc_map, cluster_info):
    cluster = cluster_info['name']
    if oc_map.get(cluster) is None:
        oc_map[cluster] = False

        at = cluster_info.get('automationToken')
        if at is not None:
            token = vault_client.read(at['path'], at['field'])
            oc_map[cluster] = OC(cluster_info['serverUrl'], token)

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


def fetch_provider_vault_secret(path, version, name, labels, annotations):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
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


def fetch_openshift_resource(resource):
    provider = resource['provider']
    path = resource['path']

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
        openshift_resource = fetch_provider_vault_secret(path, version, name,
                                                         labels, annotations)
    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(oc, ri, cluster, namespace, managed_types):
    for resource_type in managed_types:
        # Initialize cluster/namespace/resource_type in Inventories
        ri.initialize_resource_type(cluster, namespace, resource_type)

        # Fetch current resources
        for item in oc.get_items(resource_type, namespace=namespace):
            openshift_resource = OR(item)
            ri.add_current(
                cluster,
                namespace,
                resource_type,
                openshift_resource.name,
                openshift_resource
            )


def fetch_desired_state(ri, cluster, namespace, openshift_resources):
    for resource in openshift_resources:
        try:
            openshift_resource = fetch_openshift_resource(resource)
        except (FetchResourceError,
                FetchVaultSecretError,
                UnknownProviderError) as e:
            ri.register_error()
            msg = "[{}/{}] {}".format(cluster, namespace, e.message)
            logging.error(msg)
            continue

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
            logging.error(msg)
            continue
        except ResourceKeyExistsError:
            # This is failing because an attempt to add
            # a desired resource with the same name and
            # the same type was already added previously
            ri.register_error()
            msg = (
                "[{}/{}] desired item already exists: {}/{}."
            ).format(cluster, namespace, openshift_resource.kind,
                     openshift_resource.name)
            logging.error(msg)
            continue


def fetch_data(namespaces_query):
    ri = ResourceInventory()
    oc_map = {}

    for namespace_info in namespaces_query:
        # Skip if namespace has no managedResourceTypes
        managed_types = namespace_info.get('managedResourceTypes')
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

        fetch_current_state(oc, ri, cluster, namespace, managed_types)
        openshift_resources = namespace_info.get('openshiftResources') or []
        fetch_desired_state(ri, cluster, namespace, openshift_resources)

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
                    msg = (
                        "[{}/{}] resource '{}/{}' present "
                        "and hashes match, skipping."
                    ).format(cluster, namespace, resource_type, name)
                    logging.debug(msg)
                    continue

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


def run(dry_run=False):
    gqlapi = gql.get_api()

    namespaces_query = gqlapi.query(NAMESPACES_QUERY)['namespaces']

    oc_map, ri = fetch_data(namespaces_query)
    realize_data(dry_run, oc_map, ri)

    if ri.has_error_registered():
        sys.exit(1)
