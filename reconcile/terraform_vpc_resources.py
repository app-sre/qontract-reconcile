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
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "terraform_vpc_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class TerraformVpcResourcesParams(PydanticRunParams):
    account_name: Optional[str]


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
                integration.integration == "terraform-vpc-resources"
                for integration in account.terraform_state.integrations
            )
        ]

    def run(self, dry_run: bool):
        account_name = self.params.account_name

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        query_func = gql.get_api().query

        data = query_aws_accounts(query_func=query_func).accounts

        if data:
            accounts = self._filter_accounts(data)
            if not accounts:
                logging.error(
                    "No AWS accounts with 'terraform-vpc-resources' state found, nothing to do."
                )
                sys.exit(ExitCodes.SUCCESS)
        else:
            logging.error("No AWS accounts found, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)
