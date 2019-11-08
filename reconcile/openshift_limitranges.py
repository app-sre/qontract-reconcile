import logging
import semver
import sys

import utils.gql as gql
import reconcile.openshift_base as ob

from utils.openshift_resource import OpenshiftResource as OR
from utils.defer import defer

from reconcile.queries import NAMESPACES_QUERY

QONTRACT_INTEGRATION = 'openshift-limitranges'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)

SUPPORTED_LIMITRANGE_TYPES = (
    'default',
    'defaultRequest',
    'max',
    'maxLimitRequestRatio',
    'min'
)


def construct_resources(namespaces):
    for namespace in namespaces:
        if 'limitRanges' not in namespace:
            logging.warning(
                "limitRanges key not found on namespace %s. Skipping." %
                (namespace['name'])
            )
            continue

        # Get the linked limitRanges schema settings
        limitranges = namespace.get("limitRanges", {})

        body = {
            'apiVersion': 'v1',
            'kind': 'LimitRange',
            'metadata': {
                'name': limitranges['name'],
            },
            'spec': {
                'limits': []
            }
        }

        # Build each limit item ignoring null ones
        speclimit = {}
        for l in limitranges['limits']:
            for ltype in SUPPORTED_LIMITRANGE_TYPES:
                if ltype in l and l[ltype] is not None:
                    speclimit[ltype] = l[ltype]
            body['spec']['limits'].append(speclimit)

        resource = OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)

        # k8s changes an empty array to null/None. we do this here
        # to be consistent
        if len(body['spec']['limits']) == 0:
            body['spec']['limits'] = None

        # Create the resources and append them to the namespace
        namespace["resources"] = [resource]

    return namespaces


def add_desired_state(namespaces, ri):
    for namespace in namespaces:
        if 'resources' not in namespace:
            continue
        for resource in namespace["resources"]:
            ri.add_desired(
                namespace['cluster']['name'],
                namespace['name'],
                resource.kind,
                resource.name,
                resource
            )


@defer
def run(dry_run=False, thread_pool_size=10, take_over=True, defer=None):
    gqlapi = gql.get_api()
    namespaces = [namespace_info for namespace_info
                  in gqlapi.query(NAMESPACES_QUERY)['namespaces']
                  if namespace_info.get('limitRanges')]

    namespaces = construct_resources(namespaces)

    if not namespaces:
        logging.debug("No LimitRanges definition found in app-interface!")
        sys.exit(0)

    ri, oc_map = \
        ob.fetch_current_state(namespaces, thread_pool_size,
                               QONTRACT_INTEGRATION,
                               QONTRACT_INTEGRATION_VERSION,
                               override_managed_types=['LimitRange'])
    defer(lambda: oc_map.cleanup())

    add_desired_state(namespaces, ri)
    ob.realize_data(dry_run, oc_map, ri, enable_deletion=True, take_over=take_over)
