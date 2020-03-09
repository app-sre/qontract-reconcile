import semver

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform


QONTRACT_INTEGRATION = 'terraform-vpc-peerings'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10):
    print('hello there!')
