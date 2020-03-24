import semver

import reconcile.queries as queries
import reconcile.openshift_base as ob

from utils.gitlab_api import GitLabApi
from utils.saasherder import SaasHerder
from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    aws_accounts = queries.get_aws_accounts()
    gl = GitLabApi(instance, settings=settings)

    saas_files = queries.get_saas_files()
    saasherder = SaasHerder(
        saas_files,
        gitlab=gl,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings)
    ri, oc_map = ob.fetch_current_state(
        namespaces=saasherder.namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION)
    defer(lambda: oc_map.cleanup())
    saasherder.populate_desired_state(ri)
    enable_deletion = False if ri.has_error_registered() else True
    ob.realize_data(dry_run, oc_map, ri,
                    enable_deletion=enable_deletion)
    saasherder.slack_notify(dry_run, aws_accounts, ri)
