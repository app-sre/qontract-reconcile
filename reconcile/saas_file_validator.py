import sys
import logging

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.jjb_client import JJB

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.saasherder import SaasHerder
from reconcile.jenkins_job_builder import init_jjb

QONTRACT_INTEGRATION = "saas-file-validator"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(dry_run):
    saas_files = queries.get_saas_files()
    settings = queries.get_app_interface_settings()
    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=1,
        gitlab=None,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings,
        validate=True,
    )
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in saasherder.repo_urls if r not in app_int_repos]
    for r in missing_repos:
        logging.error(f"repo is missing from codeComponents: {r}")
    jjb: JJB = init_jjb()
    saasherder.validate_upstream_jobs(jjb)
    if not saasherder.valid or missing_repos:
        sys.exit(ExitCodes.ERROR)
