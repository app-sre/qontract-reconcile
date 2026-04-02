"""AWS account manager service — orchestration layer.

Creates AWS clients, delegates work to the reconciler,
and wraps results in typed action/result models for the API.
"""

from qontract_api.aws.aws_client_factory import create_aws_workspace_client
from qontract_api.aws.aws_workspace_client import AWSWorkspaceClient
from qontract_api.aws.domain import (
    AWSAccountOrganization,
    AWSAccountRequest,
    AWSPayerAccount,
    AWSQuota,
    AWSSecurityContact,
)
from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.aws_account_manager.reconciler import AWSReconciler
from qontract_api.integrations.aws_account_manager.schemas import (
    AccountCreateCompleteAction,
    AccountCreateIAMUserAction,
    AWSAccountManagerReconcileRequest,
    CreateAccountResult,
    CreateIAMUserResult,
    ReconcileAction,
    ReconcileResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class AccountCreationInProgressError(Exception):
    """Raised when account creation workflow is not yet complete.

    The Celery task catches this and retries itself after a countdown.
    """


class AWSAccountManagerService:
    """Service for creating and reconciling AWS accounts.

    Thin orchestration layer: creates AWS clients, delegates actual work
    to ``AWSReconciler``, and wraps results in typed result models.
    """

    def __init__(
        self,
        *,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self._cache = cache
        self._secret_manager = secret_manager
        self._settings = settings
        self._reconciler = AWSReconciler(secret_manager=secret_manager)

    # --- AWS client creation ---

    def _create_aws_client(self, *, payer: AWSPayerAccount) -> AWSWorkspaceClient:
        """Create an AWSWorkspaceClient for a payer account."""
        return create_aws_workspace_client(
            secret=payer.automation_token,
            region=payer.resources_default_region,
            cache=self._cache,
            secret_manager=self._secret_manager,
            settings=self._settings,
        )

    @staticmethod
    def _create_manager_client(
        *,
        payer_client: AWSWorkspaceClient,
        payer: AWSPayerAccount,
    ) -> AWSWorkspaceClient:
        """Assume the account manager role on a payer account."""
        return payer_client.assume_role(
            account_id=payer.uid,
            role=payer.automation_role,
        )

    # --- Account creation ---

    def create_account(
        self,
        *,
        payer_account: AWSPayerAccount,
        account_request: AWSAccountRequest,
        default_tags: dict[str, str] | None = None,
        dry_run: bool = True,
    ) -> CreateAccountResult:
        """Execute the account creation workflow for a single account request."""
        with (
            self._create_aws_client(payer=payer_account) as payer_client,
            self._create_manager_client(
                payer_client=payer_client,
                payer=payer_account,
            ) as manager_client,
        ):
            try:
                tags = (
                    (default_tags or {})
                    | payer_account.organization_account_tags
                    | {"app-interface-name": account_request.name}
                )
                account_uid = self._reconciler.create_organization_account(
                    manager_client,
                    name=account_request.name,
                    email=account_request.email,
                    uid=account_request.uid,
                    tags=tags,
                    dry_run=dry_run,
                )
            except Exception as e:
                error_msg = f"{payer_account.name}/{account_request.name}: {e}"
                logger.exception(error_msg)
                return CreateAccountResult(
                    status=TaskStatus.FAILED,
                    errors=[error_msg],
                )

            if not account_uid and not dry_run:
                raise AccountCreationInProgressError(
                    f"{payer_account.name}/{account_request.name}: "
                    "account creation workflow not yet complete",
                )

            actions = []
            if account_uid:
                actions.append(
                    AccountCreateCompleteAction(
                        account_name=account_request.name,
                        payer_account_name=payer_account.name,
                        account_uid=account_uid,
                    ),
                )
            return CreateAccountResult(
                status=TaskStatus.SUCCESS,
                actions=actions,
                applied_count=1 if account_uid and not dry_run else 0,
            )

    def create_iam_user(
        self,
        *,
        payer_account: AWSPayerAccount,
        account_name: str,
        account_uid: str,
        org_role: str = "OrganizationAccountAccessRole",
        user_name: str,
        policy_arn: str,
        secret_vault_path: str,
        dry_run: bool = True,
    ) -> CreateIAMUserResult:
        """Create an IAM user in an AWS account."""
        with (
            self._create_aws_client(payer=payer_account) as payer_client,
            self._create_manager_client(
                payer_client=payer_client,
                payer=payer_account,
            ) as manager_client,
        ):
            try:
                with manager_client.assume_role(
                    account_id=account_uid,
                    role=org_role,
                ) as account_client:
                    created = self._reconciler.create_iam_user(
                        account_client,
                        account_name=account_name,
                        user_name=user_name,
                        policy_arn=policy_arn,
                        vault_path=secret_vault_path,
                        dry_run=dry_run,
                    )
                actions = []
                if created:
                    actions.append(
                        AccountCreateIAMUserAction(
                            account_name=account_name,
                            user_name=user_name,
                            detail="IAM user created and credentials saved to vault"
                            if not dry_run
                            else "Would create IAM user",
                        ),
                    )
                return CreateIAMUserResult(
                    status=TaskStatus.SUCCESS,
                    actions=actions,
                    applied_count=1 if created and not dry_run else 0,
                )
            except Exception as e:
                error_msg = f"{payer_account.name}/{account_name}: {e}"
                logger.exception(error_msg)
                return CreateIAMUserResult(
                    status=TaskStatus.FAILED,
                    errors=[error_msg],
                )

    # --- Account reconciliation ---

    def reconcile(
        self,
        *,
        account: AWSAccountManagerReconcileRequest,
        dry_run: bool = True,
    ) -> ReconcileResult:
        """Reconcile a single AWS account to match desired state."""
        if account.is_org_account and not account.payer_uid:
            raise ValueError(
                f"{account.account_name}: payer_uid is required for org accounts"
            )
        with create_aws_workspace_client(
            secret=account.automation_token,
            region=account.resources_default_region,
            cache=self._cache,
            secret_manager=self._secret_manager,
            settings=self._settings,
        ) as client:
            try:
                if not account.is_org_account:
                    actions = self._reconcile_standalone_account(
                        client=client,
                        account_name=account.account_name,
                        alias=account.alias,
                        quotas=account.quotas or [],
                        security_contact=account.security_contact,
                        supported_deployment_regions=account.supported_deployment_regions
                        or [],
                        dry_run=dry_run,
                    )
                else:
                    assert (
                        account.payer_uid
                    )  # mypy - already checked above, but mypy doesn't recognize it
                    assert (
                        account.organization
                    )  # mypy - checkin in account.is_org_account
                    actions = self._reconcile_org_account(
                        client=client,
                        account_name=account.account_name,
                        uid=account.uid,
                        payer_uid=account.payer_uid,
                        alias=account.alias,
                        quotas=account.quotas or [],
                        security_contact=account.security_contact,
                        supported_deployment_regions=account.supported_deployment_regions
                        or [],
                        organization=account.organization,
                        automation_role=account.automation_role or "",
                        org_role=account.organization_account_role,
                        enterprise_support=account.enterprise_support,
                        default_tags=account.default_tags or {},
                        dry_run=dry_run,
                    )
                return ReconcileResult(
                    status=TaskStatus.SUCCESS,
                    actions=actions,
                    applied_count=len(actions) if not dry_run else 0,
                )
            except Exception as e:
                error_msg = f"{account.account_name}: {e}"
                logger.exception(error_msg)
                return ReconcileResult(
                    status=TaskStatus.FAILED,
                    actions=[],
                    errors=[error_msg],
                )

    def _reconcile_org_account(
        self,
        *,
        client: AWSWorkspaceClient,
        account_name: str,
        uid: str,
        payer_uid: str,
        alias: str | None,
        quotas: list[AWSQuota],
        security_contact: AWSSecurityContact,
        supported_deployment_regions: list[str],
        organization: AWSAccountOrganization,
        automation_role: str,
        org_role: str,
        enterprise_support: bool,
        default_tags: dict[str, str],
        dry_run: bool,
    ) -> list[ReconcileAction]:
        """Reconcile an organization-managed account."""
        r = self._reconciler
        actions: list[ReconcileAction] = []
        with client.assume_role(
            account_id=payer_uid,
            role=automation_role,
        ) as manager_client:
            desired_tags = (
                default_tags | organization.tags | {"app-interface-name": account_name}
            )
            actions.extend(
                r.reconcile_organization_account(
                    manager_client,
                    name=account_name,
                    uid=uid,
                    ou=organization.ou,
                    tags=desired_tags,
                    enterprise_support=enterprise_support,
                    payer_name=payer_uid,
                    dry_run=dry_run,
                ),
            )

            with manager_client.assume_role(
                account_id=uid,
                role=org_role,
            ) as account_client:
                actions.extend(
                    r.reconcile_account(
                        account_client,
                        name=account_name,
                        alias=alias,
                        quotas=quotas,
                        security_contact=security_contact,
                        regions=supported_deployment_regions,
                        dry_run=dry_run,
                    ),
                )
        return actions

    def _reconcile_standalone_account(
        self,
        *,
        client: AWSWorkspaceClient,
        account_name: str,
        alias: str | None,
        quotas: list[AWSQuota],
        security_contact: AWSSecurityContact,
        supported_deployment_regions: list[str],
        dry_run: bool,
    ) -> list[ReconcileAction]:
        """Reconcile a standalone (non-organization) account."""
        return self._reconciler.reconcile_account(
            client,
            name=account_name,
            alias=alias,
            quotas=quotas,
            security_contact=security_contact,
            regions=supported_deployment_regions,
            dry_run=dry_run,
        )
