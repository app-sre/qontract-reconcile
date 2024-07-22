import json
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

from pydantic import BaseModel, root_validator, validator

from reconcile.gql_definitions.aws_saml_roles.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.gql_definitions.aws_saml_roles.roles import (
    query as roles_query,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.aws_helper import unique_sso_aws_accounts
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
    # extended early exit parameters
    enable_extended_early_exit: bool = False
    extended_early_exit_cache_ttl_seconds: int = 3600
    log_cached_log_output: bool = False

    @validator("max_session_duration_hours")
    def max_session_duration_range(cls, v: str | int) -> int:
        if 1 <= int(v) <= 12:
            return int(v)
        raise ValueError("max_session_duration_hours must be between 1 and 12 hours")


class CustomPolicy(BaseModel):
    name: str
    policy: dict[str, Any]

    @validator("name")
    def name_size(cls, v: str) -> str:
        """Check the policy name size.

        See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html
        """
        if len(v) > 128:
            raise ValueError(
                f"The policy name '{v}' is too long. The AWS policy name must be 128 characters or less."
            )
        return v

    @validator("policy")
    def policy_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Check the policy size.

        See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html
        """
        if len(json.dumps(v, separators=(",", ":"))) > 6144:
            raise ValueError(
                f"The policy document '{v}' is too large. AWS policy documents must be 6144 characters or less (w/o white spaces)."
            )
        return v


class ManagedPolicy(BaseModel):
    name: str


class AwsRole(BaseModel):
    name: str
    account: str
    custom_policies: list[CustomPolicy]
    managed_policies: list[ManagedPolicy]

    @validator("name")
    def name_size(cls, v: str) -> str:
        """Check the role name size.

        See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html
        """
        if len(v) > 64:
            raise ValueError(
                f"The role name '{v}' is too long. The AWS role name must be 64 characters or less."
            )
        return v

    @root_validator
    def validate_policies(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Check the policies.

        See https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html
        """
        custom_policies = values.get("custom_policies", [])
        managed_policies = values.get("managed_policies", [])
        if len(custom_policies) + len(managed_policies) > 20:
            raise ValueError(
                f"The role '{values['name']}' has too many policies. AWS roles can have at most 20 policies (via quota increase). Please consider consolidating the policies."
            )
        cp_names = [cp.name for cp in custom_policies]
        if len(set(cp_names)) != len(cp_names):
            raise ValueError(
                f"The role '{values['name']}' has duplicate custom policies."
            )
        mp_names = [mp.name for mp in managed_policies]
        if len(set(mp_names)) != len(mp_names):
            raise ValueError(
                f"The role '{values['name']}' has duplicate managed policies."
            )
        return values


class RunnerParams(TypedDict):
    tf: TerraformClient
    dry_run: bool
    enable_deletion: bool


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
            "roles": [c.dict() for c in self.get_roles(query_func)],
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

    def get_roles(
        self, query_func: Callable, account_name: str | None = None
    ) -> list[AwsRole]:
        """Return all roles with AWS account relations."""
        aws_roles = []
        for role in roles_query(query_func).roles or []:
            if not role.aws_groups and not role.user_policies:
                continue

            user_policies = role.user_policies or []
            aws_groups = role.aws_groups or []
            for sso_aws_account in unique_sso_aws_accounts(
                integration=self.name,
                accounts=[i.account for i in user_policies + aws_groups],
                account_name=account_name,
            ):
                # AWS limits are checked via pydantic validators
                custom_policies = [
                    CustomPolicy(name=user_policy.name, policy=user_policy.policy)
                    for user_policy in user_policies
                    if user_policy.account.uid == sso_aws_account.uid
                ]
                managed_policies = [
                    ManagedPolicy(name=p)
                    for aws_group in aws_groups
                    if aws_group.account.uid == sso_aws_account.uid
                    for p in aws_group.policies or []
                ]

                aws_roles.append(
                    AwsRole(
                        name=f"{sso_aws_account.uid}-{role.name}",
                        account=sso_aws_account.name,
                        custom_policies=custom_policies,
                        managed_policies=managed_policies,
                    )
                )

        return aws_roles

    def populate_saml_iam_roles(
        self, ts: TerrascriptClient, aws_roles: Iterable[AwsRole]
    ) -> None:
        """Populate the SAML IAM roles."""
        unique_policies = {
            (role.account, custom_policy.name): custom_policy.policy
            for role in aws_roles
            for custom_policy in role.custom_policies
        }
        # User policies are unique per account
        for (account, policy), policy_doc in unique_policies.items():
            ts.populate_iam_policy(
                account=account,
                name=policy,
                policy=policy_doc,
            )
        for role in aws_roles:
            ts.populate_saml_iam_role(
                account=role.account,
                name=role.name,
                saml_provider_name=self.params.saml_idp_name,
                aws_managed_policies=[p.name for p in role.managed_policies],
                customer_managed_policies=[p.name for p in role.custom_policies],
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
        aws_roles = self.get_roles(gql_api.query, account_name=self.params.account_name)

        ts = TerrascriptClient(
            self.name.replace("-", "_"),
            "",
            self.params.thread_pool_size,
            aws_accounts_dict,
            secret_reader=self.secret_reader,
        )
        self.populate_saml_iam_roles(ts, aws_roles)
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
                shard=self.params.account_name if self.params.account_name else "",
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
