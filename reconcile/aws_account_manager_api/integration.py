"""AWS account manager reconciliation via qontract-api.

Client-side integration that calls the qontract-api to create and
reconcile AWS accounts. Per-account design: each API call handles
exactly one account.

Template rendering and MR creation happen client-side after the API
returns a completed account creation with the AWS account UID.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).
"""

import asyncio
import logging
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from qontract_api_client.api.external.vcs_create_merge_request import (
    asyncio as vcs_create_merge_request,
)
from qontract_api_client.api.external.vcs_find_merge_request import (
    asyncio as vcs_find_merge_request,
)
from qontract_api_client.api.integrations.aws_account_manager_create import (
    AWSAccountManagerTaskResponse as CreateAccountAWSAccountManagerResult,
)
from qontract_api_client.api.integrations.aws_account_manager_create import (
    asyncio as create_account,
)
from qontract_api_client.api.integrations.aws_account_manager_create_iam_user import (
    AWSAccountManagerTaskResponse as CreateIAMUserAWSAccountManagerTaskResponse,
)
from qontract_api_client.api.integrations.aws_account_manager_create_iam_user import (
    asyncio as create_iam_user,
)
from qontract_api_client.api.integrations.aws_account_manager_reconcile import (
    AWSAccountManagerTaskResponse as ReconcileAWSAccountManagerResult,
)
from qontract_api_client.api.integrations.aws_account_manager_reconcile import (
    asyncio as reconcile_account,
)
from qontract_api_client.models.aws_account_manager_create_account_request import (
    AWSAccountManagerCreateAccountRequest,
)
from qontract_api_client.models.aws_account_manager_create_account_request_default_tags import (
    AWSAccountManagerCreateAccountRequestDefaultTags,
)
from qontract_api_client.models.aws_account_manager_create_iam_user_request import (
    AWSAccountManagerCreateIAMUserRequest,
)
from qontract_api_client.models.aws_account_manager_reconcile_request import (
    AWSAccountManagerReconcileRequest,
)
from qontract_api_client.models.aws_account_manager_reconcile_request_default_tags import (
    AWSAccountManagerReconcileRequestDefaultTags,
)
from qontract_api_client.models.aws_account_organization import AWSAccountOrganization
from qontract_api_client.models.aws_account_organization_tags import (
    AWSAccountOrganizationTags,
)
from qontract_api_client.models.aws_account_request import (
    AWSAccountRequest as ApiAccountRequest,
)
from qontract_api_client.models.aws_payer_account import (
    AWSPayerAccount as ApiPayerAccount,
)
from qontract_api_client.models.aws_payer_account_organization_account_tags import (
    AWSPayerAccountOrganizationAccountTags,
)
from qontract_api_client.models.aws_quota import AWSQuota as ApiQuota
from qontract_api_client.models.aws_security_contact import (
    AWSSecurityContact as ApiSecurityContact,
)
from qontract_api_client.models.create_merge_request_request import (
    CreateMergeRequestRequest,
)
from qontract_api_client.models.merge_request_file_operation import (
    MergeRequestFileOperation,
)
from qontract_api_client.models.secret import Secret
from qontract_api_client.models.task_status import TaskStatus
from qontract_utils.templating import render_template

from reconcile.aws_account_manager.metrics import (
    NonOrgAccountCounter,
    OrgAccountCounter,
    PayerAccountCounter,
)
from reconcile.aws_account_manager.utils import validate
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountRequestV1,
    AWSAccountV1,
)
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.gql_definitions.fragments.aws_account_managed import AWSAccountManaged
from reconcile.utils import gql, metrics
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "aws-account-manager-api"


class AwsAccountMgmtApiIntegrationParams(PydanticRunParams):
    """Parameters for aws-account-manager-api integration."""

    account_name: str | None = None
    flavor: str
    organization_account_role: str = "OrganizationAccountAccessRole"
    default_tags: dict[str, str] = {}
    initial_user_name: str = "terraform"
    initial_user_policy_arn: str = "arn:aws:iam::aws:policy/AdministratorAccess"
    initial_user_secret_vault_path: str = (
        "app-sre-v2/creds/terraform/{account_name}/config"  # noqa: RUF027
    )
    account_tmpl_resource: str = "/aws-account-manager/account-tmpl.yml.j2"
    template_collection_root_path: str = "data/templating/collections/aws-account"
    app_interface_repo_url: str = ""
    vcs_secret_path: str = ""
    vcs_secret_field: str | None = None


class AwsAccountMgmtApiIntegration(
    QontractReconcileApiIntegration[AwsAccountMgmtApiIntegrationParams],
):
    """Create and manage AWS accounts via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_aws_accounts(
        self,
        query_func: Callable,
        account_name: str | None = None,
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

        # check account requests for invalid emails
        used_emails: set[str] = {
            owner.email
            for account in all_aws_accounts
            for owner in account.account_owners
        }
        for payer_account in payer_accounts:
            for account_request in payer_account.account_requests or []:
                if account_request.account_owner.email in used_emails:
                    raise ValueError(
                        f"Invalid email for account request {account_request.name} "
                        f"in payer account {payer_account.name}. "
                        f"Email {account_request.account_owner.email} is already used.",
                    )
                used_emails.add(account_request.account_owner.email)
        return payer_accounts, non_organization_accounts

    def _build_secret(self, token: Any) -> Secret:
        """Convert a VaultSecret to the API client Secret model."""
        return Secret(
            secret_manager_url=self.secret_manager_url,
            path=token.path,
            field=token.field,
            version=token.version,
        )

    def _build_payer_account(self, account: AWSAccountV1) -> ApiPayerAccount:
        """Convert a GQL AWSAccountV1 to an API AWSPayerAccount."""
        aws_account_manager_role = (
            account.automation_role.aws_account_manager
            if account.automation_role
            else None
        )
        if not aws_account_manager_role:
            raise ValueError(
                f"awsAccountManager role is not defined for account {account.name}",
            )

        return ApiPayerAccount(
            name=account.name,
            uid=account.uid,
            automation_token=self._build_secret(account.automation_token),
            automation_role=aws_account_manager_role,
            resources_default_region=account.resources_default_region,
            organization_account_tags=AWSPayerAccountOrganizationAccountTags.from_dict(
                account.organization_account_tags or {},
            ),
        )

    def _build_security_contact(self, account: AWSAccountManaged) -> ApiSecurityContact:
        """Convert a GQL security contact to the API client model.

        validate() ensures security_contact is always present.
        """
        sc = account.security_contact
        assert sc is not None  # guaranteed by validate()
        return ApiSecurityContact(
            name=sc.name,
            title=sc.title,
            email=sc.email,
            phone_number=sc.phone_number,
        )

    def _build_quotas(self, account: AWSAccountManaged) -> list[ApiQuota]:
        """Convert GQL quota limits to API client quota models."""
        return [
            ApiQuota(
                service_code=q.service_code,
                quota_code=q.quota_code,
                value=q.value,
            )
            for ql in account.quota_limits or []
            for q in ql.quotas
        ]

    def _build_org_reconcile_request(
        self,
        payer: AWSAccountV1,
        org_account: AWSAccountManaged,
        dry_run: bool,
    ) -> AWSAccountManagerReconcileRequest:
        """Build a reconcile request for an organization account."""
        org = org_account.organization
        return AWSAccountManagerReconcileRequest(
            account_name=org_account.name,
            uid=org_account.uid,
            automation_token=self._build_secret(payer.automation_token),
            resources_default_region=payer.resources_default_region,
            payer_uid=payer.uid,
            alias=org_account.alias,
            quotas=self._build_quotas(org_account),
            security_contact=self._build_security_contact(org_account),
            supported_deployment_regions=org_account.supported_deployment_regions or [],
            organization=AWSAccountOrganization(
                ou=org.ou,
                tags=AWSAccountOrganizationTags.from_dict(org.tags)
                if org.tags
                else AWSAccountOrganizationTags.from_dict({}),
            )
            if org
            else None,
            automation_role=payer.automation_role.aws_account_manager
            if payer.automation_role
            else None,
            organization_account_role=self.params.organization_account_role,
            enterprise_support=org_account.enterprise_support,
            default_tags=AWSAccountManagerReconcileRequestDefaultTags.from_dict(
                self.params.default_tags | (payer.organization_account_tags or {}),
            ),
            dry_run=dry_run,
        )

    def _build_non_org_reconcile_request(
        self,
        account: AWSAccountV1,
        dry_run: bool,
    ) -> AWSAccountManagerReconcileRequest:
        """Build a reconcile request for a non-organization account."""
        return AWSAccountManagerReconcileRequest(
            account_name=account.name,
            uid=account.uid,
            automation_token=self._build_secret(account.automation_token),
            resources_default_region=account.resources_default_region,
            alias=account.alias,
            quotas=self._build_quotas(account),
            security_contact=self._build_security_contact(account),
            supported_deployment_regions=account.supported_deployment_regions or [],
            dry_run=dry_run,
        )

    def _build_create_request(
        self,
        payer: AWSAccountV1,
        request: AWSAccountRequestV1,
        dry_run: bool,
    ) -> AWSAccountManagerCreateAccountRequest:
        """Build a create-account request for a single account request."""
        return AWSAccountManagerCreateAccountRequest(
            payer_account=self._build_payer_account(payer),
            account_request=ApiAccountRequest(
                name=request.name,
                email=request.account_owner.email,
                uid=request.uid,
                path=request.path,
            ),
            organization_account_role=self.params.organization_account_role,
            default_tags=AWSAccountManagerCreateAccountRequestDefaultTags.from_dict(
                self.params.default_tags,
            ),
            dry_run=dry_run,
        )

    def _build_create_iam_user_request(
        self,
        payer: AWSAccountV1,
        account_name: str,
        account_uid: str,
        dry_run: bool,
    ) -> AWSAccountManagerCreateIAMUserRequest:
        """Build a create-iam-user request for a completed account."""
        return AWSAccountManagerCreateIAMUserRequest(
            payer_account=self._build_payer_account(payer),
            account_name=account_name,
            account_uid=account_uid,
            organization_account_role=self.params.organization_account_role,
            user_name=self.params.initial_user_name,
            policy_arn=self.params.initial_user_policy_arn,
            secret_vault_path=self.params.initial_user_secret_vault_path.format(
                account_name=account_name,
            ),
            dry_run=dry_run,
        )

    def render_account_template(
        self,
        *,
        template: str,
        account_request: AWSAccountRequestV1,
        uid: str,
    ) -> str:
        """Render the account template with account data.

        Args:
            template: Jinja2 template content
            account_request: Account request with name, email, path
            uid: AWS account ID

        Returns:
            Rendered template content

        """
        settings = {
            "initial_user_name": self.params.initial_user_name,
            "initial_user_policy_arn": self.params.initial_user_policy_arn,
            "initial_user_secret_vault_path": self.params.initial_user_secret_vault_path,
            "organization_account_role": self.params.organization_account_role,
        }
        for k, v in settings.items():
            if isinstance(v, str):
                settings[k] = v.format(account_name=account_request.name)

        return render_template(
            template=template,
            accountRequest=account_request.model_dump(by_alias=True) | {"uid": uid},
            uid=uid,
            settings=settings,
            timestamp=int(datetime.now(UTC).timestamp()),
        )

    def _build_vcs_secret(self) -> Secret:
        """Build the VCS secret reference for app-interface MR creation."""
        return Secret(
            secret_manager_url=self.secret_manager_url,
            path=self.params.vcs_secret_path,
            field=self.params.vcs_secret_field,
            version=None,
        )

    def expose_metrics(
        self,
        payer_accounts: list[AWSAccountV1],
        non_organization_accounts: list[AWSAccountV1],
    ) -> None:
        """Expose Prometheus metrics."""
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

    def _log_results(self, results: list[Any]) -> bool:
        """Log task results and return True if any errors occurred."""
        has_errors = False
        for result in results:
            if result.status == TaskStatus.PENDING:
                logging.error("Task did not complete within the timeout period")
                has_errors = True
                continue

            for action in result.actions or []:
                logging.info(action)

            if result.errors:
                logging.error(f"Errors encountered: {len(result.errors)}")
                for error in result.errors:
                    logging.error("  - %s", error)
                has_errors = True
        return has_errors

    def _extract_completed_creates(self, results: list[Any]) -> list[tuple[str, str]]:
        """Extract (account_name, account_uid) pairs from create_complete actions."""
        completed: list[tuple[str, str]] = []
        for result in results:
            for action in result.actions or []:
                if not hasattr(action, "action_type"):
                    continue
                if action.action_type == "create_complete":
                    completed.append((action.account_name, action.account_uid))
        return completed

    async def _create_iam_users(
        self,
        *,
        completed: list[tuple[str, str]],
        payer_by_request_name: dict[str, AWSAccountV1],
        dry_run: bool,
    ) -> None:
        """Create IAM users for completed account creates in parallel."""
        iam_calls = []
        for account_name, account_uid in completed:
            payer = payer_by_request_name.get(account_name)
            if not payer:
                logging.error("Payer account not found for %s", account_name)
                continue
            iam_calls.append(
                create_iam_user(
                    client=self.qontract_api_client,
                    body=self._build_create_iam_user_request(
                        payer=payer,
                        account_name=account_name,
                        account_uid=account_uid,
                        dry_run=dry_run,
                    ),
                ),
            )

        if iam_calls:
            iam_responses = await asyncio.gather(*iam_calls)
            iam_results = await asyncio.gather(*[
                self.poll_task_status(
                    response.status_url,
                    CreateIAMUserAWSAccountManagerTaskResponse,
                    timeout=300,
                )
                for response in iam_responses
            ])
            self._log_results(iam_results)

    async def _create_account_merge_requests(
        self,
        *,
        completed: list[tuple[str, str]],
        account_requests_by_name: dict[str, AWSAccountRequestV1],
        account_template: str,
        auto_merge: bool,
    ) -> None:
        """Render account templates and create MRs for completed creates.

        Skips accounts that already have an open MR (deduplication).
        """
        vcs_secret = self._build_vcs_secret()

        # Build (account_name, account_uid, account_request, source_branch) tuples
        candidates = []
        for account_name, account_uid in completed:
            if account_request := account_requests_by_name.get(account_name):
                candidates.append((
                    account_name,
                    account_uid,
                    account_request,
                    f"aws-account-manager/{account_request.name}",
                ))
            else:
                logging.error("Account request not found for %s", account_name)

        if not candidates:
            return

        # Check all MRs in parallel (deduplication)
        existing_mrs = await asyncio.gather(*[
            vcs_find_merge_request(
                client=self.qontract_api_client,
                secret_manager_url=vcs_secret.secret_manager_url,
                path=vcs_secret.path,
                field=vcs_secret.field,
                repo_url=self.params.app_interface_repo_url,
                source_branch=source_branch,
            )
            for _, _, _, source_branch in candidates
        ])

        mr_calls = []
        for (
            account_name,
            account_uid,
            account_request,
            source_branch,
        ), existing_mr in zip(candidates, existing_mrs, strict=True):
            if existing_mr:
                logging.info(f"MR already exists for {account_name}: {existing_mr.url}")
                continue

            tmpl_content = self.render_account_template(
                template=account_template,
                account_request=account_request,
                uid=account_uid,
            )
            tmpl_file_path = f"{self.params.template_collection_root_path}/{account_request.name}.yml"
            request_file_path = f"data/{account_request.path.strip('/')}"
            labels = ["aws-account-manager"]
            if auto_merge:
                labels.append("bot/automerge")

            mr_calls.append(
                vcs_create_merge_request(
                    client=self.qontract_api_client,
                    body=CreateMergeRequestRequest(
                        repo_url=self.params.app_interface_repo_url,
                        token=vcs_secret,
                        title=f"{account_request.name}: AWS account template collection file",
                        description=f"New AWS account template collection file {tmpl_file_path}",
                        source_branch=source_branch,
                        file_operations=[
                            MergeRequestFileOperation(
                                path=tmpl_file_path,
                                content=tmpl_content,
                                commit_message="add account template file",
                            ),
                            MergeRequestFileOperation(
                                path=request_file_path,
                                content=None,
                                commit_message="delete account request file",
                            ),
                        ],
                        labels=labels,
                        auto_merge=auto_merge,
                    ),
                ),
            )

        if mr_calls:
            mr_responses = await asyncio.gather(*mr_calls)
            for response in mr_responses:
                logging.info(f"MR created: {response.url}")

    async def _handle_completed_creates(
        self,
        *,
        results: list[Any],
        payer_accounts: Iterable[AWSAccountV1],
        account_template: str,
        auto_merge: bool,
        dry_run: bool,
    ) -> None:
        """Create IAM users, render templates, and create MRs for completed creates."""
        completed = self._extract_completed_creates(results)
        if not completed:
            return

        account_requests_by_name: dict[str, AWSAccountRequestV1] = {
            request.name: request
            for payer in payer_accounts
            for request in payer.account_requests or []
        }
        payer_by_request_name: dict[str, AWSAccountV1] = {
            request.name: payer
            for payer in payer_accounts
            for request in payer.account_requests or []
        }

        await self._create_iam_users(
            completed=completed,
            payer_by_request_name=payer_by_request_name,
            dry_run=dry_run,
        )
        await self._create_account_merge_requests(
            completed=completed,
            account_requests_by_name=account_requests_by_name,
            account_template=account_template,
            auto_merge=auto_merge,
        )

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        payer_accounts, non_organization_accounts = self.get_aws_accounts(
            gql_api.query,
            account_name=self.params.account_name,
        )
        account_template = gql_api.get_resource(path=self.params.account_tmpl_resource)[
            "content"
        ]
        auto_merge = get_feature_toggle_state(
            integration_name="aws-account-manager-allow-auto-merge-mrs",
            default=False,
        )

        self.expose_metrics(
            payer_accounts=payer_accounts,
            non_organization_accounts=non_organization_accounts,
        )

        # Dispatch all API calls in parallel — one per account
        create_calls = [
            create_account(
                client=self.qontract_api_client,
                body=self._build_create_request(
                    payer=payer,
                    request=request,
                    dry_run=dry_run,
                ),
            )
            for payer in payer_accounts
            for request in payer.account_requests or []
        ]

        reconcile_calls = [
            reconcile_account(
                client=self.qontract_api_client,
                body=self._build_org_reconcile_request(
                    payer=payer,
                    org_account=org_account,
                    dry_run=dry_run,
                ),
            )
            for payer in payer_accounts
            for org_account in payer.organization_accounts or []
        ] + [
            reconcile_account(
                client=self.qontract_api_client,
                body=self._build_non_org_reconcile_request(
                    account=account,
                    dry_run=dry_run,
                ),
            )
            for account in non_organization_accounts
        ]

        # Dispatch create and reconcile in parallel, keep responses separate
        create_responses, reconcile_responses = (
            await asyncio.gather(*create_calls),
            await asyncio.gather(*reconcile_calls),
        )

        for response in [*create_responses, *reconcile_responses]:
            logging.info(f"request_id: {response.id}")

        # Always wait for create results to handle post-create MR creation
        has_errors = False
        if create_responses:
            create_results = await asyncio.gather(*[
                self.poll_task_status(
                    response.status_url,
                    CreateAccountAWSAccountManagerResult,
                    timeout=300,
                )
                for response in create_responses
            ])
            has_errors = self._log_results(create_results)

            # For completed creates: create IAM user, render template, create MR
            await self._handle_completed_creates(
                results=create_results,
                payer_accounts=payer_accounts,
                account_template=account_template,
                auto_merge=auto_merge,
                dry_run=dry_run,
            )

        if dry_run:
            # In dry-run: also wait for reconcile results
            if reconcile_responses:
                reconcile_results = await asyncio.gather(*[
                    self.poll_task_status(
                        response.status_url,
                        ReconcileAWSAccountManagerResult,
                        timeout=300,
                    )
                    for response in reconcile_responses
                ])
                has_errors = self._log_results(reconcile_results) or has_errors

        if has_errors:
            sys.exit(1)
