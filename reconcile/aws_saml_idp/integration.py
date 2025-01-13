import logging
import sys
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    TypedDict,
)

import requests
from pydantic import BaseModel, HttpUrl

from reconcile.gql_definitions.aws_saml_idp.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.aws_saml_idp.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript_aws_client import TerrascriptClient
from reconcile.utils.unleash.client import get_feature_toggle_state

QONTRACT_INTEGRATION = "aws-saml-idp"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class AwsSamlIdpIntegrationParams(PydanticRunParams):
    thread_pool_size: int = 10
    print_to_file: str | None = None
    enable_deletion: bool = False
    # integration specific parameters
    saml_idp_name: str
    saml_metadata_url: HttpUrl
    account_name: str | None = None
    # extended early exit parameters
    enable_extended_early_exit: bool = False
    extended_early_exit_cache_ttl_seconds: int = 3600
    log_cached_log_output: bool = False


class SamlIdpConfig(BaseModel):
    account_name: str
    name: str
    metadata: str


class RunnerParams(TypedDict):
    tf: TerraformClient
    dry_run: bool
    enable_deletion: bool


class AwsSamlIdpIntegration(QontractReconcileIntegration[AwsSamlIdpIntegrationParams]):
    """Manage the SAML IDP config for all AWS accounts."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query
        return {
            "accounts": [c.dict() for c in self.get_aws_accounts(query_func)],
        }

    def get_aws_accounts(
        self, query_func: Callable, account_name: str | None = None
    ) -> list[AWSAccountV1]:
        """Get all AWS accounts."""
        data = aws_accounts_query(query_func)
        return [
            account
            for account in data.accounts or []
            if integration_is_enabled(self.name, account)
            and (not account_name or account.name == account_name)
        ]

    def build_saml_idp_config(
        self,
        aws_accounts: Iterable[AWSAccountV1],
        saml_idp_name: str,
        saml_metadata: str,
    ) -> list[SamlIdpConfig]:
        """Build the desired state."""
        return [
            SamlIdpConfig(
                account_name=account.name, name=saml_idp_name, metadata=saml_metadata
            )
            for account in aws_accounts
            if account.sso
        ]

    def get_saml_metadata(self, saml_metadata_url: str) -> str:
        """Get the SAML metadata from the given URL."""
        response = requests.get(saml_metadata_url)
        response.raise_for_status()
        return response.text

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        aws_accounts = self.get_aws_accounts(
            gql_api.query, account_name=self.params.account_name
        )
        aws_accounts_dict = [account.dict(by_alias=True) for account in aws_accounts]

        ts = TerrascriptClient(
            self.name.replace("-", "_"),
            "",
            self.params.thread_pool_size,
            aws_accounts_dict,
            secret_reader=self.secret_reader,
        )

        for saml_idp_config in self.build_saml_idp_config(
            aws_accounts,
            saml_idp_name=self.params.saml_idp_name,
            saml_metadata=self.get_saml_metadata(self.params.saml_metadata_url),
        ):
            ts.populate_saml_idp(
                account_name=saml_idp_config.account_name,
                name=saml_idp_config.name,
                metadata=saml_idp_config.metadata,
            )
        working_dirs = ts.dump(print_to_file=self.params.print_to_file)

        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)

        aws_api = AWSApi(
            1, aws_accounts_dict, secret_reader=self.secret_reader, init_users=False
        )
        tf = TerraformClient(
            self.name,
            QONTRACT_INTEGRATION_VERSION,
            "",
            aws_accounts_dict,
            working_dirs,
            self.params.thread_pool_size,
            aws_api,
        )
        if defer:
            defer(tf.cleanup)

        runner_params: RunnerParams = {
            "tf": tf,
            "dry_run": dry_run,
            "enable_deletion": self.params.enable_deletion,
        }

        if self.params.enable_extended_early_exit and get_feature_toggle_state(
            f"{QONTRACT_INTEGRATION}-extended-early-exit", default=True
        ):
            extended_early_exit_run(
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                dry_run=dry_run,
                cache_source=ts.terraform_configurations(),
                shard=self.params.account_name or "",
                ttl_seconds=self.params.extended_early_exit_cache_ttl_seconds,
                logger=logging.getLogger(),
                runner=runner,
                runner_params=runner_params,
                log_cached_log_output=self.params.log_cached_log_output,
            )
        else:
            runner(**runner_params)


def runner(
    dry_run: bool, tf: TerraformClient, enable_deletion: bool
) -> ExtendedEarlyExitRunnerResult:
    _, err = tf.plan(enable_deletion)
    if err:
        raise RuntimeError("Terraform plan has errors")

    if dry_run:
        return ExtendedEarlyExitRunnerResult(payload={}, applied_count=0)

    if err := tf.apply():
        raise RuntimeError("Terraform apply has errors")

    return ExtendedEarlyExitRunnerResult(payload={}, applied_count=tf.apply_count)
