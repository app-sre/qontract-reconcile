"""AWS account reconciler — pure business logic.

Private methods do the work, public methods compose them.
Returns simple values — the service layer builds action models.
All caching is handled transparently by AWSWorkspaceClient (Layer 2).
"""

from collections.abc import Iterable
from textwrap import dedent

from qontract_utils.aws_api_typed.account import OptStatus
from qontract_utils.aws_api_typed.support import SupportPlan
from qontract_utils.json_utils import json_dumps

from qontract_api.aws.aws_workspace_client import AWSWorkspaceClient
from qontract_api.aws.domain import AWSQuota, AWSSecurityContact
from qontract_api.integrations.aws_account_manager.schemas import (
    ReconcileAction,
    ReconcileActionEnableSupport,
    ReconcileActionMoveOU,
    ReconcileActionRequestQuota,
    ReconcileActionSetAlias,
    ReconcileActionSetRegions,
    ReconcileActionSetSecurityContact,
    ReconcileActionTag,
)
from qontract_api.logger import get_logger
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class AWSReconciler:
    """AWS operations for account creation and reconciliation.

    Pure business logic — caching is handled by the workspace client.
    """

    def __init__(
        self,
        *,
        secret_manager: SecretManager,
    ) -> None:
        self._secret_manager = secret_manager

    # --- Private methods ---

    @staticmethod
    def _create_account(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        email: str,
    ) -> str | None:
        """Create the organization account. Returns the request ID."""
        logger.info("Creating account", account_name=name)
        return aws.create_account(account_name=name, email=email, name=name)

    @staticmethod
    def _describe_account(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        request_id: str,
    ) -> str | None:
        """Check account creation status. Returns the UID if ready, None if in progress."""
        logger.info("Checking account creation status", account_name=name)
        return aws.describe_create_account_status(
            account_name=name,
            request_id=request_id,
        )

    @staticmethod
    def _tag_account(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        uid: str,
        tags: dict[str, str],
        dry_run: bool,
    ) -> bool:
        """Tag the account. Returns True if tags were applied."""
        current_tags = aws.get_tags(name, uid=uid)
        if current_tags == tags:
            return False
        logger.info("Setting tags", account_name=name, tags=tags)
        if not dry_run:
            if current_tags:
                aws.untag_account(uid=uid, tag_keys=list(current_tags.keys()))
            aws.tag_account(account_name=name, uid=uid, tags=tags)
        return True

    @staticmethod
    def _move_account(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        uid: str,
        ou: str,
        payer_name: str | None = None,
        dry_run: bool,
    ) -> bool:
        """Move account to target OU. Returns True if moved."""
        if aws.get_account_ou(name, uid=uid, payer_name=payer_name) == ou:
            return False
        logger.info("Moving account to OU", account_name=name, ou=ou)
        if not dry_run:
            aws.move_account(
                account_name=name,
                uid=uid,
                destination_ou_path=ou,
                payer_name=payer_name,
            )
        return True

    @staticmethod
    def _set_account_alias(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        alias: str | None,
        dry_run: bool,
    ) -> str | None:
        """Set account alias. Returns the alias if set, None if unchanged."""
        desired = alias or name
        if aws.get_account_alias_cached(name) == desired:
            return None
        logger.info("Setting account alias", account_name=name, alias=desired)
        if not dry_run:
            aws.set_account_alias(account_name=name, alias=desired)
        return desired

    @staticmethod
    def _request_quotas(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        quotas: Iterable[AWSQuota],
        dry_run: bool,
    ) -> list[AWSQuota]:
        """Request service quota increases. Returns quotas that were changed."""
        quotas_list = list(quotas)
        desired_json = json_dumps([
            {"sc": q.service_code, "qc": q.quota_code, "v": q.value}
            for q in quotas_list
        ])
        current_json = aws.get_applied_quotas(
            name,
            desired_quotas=[
                (q.service_code, q.quota_code, q.value) for q in quotas_list
            ],
        )
        if current_json == desired_json:
            return []

        changed: list[AWSQuota] = []
        for q in quotas_list:
            current = aws.get_service_quota(
                service_code=q.service_code,
                quota_code=q.quota_code,
            )
            if current.value >= q.value:
                if current.value > q.value:
                    logger.info(
                        "Cannot lower quota, skipping",
                        account_name=name,
                        service_code=q.service_code,
                        quota_code=q.quota_code,
                        current_value=current.value,
                        desired_value=q.value,
                    )
                continue

            logger.info(
                "Requesting quota change",
                account_name=name,
                service_name=current.service_name,
                quota_name=current.quota_name,
                service_code=q.service_code,
                quota_code=q.quota_code,
                current_value=current.value,
                desired_value=q.value,
            )
            changed.append(q)

        if not dry_run:
            aws.apply_quota_changes(
                account_name=name,
                changes=[(q.service_code, q.quota_code, q.value) for q in changed],
                desired_json=desired_json,
            )
        return changed

    @staticmethod
    def _enable_enterprise_support(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        uid: str,
        dry_run: bool,
    ) -> bool:
        """Enable enterprise support. Returns True if action was taken.

        Checks for existing pending case before creating a new one to prevent
        duplicate support cases on repeated runs.
        """
        if aws.get_support_level(name) == SupportPlan.ENTERPRISE:
            return False

        subject = f"Add account {uid} to Enterprise Support"

        # Check for a pending support case before creating a new one
        if case_id := aws.get_support_case_id(name, subject=subject):
            case = aws.describe_support_case(case_id=case_id)
            if case.status == "resolved":
                return False
            logger.info(
                "Enterprise support case still open",
                account_name=name,
                case_id=case_id,
                case_status=case.status,
            )
            return False

        logger.info("Creating enterprise support case", account_name=name)
        if not dry_run:
            aws.create_support_case(
                account_name=name,
                subject=subject,
                message=dedent(f"""
                    Hello AWS,

                    Please enable Enterprise Support on AWS account {uid} and resolve this support case.

                    Thanks.

                    [rh-internal-account-name: {name}]
                """),
            )
        return True

    @staticmethod
    def _check_quota_change_requests(
        aws: AWSWorkspaceClient,
        *,
        name: str,
    ) -> None:
        """Check the status of pending quota change requests.

        Polls each cached request ID and raises on denied/invalid requests.
        Clears the cache once all requests are resolved.
        """
        request_ids = aws.get_quota_request_ids(name)
        if not request_ids:
            return

        logger.info("Checking quota change requests", account_name=name)
        all_resolved = True
        for request_id in request_ids:
            req = aws.get_requested_service_quota_change(request_id=request_id)
            match req.status:
                case "CASE_CLOSED" | "APPROVED":
                    pass
                case "DENIED" | "INVALID_REQUEST" | "NOT_APPROVED":
                    raise RuntimeError(
                        f"Quota change request {request_id} failed: {req.status}",
                    )
                case _:
                    all_resolved = False

        if all_resolved:
            aws.clear_quota_request_ids(name)

    @staticmethod
    def _set_security_contact(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        contact: AWSSecurityContact,
        dry_run: bool,
    ) -> bool:
        """Set security contact. Returns True if set."""
        title = contact.title or contact.name
        desired_json = json_dumps({
            "name": contact.name,
            "title": title,
            "email": contact.email,
            "phone_number": contact.phone_number,
        })
        if aws.get_applied_security_contact(name) == desired_json:
            return False
        logger.info("Setting security contact", account_name=name)
        if not dry_run:
            aws.set_security_contact(
                account_name=name,
                name=contact.name,
                title=title,
                email=contact.email,
                phone_number=contact.phone_number,
            )
        return True

    @staticmethod
    def _set_supported_regions(
        aws: AWSWorkspaceClient,
        *,
        name: str,
        regions: Iterable[str],
        dry_run: bool,
    ) -> tuple[list[str], list[str]]:
        """Set supported regions. Returns (enabled, disabled) region lists."""
        desired = sorted(regions)
        if aws.get_applied_regions(name) == desired:
            return [], []

        aws_regions = aws.list_regions()
        desired_set = set(desired)

        if invalid := desired_set - {r.name for r in aws_regions}:
            raise RuntimeError(f"{name}: Regions {invalid} are not available")

        to_enable = [
            r.name
            for r in aws_regions
            if r.status == OptStatus.DISABLED and r.name in desired_set
        ]
        to_disable = [
            r.name
            for r in aws_regions
            if r.status == OptStatus.ENABLED and r.name not in desired_set
        ]

        if to_enable:
            logger.info("Enabling regions", account_name=name, regions=to_enable)
        if to_disable:
            logger.info("Disabling regions", account_name=name, regions=to_disable)

        if not dry_run:
            aws.apply_region_changes(
                account_name=name,
                to_enable=to_enable,
                to_disable=to_disable,
                desired=desired,
            )
        return to_enable, to_disable

    # --- Public composition methods ---

    def create_organization_account(
        self,
        aws: AWSWorkspaceClient,
        *,
        name: str,
        email: str,
        uid: str | None,
        tags: dict[str, str],
        dry_run: bool,
    ) -> str | None:
        """Create an organization account. Returns UID when complete, None if in progress.

        If uid is provided, skips creation and assume its the account already exists.
        This supports account takeover use cases where the account is created outside of
        this workflow and we just want to onboard it for management and reconciliation.
        """
        if not uid and (
            request_id := self._create_account(aws, name=name, email=email)
        ):
            uid = self._describe_account(aws, name=name, request_id=request_id)

        if uid:
            self._tag_account(
                aws,
                name=name,
                uid=uid,
                tags=tags,
                dry_run=dry_run,
            )
            return uid
        return None

    def create_iam_user(
        self,
        aws: AWSWorkspaceClient,
        *,
        account_name: str,
        user_name: str,
        policy_arn: str,
        vault_path: str,
        dry_run: bool,
    ) -> bool:
        """Create an IAM user in an account. Returns True if created."""
        logger.info("Creating IAM user", account_name=account_name, user_name=user_name)
        if not dry_run:
            if not (
                user := aws.create_user(account_name=account_name, user_name=user_name)
            ):
                return False
            aws.attach_user_policy(
                user_name=user.user_name,
                policy_arn=policy_arn,
            )
            access_key = aws.create_access_key(
                account_name=account_name,
                user_name=user.user_name,
            )

            clean_path = vault_path.format(account_name=account_name).strip("/")
            backend_url = next(iter(self._secret_manager.secret_backends))
            self._secret_manager.write(
                path=clean_path,
                data={
                    "aws_access_key_id": access_key.access_key_id,
                    "aws_secret_access_key": access_key.secret_access_key,
                },
                backend_url=backend_url,
            )
        return True

    def reconcile_organization_account(
        self,
        aws: AWSWorkspaceClient,
        *,
        name: str,
        uid: str,
        ou: str,
        tags: dict[str, str],
        enterprise_support: bool,
        payer_name: str | None = None,
        dry_run: bool,
    ) -> list[ReconcileAction]:
        """Reconcile an account at the organization level (tags, OU)."""
        actions: list[ReconcileAction] = []
        if self._tag_account(aws, name=name, uid=uid, tags=tags, dry_run=dry_run):
            actions.append(ReconcileActionTag(account_name=name, tags=tags))
        if self._move_account(
            aws,
            name=name,
            uid=uid,
            ou=ou,
            payer_name=payer_name,
            dry_run=dry_run,
        ):
            actions.append(ReconcileActionMoveOU(account_name=name, ou=ou))
        if enterprise_support and self._enable_enterprise_support(
            aws, name=name, uid=uid, dry_run=dry_run
        ):
            return [ReconcileActionEnableSupport(account_name=name)]
        return actions

    @staticmethod
    def _validate_quotas(quotas: Iterable[AWSQuota]) -> list[AWSQuota]:
        """Validate and deduplicate quotas. Raises on duplicates."""
        seen: set[tuple[str, str]] = set()
        duplicates: list[str] = []
        validated: list[AWSQuota] = []
        for q in quotas:
            key = (q.service_code, q.quota_code)
            if key in seen:
                duplicates.append(f"{q.service_code}/{q.quota_code}")
            else:
                seen.add(key)
                validated.append(q)
        if duplicates:
            raise ValueError(f"Duplicate quotas: {', '.join(duplicates)}")
        return validated

    def reconcile_account(
        self,
        aws: AWSWorkspaceClient,
        *,
        name: str,
        alias: str | None,
        quotas: Iterable[AWSQuota],
        security_contact: AWSSecurityContact,
        regions: Iterable[str],
        dry_run: bool,
    ) -> list[ReconcileAction]:
        """Reconcile account-level settings (alias, quotas, security contact, regions)."""
        validated_quotas = self._validate_quotas(quotas)
        actions: list[ReconcileAction] = []
        if applied_alias := self._set_account_alias(
            aws,
            name=name,
            alias=alias,
            dry_run=dry_run,
        ):
            actions.append(
                ReconcileActionSetAlias(account_name=name, alias=applied_alias),
            )
        actions.extend(
            ReconcileActionRequestQuota(
                account_name=name,
                service_code=q.service_code,
                quota_code=q.quota_code,
                value=q.value,
            )
            for q in self._request_quotas(
                aws,
                name=name,
                quotas=validated_quotas,
                dry_run=dry_run,
            )
        )
        self._check_quota_change_requests(aws, name=name)
        if self._set_security_contact(
            aws,
            name=name,
            contact=security_contact,
            dry_run=dry_run,
        ):
            actions.append(ReconcileActionSetSecurityContact(account_name=name))
        enabled, disabled = self._set_supported_regions(
            aws,
            name=name,
            regions=regions,
            dry_run=dry_run,
        )
        if enabled or disabled:
            actions.append(
                ReconcileActionSetRegions(
                    account_name=name,
                    enabled=enabled,
                    disabled=disabled,
                ),
            )
        return actions
