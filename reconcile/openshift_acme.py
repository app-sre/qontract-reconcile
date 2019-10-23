import semver

import anymarkup
import utils.gql as gql
import reconcile.openshift_base as ob

from utils.openshift_resource import OpenshiftResource as OR
from utils.openshift_resource import ConstructResourceError
from utils.defer import defer

from utils.openshift_acme import NAMESPACES_QUERY
from utils.openshift_acme import (ACME_DEPLOYMENT,
                                  ACME_ROLE,
                                  ACME_ROLEBINDING,
                                  ACME_SERVICEACCOUNT)


QONTRACT_INTEGRATION = 'openshift-acme'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def process_template(template, values):
    try:
        manifest = template % values
        return OR(anymarkup.parse(manifest, force_types=None),
                  QONTRACT_INTEGRATION,
                  QONTRACT_INTEGRATION_VERSION)
    except KeyError as e:
        raise ConstructResourceError(
            'could not process template: missing key {}'.format(e))


def construct_resources(namespaces):
    for namespace in namespaces:
        namespace_name = namespace["name"]

        # Get the linked acme schema settings
        acme = namespace.get("openshiftAcme", {})
        image = acme.get("image")
        acme_overrides = acme.get("overrides", {})
        deployment_name = acme_overrides.get('deploymentName',
                                             'openshift-acme')
        serviceaccount_name = acme_overrides.get('serviceaccountName',
                                                 'openshift-acme')
        role_name = acme_overrides.get('roleName',
                                       'openshift-acme')
        rolebinding_name = acme_overrides.get('roleName',
                                              'openshift-acme')

        # Create the resources and append them to the namespace
        namespace["resources"] = []
        namespace["resources"].append(
            process_template(ACME_DEPLOYMENT, {
                'deployment_name': deployment_name,
                'image': image,
                'serviceaccount_name': serviceaccount_name
            })
        )
        namespace["resources"].append(
            process_template(ACME_SERVICEACCOUNT, {
                'serviceaccount_name': serviceaccount_name
            })
        )
        namespace["resources"].append(
            process_template(ACME_ROLE, {
                'role_name': role_name
            })
        )
        namespace["resources"].append(
            process_template(ACME_ROLEBINDING, {
                'role_name': role_name,
                'rolebinding_name': rolebinding_name,
                'serviceaccount_name': serviceaccount_name,
                'namespace_name': namespace_name
            })
        )

    return namespaces


def add_desired_state(namespaces, ri):
    for namespace in namespaces:
        for resource in namespace["resources"]:
            ri.add_desired(
                namespace['cluster']['name'],
                namespace['name'],
                resource.kind,
                resource.name,
                resource
            )


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    gqlapi = gql.get_api()
    namespaces = [namespace_info for namespace_info
                  in gqlapi.query(NAMESPACES_QUERY)['namespaces']
                  if namespace_info.get('openshiftAcme')]

    namespaces = construct_resources(namespaces)

    ri, oc_map = \
        ob.fetch_current_state(namespaces, thread_pool_size,
                               QONTRACT_INTEGRATION,
                               QONTRACT_INTEGRATION_VERSION,
                               override_managed_types=[
                                   'Deployment',
                                   'Role',
                                   'RoleBinding',
                                   'ServiceAccount'])
    add_desired_state(namespaces, ri)

    defer(lambda: oc_map.cleanup())

    ob.realize_data(dry_run, oc_map, ri)
