import logging
import sys
from typing import Iterable, Optional

from reconcile.gql_definitions.terraform_vpc_resources.vpc_resources_aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.terraform_vpc_resources.vpc_resources_aws_accounts import (
    query as query_aws_accounts,
)
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
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

    def _filter_accounts(self, data: Iterable[AWSAccountV1]) -> Iterable[AWSAccountV1]:
        """Return a list of accounts that have the 'terraform-vpc-resources' terraform state."""
        return [
            account
            for account in data
            if account.terraform_state
            and account.terraform_state.integrations
            and any(
                integration.integration == self.name
                for integration in account.terraform_state.integrations
            )
        ]

    def _filter_vpcs_per_account(
        self, account: AWSAccountV1, vpcs: Iterable[AWSVPC]
    ) -> Iterable[AWSVPC]:
        return [
            vpc
            for vpc in vpcs
            if (
                vpc.account.name == account.name
            )
        ]

    def run(self, dry_run: bool) -> None:
        account_name = self.params.account_name

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        query_func = gql.get_api().query

        data = query_aws_accounts(query_func=query_func).accounts

        if data:
            accounts = self._filter_accounts(data)
            if account_name:
                accounts = [
                    account for account in accounts if account.name == account_name
                ]
            if not accounts:
                logging.warning(
                    "No AWS accounts with 'terraform-vpc-resources' state found, nothing to do."
                )
                sys.exit(ExitCodes.SUCCESS)
        else:
            logging.warning("No AWS accounts found, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)

        vpcs = get_aws_vpcs(gql_api=gql.get_api())
        if not vpcs:
            logging.warning("No AWS VPCs found, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)

        accounts_untyped: list[dict] = [acc.dict(by_alias=True) for acc in accounts]
        ts_client = TerrascriptClient(
            integration=QONTRACT_INTEGRATION,
            integration_prefix=QONTRACT_TF_PREFIX,
            thread_pool_size=1,
            accounts=accounts_untyped,
            secret_reader=secret_reader,
        )

        working_dirs = ts_client.dump(print_to_file=self.params.print_to_file)

        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)
    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            shard_arg_name="account_name",
            shard_path_selectors={
                "accounts[*].name",
            },
            sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
        )
