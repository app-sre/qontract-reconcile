import logging
import sys
from typing import (
    Callable,
    Optional,
)

from reconcile.jenkins_job_builder import init_jjb
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.repos import get_repos
from reconcile.typed_queries.saas_files import (
    get_saas_files,
    get_saasherder_settings,
)
from reconcile.utils.defer import defer
from reconcile.utils.jjb_client import JJB
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "saas-file-validator"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@defer
def run(dry_run: bool, defer: Optional[Callable] = None) -> None:
    vault_settings = get_app_interface_vault_settings()
    saasherder_settings = get_saasherder_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    saas_files = get_saas_files()
    if not saas_files:
        logging.error("no saas files found")
        raise RuntimeError("no saas files found")

    saasherder = SaasHerder(
        saas_files=saas_files,
        thread_pool_size=1,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        secret_reader=secret_reader,
        hash_length=saasherder_settings.hash_length,
        repo_url=saasherder_settings.repo_url,
        validate=True,
    )
    if defer:
        defer(saasherder.cleanup)
    app_int_repos = get_repos()
    missing_repos = [r for r in saasherder.repo_urls if r not in app_int_repos]
    for r in missing_repos:
        logging.error(f"repo is missing from codeComponents: {r}")
    jjb: JJB = init_jjb(secret_reader)
    saasherder.validate_upstream_jobs(jjb)
    if not saasherder.valid or missing_repos:
        sys.exit(ExitCodes.ERROR)
