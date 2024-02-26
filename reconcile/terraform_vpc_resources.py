import logging
from typing import Optional
from reconcile import queries
from reconcile.utils import aws_api

from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "terraform_vpc_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

def run(dry_run, account_name: Optional[str] = None):
    settings = queries.get_secret_reader_settings()
    accounts = queries.get_aws_accounts(terraform_state=True,)

    awsapi = aws_api.AWSApi(1, accounts, settings=settings, init_users=False)

    logging.info(f"Running {QONTRACT_INTEGRATION} version {QONTRACT_INTEGRATION_VERSION}")
