import logging
import sys

import anymarkup
import base64

import reconcile.gql as gql
import utils.vault_client as vault_client
from utils.openshift_resource import OpenshiftResource
from utils.oc import OC, StatusCodeError

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
        name
        path
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
QONTRACT_INTEGRATION_VERSION = '1'


class FetchResourceError(Exception):
    pass


class FetchVaultSecretError(Exception):
    pass


class ResourceKeyExistsError(Exception):
    pass


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


class ResourceInventory(object):
    def __init__(self):
        self._clusters = {}

    def initialize_resource_type(self, cluster, namespace, resource_type):
        self._clusters.setdefault(cluster, {})
        self._clusters[cluster].setdefault(namespace, {})
        self._clusters[cluster][namespace].setdefault(resource_type, {
            'current': {},
            'desired': {}
        })

    def add_desired(self, cluster, namespace, resource_type, name, value):
        desired = self._clusters[cluster][namespace][resource_type]['desired']
        if name in desired:
            raise ResourceKeyExistsError(name)
        desired[name] = value

    def add_current(self, cluster, namespace, resource_type, name, value):
        current = self._clusters[cluster][namespace][resource_type]['current']
        current[name] = value

    def __iter__(self):
        for cluster in self._clusters.keys():
            for namespace in self._clusters[cluster].keys():
                for resource_type in self._clusters[cluster][namespace].keys():
                    data = self._clusters[cluster][namespace][resource_type]
                    yield (cluster, namespace, resource_type, data)


_error_occured = False
_error_prefix = ''


def error(msg):
    global _error_occured
    global _error_prefix

    _error_occured = True
    logging.error(_error_prefix + msg)


def update_error_prefix(namespace, cluster):
    global _error_prefix

    err_tpl = "Error fetching data. cluster: {}, namespace: {}. Details: "
    _error_prefix = err_tpl.format(cluster, namespace)


def has_error_occured():
    global _error_occured

    return _error_occured


def obtain_oc_client(oc_map, cluster_info):
    cluster = cluster_info['name']
    if oc_map.get(cluster) is None:
        at = cluster_info.get('automationToken')

        # Skip if cluster has no automationToken
        if at is None:
            error("Cluster has no automationToken.")
            oc_map[cluster] = False
        else:
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


def fetch_provider_vault_secret(name, path):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name
        },
        "data": {}
    }

    # get the fields from vault
    raw_data = vault_client.read_all(path)
    for k, v in raw_data.items():
        body['data'][k] = base64.b64encode(v)

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
        try:
            openshift_resource = fetch_provider_resource(path)
        except FetchResourceError as e:
            error(str(e.message))
            return None
    elif provider == 'vault-secret':
        name = resource['name']
        try:
            openshift_resource = fetch_provider_vault_secret(
                name, path)
        except FetchVaultSecretError as e:
            error(str(e.message))
            return None
    else:
        error('Unknown provider: {}'.format(provider))
        return None

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
    return ri


def fetch_desired_state(ri, cluster, namespace, openshift_resources):
    for resource in openshift_resources:
        openshift_resource = fetch_openshift_resource(resource)
        if openshift_resource is None:
            error('Invalid None type for openshift_resource.')
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
            error("Unknown kind: {}.".format(openshift_resource.kind))
            continue
        except ResourceKeyExistsError:
            # This is failing because an attempt to add
            # a desired resource with the same name and
            # the same type was already added previously
            error("Desired item already exists: {}/{}.".format(
                openshift_resource.kind, openshift_resource.name))
            continue
    return ri


def fetch_data(namespaces_query):
    ri = ResourceInventory()
    oc_map = {}

    for namespace_info in namespaces_query:
        # Skip if namespace has no managedResourceTypes
        managed_types = namespace_info.get('managedResourceTypes')
        if not managed_types:
            continue

        cluster_info = namespace_info['cluster']
        oc = obtain_oc_client(oc_map, cluster_info)
        if oc is False:
            continue

        namespace = namespace_info['name']
        cluster = cluster_info['name']
        update_error_prefix(cluster, namespace)

        fetch_current_state(oc, ri, cluster, namespace, managed_types)
        openshift_resources = namespace_info.get('openshiftResources') or []
        fetch_desired_state(ri, cluster, namespace, openshift_resources)

    return oc_map, ri


def apply(dry_run, oc_map, cluster, namespace, resource_type, resource):
    if not dry_run:
        annotated = resource.annotate()

        try:
            oc_map[cluster].apply(namespace, annotated.toJSON())
        except StatusCodeError as e:
            logging.error(e.message)


def delete(dry_run, oc_map, cluster, namespace, resource_type, name):
    logging.info(['delete', cluster, namespace, resource_type, name])

    if not dry_run:
        oc_map[cluster].delete(namespace, resource_type, name)


def run(dry_run=False):
    gqlapi = gql.get_api()

    namespaces_query = gqlapi.query(NAMESPACES_QUERY)['namespaces']

    oc_map, ri = fetch_data(namespaces_query)

    for cluster, namespace, resource_type, data in ri:
        # desired items
        for name, d_item in data['desired'].items():
            c_item = data['current'].get(name)

            if c_item is not None:
                if c_item.has_qontract_annotations():
                    if c_item.sha256sum() == d_item.sha256sum():
                        # don't apply if sha256sum hashes match
                        logging.debug((
                            "Skipping resource '{}/{}' in '{}/{}'. "
                            "Hashes match."
                        ).format(
                            resource_type, name, cluster, namespace))
                        continue
                else:
                    # don't apply if it doesn't have annotations
                    e_msg = (
                        "Skipping resource '{}/{}' in '{}/{}'. "
                        "Present w/o annotations."
                    ).format(resource_type, name, cluster, namespace)
                    error(e_msg)
                    continue

            logging.info(['apply', cluster, namespace,
                          resource_type, d_item.name])

            if c_item is None:
                logging.debug("CURRENT: None")
            else:
                logging.debug("CURRENT: " +
                              OR.serialize(OR.canonicalize(c_item.body)))

            logging.debug("DESIRED: " +
                          OR.serialize(OR.canonicalize(d_item.body)))

            apply(dry_run, oc_map, cluster, namespace, resource_type, d_item)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)

            if c_item.has_qontract_annotations() and d_item is None:
                delete(dry_run, oc_map, cluster, namespace, resource_type,
                       name)

    if has_error_occured():
        sys.exit(1)
