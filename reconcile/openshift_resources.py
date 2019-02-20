import logging
import sys

import anymarkup

import reconcile.gql as gql
import utils.vault_client as vault_client
import utils.openshift_resource
from utils.oc import OC

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

QONTRACT_INTEGRATION = 'openshift_resource'
QONTRACT_INTEGRATION_VERSION = '1'


class FetchResourceError(Exception):
    pass


class OpenshiftResource(utils.openshift_resource.OpenshiftResource):
    def __init__(self, body):
        super(OpenshiftResource, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


class ResourceInventory(object):
    def __init__(self):
        self._dict = {}

    def initialize_resource_type(self, cluster, namespace, resource_type):
        self._dict.setdefault(cluster, {})
        self._dict[cluster].setdefault(namespace, {})
        self._dict[cluster][namespace].setdefault(resource_type, {
            'current': {},
            'desired': {}
        })

    def add_desired(self, cluster, namespace, resource_type, name, value):
        desired = self._dict[cluster][namespace][resource_type]['desired']
        desired[name] = value

    def add_current(self, cluster, namespace, resource_type, name, value):
        current = self._dict[cluster][namespace][resource_type]['current']
        current[name] = value

    def iterate(self):
        for cluster in self._dict.keys():
            for namespace in self._dict[cluster].keys():
                for resource_type in self._dict[cluster][namespace].keys():
                    data = self._dict[cluster][namespace][resource_type]
                    yield (cluster, namespace, resource_type, data)


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

    openshift_resource = OpenshiftResource(resource['body'])

    # verify valid k8s object
    try:
        openshift_resource.run_assert()
    except TypeError:
        e_msg = "Invalid data (TypeError). Skipping resource: {}"
        raise FetchResourceError(e_msg.format(path))
    except KeyError:
        e_msg = "Invalid data (KeyError). Skipping resource: {}"
        raise FetchResourceError(e_msg.format(path))

    return openshift_resource


def fetch_data(namespaces_query):
    ri = ResourceInventory()
    oc_map = {}
    errors = []

    for namespace_info in namespaces_query:
        namespace = namespace_info['name']
        cluster_info = namespace_info['cluster']
        cluster = cluster_info['name']

        # Skip if namespace has no managedResourceTypes
        managed_types = namespace_info.get('managedResourceTypes')
        if not managed_types:
            continue

        # useful errors
        def error(msg):
            err_msg = (
                "Error fetching data. cluster: {}, namespace: {}. "
            ).format(cluster, namespace) + msg

            logging.error(err_msg)
            errors.append(err_msg)

        # Obtain `oc` client
        if oc_map.get(cluster) is None:
            at = cluster_info.get('automationToken')

            # Skip if cluster has no automationToken
            if at is None:
                error("Cluster {} has no automationToken.")
                oc_map[cluster] = False
            else:
                token = vault_client.read(at['path'], at['field'])
                oc_map[cluster] = OC(cluster_info['serverUrl'], token)

        oc = oc_map[cluster]

        if oc is False:
            continue

        # Current State
        for resource_type in managed_types:
            # Initialize cluster/namespace/resource_type in Inventories
            ri.initialize_resource_type(cluster, namespace, resource_type)

            # Fetch current resources
            for item in oc.get_items(resource_type, namespace=namespace):
                openshift_resource = OpenshiftResource(item)
                ri.add_current(
                    cluster,
                    namespace,
                    resource_type,
                    openshift_resource.name,
                    openshift_resource
                )

        # Desired State
        openshift_resources = namespace_info.get('openshiftResources') or []
        for resource in openshift_resources:
            openshift_resource = None

            provider = resource['provider']
            if provider == 'resource':
                path = resource['path']
                try:
                    openshift_resource = fetch_provider_resource(path)
                except FetchResourceError as e:
                    error("provider resource. path: {}. ".format(path)
                          + str(e.message))
                    continue
            else:
                error('Unknown provider: {}'.format(provider))
                continue

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
                error("Unknown cluster/namespace/kind: {}/{}/{}.".format(
                    cluster,
                    namespace,
                    openshift_resource.kind,
                ))
                continue

    return oc_map, ri, errors


def apply(dry_run, oc_map, c, n, rt, item):
    logging.info(['apply', c, n, rt, item.name])

    if not dry_run:
        item.annotate()
        body = OpenshiftResource.serialize(item.body)
        oc_map[c].apply(n, body)


def delete(dry_run, oc_map, c, n, rt, name):
    logging.info(['delete', c, n, rt, name])

    if not dry_run:
        oc_map[c].delete(n, rt, name)


def run(dry_run=False):
    gqlapi = gql.get_api()

    namespaces_query = gqlapi.query(NAMESPACES_QUERY)['namespaces']

    oc_map, ri, errors = fetch_data(namespaces_query)

    for c, n, rt, data in ri.iterate():
        # desired items
        for name, d_item in data['desired'].items():
            c_item = data['current'].get(name)

            if c_item is not None:
                if c_item.has_qontract_annotations():
                    if c_item.sha256sum() == d_item.sha256sum():
                        # don't apply if sha256sum hashes match
                        continue
                else:
                    # don't apply if it doesn't have annotations
                    e_msg = (
                        "Skipping resource '{}/{}' in '{}/{}'. "
                        "Present w/o annotations."
                    ).format(rt, name, c, n)
                    logging.info(e_msg)
                    errors.append(e_msg)
                    continue

            apply(dry_run, oc_map, c, n, rt, d_item)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)

            if c_item.has_qontract_annotations() and d_item is None:
                delete(dry_run, oc_map, c, n, rt, name)

    if len(errors) > 0:
        sys.exit(1)
