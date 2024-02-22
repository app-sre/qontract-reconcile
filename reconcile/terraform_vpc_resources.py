import logging

from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "terraform_vpc_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

def run(dry_run):
    logging.info(f"Running {QONTRACT_INTEGRATION} version {QONTRACT_INTEGRATION_VERSION}")
