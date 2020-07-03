import sys
import logging
import semver

import anymarkup
import reconcile.queries as queries
import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

from utils.openshift_resource import OpenshiftResource as OR
from utils.openshift_resource import ConstructResourceError
from utils.defer import defer

from utils.openshift_acme import (ACME_DEPLOYMENT,
                                  ACME_ROLE,
                                  ACME_ROLEBINDING,
                                  ACME_SERVICEACCOUNT)


QONTRACT_INTEGRATION = 'openshift-acme'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 2, 0)


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
        acme = namespace.get("openshiftAcme", {})

        # Get the linked acme schema settings
        acme_config = acme.get("config", {})
        image = acme_config.get("image")
        acme_overrides = acme_config.get("overrides", {})
        default_name = 'openshift-acme'
        default_rbac_api_version = 'authorization.openshift.io/v1'
        deployment_name = \
            acme_overrides.get('deploymentName') or default_name
        serviceaccount_name = \
            acme_overrides.get('serviceaccountName') or default_name
        role_name = \
            acme_overrides.get('roleName') or default_name
        rolebinding_name = \
            acme_overrides.get('roleName') or default_name
        rbac_api_version = \
            acme_overrides.get('rbacApiVersion') or default_rbac_api_version

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
                'role_name': role_name,
                'role_api_version': rbac_api_version
            })
        )
        namespace["resources"].append(
            process_template(ACME_ROLEBINDING, {
                'role_name': role_name,
                'rolebinding_name': rolebinding_name,
                'rolebinding_api_version': rbac_api_version,
                'serviceaccount_name': serviceaccount_name,
                'namespace_name': namespace_name
            })
        )

        # If acme-account Secret is defined, add it to the namespace
        acme_account_secret = acme.get("accountSecret", {})
        if acme_account_secret:
            namespace["resources"].append(
                orb.fetch_provider_vault_secret(
                    acme_account_secret['path'],
                    acme_account_secret['version'],
                    'acme-account',
                    labels={'kubernetes.io/acme.type': 'account'},
                    annotations={},
                    type='Opaque',
                    integration=QONTRACT_INTEGRATION,
                    integration_version=QONTRACT_INTEGRATION_VERSION
                )
            )

    return namespaces


def add_desired_state(namespaces, ri, oc_map):
    for namespace in namespaces:
        cluster = namespace['cluster']['name']
        if not oc_map.get(cluster):
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
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):

    try:
        namespaces = [
            namespace_info for namespace_info
            in queries.get_namespaces()
            if namespace_info.get('openshiftAcme')
            ]

        namespaces = construct_resources(namespaces)

        ri, oc_map = ob.fetch_current_state(
            namespaces=namespaces,
            thread_pool_size=thread_pool_size,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            override_managed_types=[
                'Deployment',
                'Role',
                'RoleBinding',
                'ServiceAccount',
                'Secret'],
            internal=internal,
            use_jump_host=use_jump_host)
        add_desired_state(namespaces, ri, oc_map)

        defer(lambda: oc_map.cleanup())

        ob.realize_data(dry_run, oc_map, ri)

        if ri.has_error_registered():
            sys.exit(1)

    except Exception as e:
        msg = 'There was problem running openshift acme reconcile.'
        msg += ' Exception: {}'
        msg = msg.format(str(e))
        logging.error(msg)
        sys.exit(1)
