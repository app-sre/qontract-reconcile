import logging
import sys
from typing import Iterable, Optional

from reconcile.gql_definitions.fragments.aws_vpc_request import (
    AWSAccountV1,
    VPCRequest,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.aws_vpc_requests import get_aws_vpc_requests
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript_aws_client import TerrascriptClient

QONTRACT_INTEGRATION = "terraform_vpc_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrtvr"


class TerraformVpcResourcesParams(PydanticRunParams):
    account_name: Optional[str]
    print_to_file: Optional[str]
    thread_pool_size: int


class TerraformVpcResources(QontractReconcileIntegration[TerraformVpcResourcesParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION.replace("_", "-")

    def _filter_accounts(self, data: Iterable[VPCRequest]) -> list[AWSAccountV1]:
        """Return a list of accounts extracted from the provided VPCRequests."""
        return [vpc.account for vpc in data]

    def run(self, dry_run: bool) -> None:
        account_name = self.params.account_name

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        data = get_aws_vpc_requests(gql_api=gql.get_api())

        if data:
            accounts = self._filter_accounts(data)
            if account_name:
                accounts = [
                    account for account in accounts if account.name == account_name
                ]
                if not accounts:
                    logging.warning(
                        f"The account {account_name} doesn't have any managed vpc. Verify your input"
                    )
                    sys.exit(ExitCodes.ERROR)
        else:
            logging.warning("No VPC requests found, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)

        accounts_untyped: list[dict] = [acc.dict(by_alias=True) for acc in accounts]
        with TerrascriptClient(
            integration=QONTRACT_INTEGRATION,
            integration_prefix=QONTRACT_TF_PREFIX,
            thread_pool_size=1,
            accounts=accounts_untyped,
            secret_reader=secret_reader,
        ) as ts_client:
            ts_client.populate_vpc_requests(data)

        working_dirs = ts_client.dump(print_to_file=self.params.print_to_file)

        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)

        tf_client = TerraformClient(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            integration_prefix=QONTRACT_TF_PREFIX,
            accounts=accounts_untyped,
            working_dirs=working_dirs,
            thread_pool_size=1,
        )

        tf_client.plan(enable_deletion=False)

        if not dry_run:
            tf_client.apply()

    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="account_name",
            shard_path_selectors={
                "accounts[*].name",
            },
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )
