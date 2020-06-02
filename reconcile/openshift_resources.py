import semver

import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

QONTRACT_INTEGRATION = 'openshift_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 9, 3)


def run(dry_run=False, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    providers = ['resource', 'resource-template']
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    ri = orb.run(dry_run=dry_run,
                 thread_pool_size=thread_pool_size,
                 internal=internal,
                 use_jump_host=use_jump_host,
                 providers=providers)

    # check for unused resources types
    # listed under `managedResourceTypes`
    # only applicable for openshift-resources
    ob.check_unused_resource_types(ri)
