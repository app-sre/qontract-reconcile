import sys
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
)

from pydantic import validator

from reconcile.gql_definitions.aws_saml_roles.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.gql_definitions.aws_saml_roles.aws_groups import (
    AWSGroupV1,
)
from reconcile.gql_definitions.aws_saml_roles.aws_groups import (
    query as aws_groups_query,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript_aws_client import TerrascriptClient

QONTRACT_INTEGRATION = "aws-saml-roles"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class AwsSamlRolesIntegrationParams(PydanticRunParams):
    thread_pool_size: int = 10
    print_to_file: str | None = None
    enable_deletion: bool = False
    # integration specific parameters
    saml_idp_name: str
    max_session_duration_hours: int = 1
    account_name: str | None = None

    @validator("max_session_duration_hours")
    def max_session_duration_range(cls, v: str | int) -> int:
        if 1 <= int(v) <= 12:
            return int(v)
        raise ValueError("max_session_duration_hours must be between 1 and 12 hours")


class AwsSamlRolesIntegration(
    QontractReconcileIntegration[AwsSamlRolesIntegrationParams]
):
    """Manage the SAML IAM roles for all AWS accounts with SSO enabled"""

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
            "aws_groups": [c.dict() for c in self.get_aws_groups(query_func)],
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

    def get_aws_groups(
        self, query_func: Callable, account_name: str | None = None
    ) -> list[AWSGroupV1]:
        """Get all AWS groups with SSO enabled."""
        data = aws_groups_query(query_func)
        return [
            group
            for group in data.aws_groups or []
            if integration_is_enabled(self.name, group.account)
            and (not account_name or group.account.name == account_name)
            and group.account.sso
            and group.roles
            and group.policies
            and any(role.users for role in group.roles)
        ]

    def populate_saml_iam_roles(
        self, ts: TerrascriptClient, aws_groups: Iterable[AWSGroupV1]
    ) -> None:
        """Populate the SAML IAM roles."""
        for group in aws_groups:
            # aws groups without policies are filtered out by the query
            # duplicated policies aren't allowed in the same role
            policies = group.policies or []
            if len(policies) != len(set(policies)):
                raise ValueError(
                    f"Group {group.name} has duplicated policies: {policies}"
                )

            ts.populate_saml_iam_role(
                account=group.account.name,
                name=group.name,
                saml_provider_name=self.params.saml_idp_name,
                policies=policies,
                max_session_duration_hours=self.params.max_session_duration_hours,
            )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        aws_accounts = self.get_aws_accounts(
            gql_api.query, account_name=self.params.account_name
        )
        aws_accounts_dict = [account.dict(by_alias=True) for account in aws_accounts]
        aws_groups = self.get_aws_groups(
            gql_api.query, account_name=self.params.account_name
        )

        ts = TerrascriptClient(
            self.name.replace("-", "_"),
            "",
            self.params.thread_pool_size,
            aws_accounts_dict,
            secret_reader=self.secret_reader,
        )
        self.populate_saml_iam_roles(ts, aws_groups)
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

        _, err = tf.plan(self.params.enable_deletion)
        if err:
            sys.exit(ExitCodes.ERROR)

        if dry_run:
            return

        err = tf.apply()
        if err:
            sys.exit(ExitCodes.ERROR)
