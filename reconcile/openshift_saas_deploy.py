import os
import semver

import reconcile.queries as queries
import reconcile.openshift_base as ob

from github import Github

from reconcile.github_org import get_config

from utils.gitlab_api import GitLabApi
from utils.saasherder import SaasHerder
from utils.defer import defer


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def init_gh_gl(internal):
    base_url = os.environ.get('GITHUB_API', 'https://api.github.com')
    config = get_config()
    github_config = config['github']
    token = github_config['app-sre']['token']
    gh = Github(token, base_url=base_url)
    gl = None
    if internal:
        instance = queries.get_gitlab_instance()
        settings = queries.get_app_interface_settings()
        gl = GitLabApi(instance, settings=settings)
    return gh, gl


@defer
def run(dry_run=False, thread_pool_size=10, internal=None, defer=None):
    gh, gl = init_gh_gl(internal)
    saas_files = queries.get_saas_files()
    saasherder = SaasHerder(
        saas_files,
        github=gh,
        gitlab=gl,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION)
    ri, oc_map = ob.fetch_current_state(
        namespaces=saasherder.namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        internal=internal)
    defer(lambda: oc_map.cleanup())
    saasherder.populate_desired_state(ri)
    ob.realize_data(dry_run, oc_map, ri,
                    enable_deletion=False)
