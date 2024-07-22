from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

import jinja2

from reconcile.aws_account_manager.merge_request_manager import MergeRequestManager
from reconcile.aws_account_manager.metrics import (
    NonOrgAccountCounter,
    OrgAccountCounter,
    PayerAccountCounter,
)
from reconcile.aws_account_manager.reconciler import AWSReconciler
from reconcile.aws_account_manager.utils import validate
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountManaged,
    AWSAccountRequestV1,
    AWSAccountV1,
)
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql, metrics
from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from reconcile.utils.aws_api_typed.iam import AWSAccessKey
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "aws-account-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class AwsAccountMgmtIntegrationParams(PydanticRunParams):
    account_name: str | None
    flavor: str
    organization_account_role: str = "OrganizationAccountAccessRole"
    default_tags: dict[str, str] = {}
    initial_user_name: str = "terraform"
    initial_user_policy_arn: str = "arn:aws:iam::aws:policy/AdministratorAccess"
    initial_user_secret_vault_path: str = (
        "app-sre-v2/creds/terraform/{account_name}/config"
    )
    account_tmpl_resource: str = "/aws-account-manager/account-tmpl.yml"
    template_collection_root_path: str = "data/templating/collections/aws-account"


class AwsAccountMgmtIntegration(
    QontractReconcileIntegration[AwsAccountMgmtIntegrationParams]
):
    """Create and manage AWS accounts."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_early_exit_desired_state(
        self, query_func: Callable | None = None
    ) -> dict[str, Any]:
        """Return the desired state for early exit."""
        if not query_func:
            query_func = gql.get_api().query
        payer_accounts, non_organization_accounts = self.get_aws_accounts(
            query_func, account_name=self.params.account_name
        )
        return {
            "payer_accounts": [account.dict() for account in payer_accounts],
            "non_organization_accounts": [
                account.dict() for account in non_organization_accounts
            ],
        }

    @staticmethod
    def render_account_tmpl_file(
        template: str, account_request: AWSAccountRequestV1, uid: str, settings: dict
    ) -> str:
        for k, v in settings.items():
            if not isinstance(v, str):
                continue
            # render string templates with account name
            settings[k] = v.format(account_name=account_request.name)
        tmpl = jinja2.Template(
            template,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        ).render({
            "accountRequest": account_request.dict(by_alias=True),
            "uid": uid,
            "settings": settings,
            "timestamp": int(datetime.now(tz=UTC).timestamp()),
        })
        return tmpl

    def get_aws_accounts(
        self, query_func: Callable, account_name: str | None = None
    ) -> tuple[list[AWSAccountV1], list[AWSAccountV1]]:
        """Get all AWS payer and non-organization accounts."""
        data = aws_accounts_query(query_func)

        all_aws_accounts = [
            account
            for account in data.accounts or []
            if integration_is_enabled(self.name, account)
            and (not account_name or account.name == account_name)
            and validate(account)
        ]
        payer_accounts = [
            account
            for account in all_aws_accounts
            if account.organization_accounts or account.account_requests
        ]
        all_organization_account_names = {
            org_account.name
            for payer_account in payer_accounts
            for org_account in payer_account.organization_accounts or []
        }

        non_organization_accounts = [
            account
            for account in all_aws_accounts
            if account.name not in all_organization_account_names
        ]
        return payer_accounts, non_organization_accounts

    def save_access_key(self, account: str, access_key: AWSAccessKey) -> None:
        """Write the AWS secret to Vault."""
        self.secret_reader.vault_client.write(  # type: ignore[attr-defined] # mypy doesn't recognize the VaultClient.__new__ method
            secret={
                "data": {
                    "aws_access_key_id": access_key.access_key_id,
                    "aws_secret_access_key": access_key.secret_access_key,
                },
                "path": self.params.initial_user_secret_vault_path.format(
                    account_name=account
                ).strip("/"),
            },
            decode_base64=False,
        )

    def create_accounts(
        self,
        aws_api: AWSApi,
        reconciler: AWSReconciler,
        merge_request_manager: MergeRequestManager,
        account_template: str,
        account_requests: Iterable[AWSAccountRequestV1],
    ) -> None:
        """Create new AWS accounts."""
        for account_request in account_requests:
            uid = account_request.uid or reconciler.create_organization_account(
                aws_api=aws_api,
                name=account_request.name,
                email=account_request.account_owner.email,
            )
            if not uid:
                continue

            with aws_api.assume_role(
                account_id=uid, role=self.params.organization_account_role
            ) as account_role_api:
                if access_key := reconciler.create_iam_user(
                    aws_api=account_role_api,
                    name=account_request.name,
                    user_name=self.params.initial_user_name,
                    user_policy_arn=self.params.initial_user_policy_arn,
                ):
                    self.save_access_key(account_request.name, access_key)

            merge_request_manager.create_account_file(
                title=f"{account_request.name}: AWS account template collection file",
                account_tmpl_file_path=f"{self.params.template_collection_root_path}/{account_request.name}.yml",
                account_tmpl_file_content=self.render_account_tmpl_file(
                    template=account_template,
                    account_request=account_request,
                    uid=uid,
                    settings=self.params.dict(),
                ),
                account_request_file_path=f"data/{account_request.path.strip('/')}",
            )

    def reconcile_organization_accounts(
        self,
        aws_api: AWSApi,
        reconciler: AWSReconciler,
        organization_accounts: Iterable[AWSAccountManaged],
    ) -> None:
        """Reconcile organization accounts."""
        for account in organization_accounts:
            assert account.organization  # mypy
            reconciler.reconcile_organization_account(
                aws_api=aws_api,
                name=account.name,
                uid=account.uid,
                ou=account.organization.ou,
                tags=self.params.default_tags
                | account.organization.tags
                | {"app-interface-name": account.name},
                enterprise_support=account.premium_support,
            )

            with aws_api.assume_role(
                account_id=account.uid, role=self.params.organization_account_role
            ) as account_role_api:
                self.reconcile_account(account_role_api, reconciler, account)

    def reconcile_account(
        self, aws_api: AWSApi, reconciler: AWSReconciler, account: AWSAccountManaged
    ) -> None:
        """Reconcile an AWS account."""
        assert account.security_contact  # mypy
        reconciler.reconcile_account(
            aws_api=aws_api,
            name=account.name,
            alias=account.alias,
            quotas=[q for ql in account.quota_limits or [] for q in ql.quotas],
            security_contact=account.security_contact,
        )

    def reconcile_payer_accounts(
        self,
        reconciler: AWSReconciler,
        merge_request_manager: MergeRequestManager,
        default_state_path: str,
        account_template: str,
        payer_accounts: Iterable[AWSAccountV1],
    ) -> None:
        """Reconcile all payer accounts including account creation."""
        # reconcile accounts within payer accounts, aka organization accounts
        for payer_account in payer_accounts:
            # having a state per flavor and payer account makes it easier in a shared environment
            reconciler.state.state_path = f"{default_state_path}/{payer_account.name}"
            aws_account_manager_role = (
                payer_account.automation_role.aws_account_manager
                if payer_account.automation_role
                else None
            )
            if not aws_account_manager_role:
                raise ValueError(
                    f"awsAccountManager role is not defined for account {payer_account.name}"
                )

            secret = self.secret_reader.read_all_secret(payer_account.automation_token)
            with (
                AWSApi(
                    AWSStaticCredentials(
                        access_key_id=secret["aws_access_key_id"],
                        secret_access_key=secret["aws_secret_access_key"],
                        region=payer_account.resources_default_region,
                    )
                ) as payer_account_aws_api,
                payer_account_aws_api.assume_role(
                    account_id=payer_account.uid,
                    role=aws_account_manager_role,
                ) as acct_manager_role_aws_api,
            ):
                self.create_accounts(
                    acct_manager_role_aws_api,
                    reconciler,
                    merge_request_manager,
                    account_template,
                    payer_account.account_requests or [],
                )
                self.reconcile_organization_accounts(
                    acct_manager_role_aws_api,
                    reconciler,
                    payer_account.organization_accounts or [],
                )

    def reconcile_non_organization_accounts(
        self,
        reconciler: AWSReconciler,
        default_state_path: str,
        non_organization_accounts: Iterable[AWSAccountV1],
    ) -> None:
        """Reconcile accounts not part of an organization via a payer account (e.g. payer accounts themselves)"""
        for account in non_organization_accounts:
            # the state must be account specific
            reconciler.state.state_path = f"{default_state_path}/{account.name}"
            secret = self.secret_reader.read_all_secret(account.automation_token)
            with AWSApi(
                AWSStaticCredentials(
                    access_key_id=secret["aws_access_key_id"],
                    secret_access_key=secret["aws_secret_access_key"],
                    region=account.resources_default_region,
                )
            ) as account_aws_api:
                self.reconcile_account(account_aws_api, reconciler, account)

    def expose_metrics(
        self,
        payer_accounts: list[AWSAccountV1],
        non_organization_accounts: list[AWSAccountV1],
    ) -> None:
        """Expose metrics."""
        with metrics.transactional_metrics(self.name) as metrics_container:
            metrics_container.set_gauge(
                PayerAccountCounter(flavor=self.params.flavor),
                value=len(payer_accounts),
            )

            for payer_account in payer_accounts:
                metrics_container.set_gauge(
                    OrgAccountCounter(
                        flavor=self.params.flavor,
                        payer_account=payer_account.name,
                    ),
                    value=len(payer_account.organization_accounts or []),
                )
            metrics_container.set_gauge(
                NonOrgAccountCounter(flavor=self.params.flavor),
                value=len(non_organization_accounts),
            )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        payer_accounts, non_organization_accounts = self.get_aws_accounts(
            gql_api.query, account_name=self.params.account_name
        )
        state = init_state(self.name, self.secret_reader)
        default_state_path = f"state/{self.name}/{self.params.flavor}"
        reconciler = AWSReconciler(state, dry_run)
        vcs = VCS(
            secret_reader=self.secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=False,
            allow_opening_mrs=True,
        )
        if defer:
            defer(vcs.cleanup)
        merge_request_manager = MergeRequestManager(
            vcs=vcs,
            auto_merge_enabled=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-auto-merge-mrs", default=False
            ),
        )
        merge_request_manager.fetch_open_merge_requests()
        account_template = gql_api.get_resource(path=self.params.account_tmpl_resource)[
            "content"
        ]

        self.expose_metrics(
            payer_accounts=payer_accounts,
            non_organization_accounts=non_organization_accounts,
        )
        self.reconcile_payer_accounts(
            reconciler=reconciler,
            merge_request_manager=merge_request_manager,
            default_state_path=default_state_path,
            account_template=account_template,
            payer_accounts=payer_accounts,
        )
        self.reconcile_non_organization_accounts(
            reconciler=reconciler,
            default_state_path=default_state_path,
            non_organization_accounts=non_organization_accounts,
        )
