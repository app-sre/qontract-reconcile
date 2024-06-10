import logging
from collections.abc import Iterable
from textwrap import dedent
from typing import Any, Protocol

from reconcile.aws_account_manager.utils import state_key
from reconcile.utils.aws_api_typed.api import AWSApi
from reconcile.utils.aws_api_typed.iam import (
    AWSAccessKey,
)
from reconcile.utils.aws_api_typed.organization import AwsOrganizationOU
from reconcile.utils.aws_api_typed.service_quotas import (
    AWSResourceAlreadyExistsException,
)
from reconcile.utils.aws_api_typed.support import SUPPORT_PLAN
from reconcile.utils.state import AbortStateTransaction, State

TASK_CREATE_ACCOUNT = "create-account"
TASK_DESCRIBE_ACCOUNT = "describe-account"
TASK_TAG_ACCOUNT = "tag-account"
TASK_MOVE_ACCOUNT = "move-account"
TASK_ACCOUNT_ALIAS = "account-alias"
TASK_CREATE_IAM_USER = "create-iam-user"
TASK_REQUEST_SERVICE_QUOTA = "request-service-quota"
TASK_CHECK_SERVICE_QUOTA_STATUS = "check-service-quota-status"
TASK_ENABLE_ENTERPRISE_SUPPORT = "enable-enterprise-support"
TASK_CHECK_ENTERPRISE_SUPPORT_STATUS = "check-enterprise-support-status"
TASK_SET_SECURITY_CONTACT = "set-security-contact"


class Quota(Protocol):
    service_code: str
    quota_code: str
    value: float

    def dict(self) -> dict[str, Any]: ...


class Contact(Protocol):
    name: str
    title: str | None
    email: str
    phone_number: str

    def dict(self) -> dict[str, Any]: ...


class AWSReconciler:
    def __init__(self, state: State, dry_run: bool) -> None:
        self.state = state
        self.dry_run = dry_run

    def _create_account(
        self,
        aws_api: AWSApi,
        name: str,
        email: str,
    ) -> str | None:
        """Create the organization account and return the creation status ID."""
        with self.state.transaction(state_key(name, TASK_CREATE_ACCOUNT)) as _state:
            if _state.exists:
                # account already exists, nothing to do
                return _state.value

            logging.info(f"Creating account {name}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            status = aws_api.organizations.create_account(email=email, name=name)
            # store the status id for future reference
            _state.value = status.id
            return status.id

    def _org_account_exists(
        self,
        aws_api: AWSApi,
        name: str,
        create_account_request_id: str,
    ) -> str | None:
        """Check if the organization account exists and return its ID."""
        with self.state.transaction(state_key(name, TASK_DESCRIBE_ACCOUNT)) as _state:
            if _state.exists:
                # account checked and exists, nothing to do
                return _state.value

            logging.info(f"Checking account creation status {name}")
            status = aws_api.organizations.describe_create_account_status(
                create_account_request_id=create_account_request_id
            )
            match status.state:
                case "SUCCEEDED":
                    _state.value = status.uid
                    return status.uid
                case "FAILED":
                    raise RuntimeError(
                        f"Account creation failed: {status.failure_reason}"
                    )
                case "IN_PROGRESS":
                    raise AbortStateTransaction("Account creation still in progress")
                case _:
                    raise RuntimeError(
                        f"Unexpected account creation status: {status.state}"
                    )

    def _tag_account(
        self, aws_api: AWSApi, name: str, uid: str, tags: dict[str, str]
    ) -> None:
        with self.state.transaction(state_key(name, TASK_TAG_ACCOUNT)) as _state:
            if _state.exists and _state.value == tags:
                # account already tagged, nothing to do
                return

            logging.info(f"Tagging account {name}: {tags}")
            _state.value = tags
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            if _state.exists:
                aws_api.organizations.untag_resource(
                    resource_id=uid, tag_keys=_state.value.keys()
                )
            aws_api.organizations.tag_resource(resource_id=uid, tags=tags)

    def _get_destination_ou(
        self, aws_api: AWSApi, destination_path: str
    ) -> AwsOrganizationOU:
        org_tree_root = aws_api.organizations.get_organizational_units_tree()
        return org_tree_root.find(destination_path)

    def _move_account(self, aws_api: AWSApi, name: str, uid: str, ou: str) -> None:
        with self.state.transaction(state_key(name, TASK_MOVE_ACCOUNT)) as _state:
            if _state.exists and _state.value == ou:
                # account already moved, nothing to do
                return

            logging.info(f"Moving account {name} to {ou}")
            destination = self._get_destination_ou(aws_api, destination_path=ou)
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            aws_api.organizations.move_account(
                uid=uid,
                destination_parent_id=destination.id,
            )
            _state.value = ou

    def _set_account_alias(self, aws_api: AWSApi, name: str, alias: str | None) -> None:
        """Create an account alias."""
        new_alias = alias or name
        with self.state.transaction(
            state_key(name, TASK_ACCOUNT_ALIAS), new_alias
        ) as _state:
            if _state.exists and _state.value == new_alias:
                return

            logging.info(f"Set account alias '{new_alias}' for {name}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            aws_api.iam.set_account_alias(account_alias=new_alias)

    def _request_quotas(
        self, aws_api: AWSApi, name: str, quotas: Iterable[Quota]
    ) -> list[str] | None:
        """Request service quota changes."""
        quotas_dict = [q.dict() for q in quotas]
        with self.state.transaction(
            state_key(name, TASK_REQUEST_SERVICE_QUOTA)
        ) as _state:
            if _state.exists and _state.value["last_applied_quotas"] == quotas_dict:
                return _state.value["ids"]

            # ATTENTION: reverting previously applied quotas or lowering them is not supported
            new_quotas = []
            for q in quotas:
                quota = aws_api.service_quotas.get_service_quota(
                    service_code=q.service_code, quota_code=q.quota_code
                )
                if quota.value > q.value:
                    # a quota can be already higher than requested, because it was may set manually or enforced by the payer account
                    logging.info(
                        f"Cannot lower quota {q.service_code=}, {q.quota_code=}: {quota.value} -> {q.value}. Skipping."
                    )
                elif quota.value < q.value:
                    quota.value = q.value
                    new_quotas.append(quota)

            for q in new_quotas:
                logging.info(
                    f"Setting quota for {name}: {q.service_name}/{q.quota_name} ({q.service_code}/{q.quota_code}) -> {q.value}"
                )

            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            ids = []
            for new_quota in new_quotas:
                try:
                    req = aws_api.service_quotas.request_service_quota_change(
                        service_code=new_quota.service_code,
                        quota_code=new_quota.quota_code,
                        desired_value=new_quota.value,
                    )
                except AWSResourceAlreadyExistsException:
                    raise AbortStateTransaction(
                        f"A quota increase for this {new_quota.service_code}/{new_quota.quota_code} already exists. Try it again later."
                    )
                ids.append(req.id)

            _state.value = {"last_applied_quotas": quotas_dict, "ids": ids}
            return ids

    def _check_quota_change_requests(
        self,
        aws_api: AWSApi,
        name: str,
        request_ids: Iterable[str],
    ) -> None:
        """Check the status of the quota change requests."""
        with self.state.transaction(
            state_key(name, TASK_CHECK_SERVICE_QUOTA_STATUS)
        ) as _state:
            if _state.exists and _state.value == request_ids:
                return

            logging.info(f"Checking quota change requests for {name}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            _state.value = []
            for request_id in request_ids:
                req = aws_api.service_quotas.get_requested_service_quota_change(
                    request_id=request_id
                )
                match req.status:
                    case "CASE_CLOSED" | "APPROVED":
                        _state.value.append(request_id)
                    case "DENIED" | "INVALID_REQUEST" | "NOT_APPROVED":
                        raise RuntimeError(
                            f"Quota change request {request_id} failed: {req.status}"
                        )
                    case _:
                        # everything else is considered in progress
                        pass

    def _enable_enterprise_support(
        self, aws_api: AWSApi, name: str, uid: str
    ) -> str | None:
        """Enable enterprise support for the account."""
        with self.state.transaction(
            state_key(name, TASK_ENABLE_ENTERPRISE_SUPPORT), ""
        ) as _state:
            if _state.exists:
                return _state.value

            if aws_api.support.get_support_level() == SUPPORT_PLAN.ENTERPRISE:
                if self.dry_run:
                    raise AbortStateTransaction("Dry run")
                return None

            logging.info(f"Enabling enterprise support for {name}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            case_id = aws_api.support.create_case(
                subject=f"Add account {uid} to Enterprise Support",
                message=dedent(f"""
                    Hello AWS,

                    Please enable Enterprise Support on AWS account {uid} and resolve this support case.

                    Thanks.

                    [rh-internal-account-name: {name}]
                """),
            )
            _state.value = case_id
            return case_id

    def _check_enterprise_support_status(self, aws_api: AWSApi, case_id: str) -> None:
        """Check the status of the enterprise support case."""
        with self.state.transaction(
            state_key(case_id, TASK_CHECK_ENTERPRISE_SUPPORT_STATUS), True
        ) as _state:
            if _state.exists:
                return

            logging.info(f"Checking enterprise support case {case_id}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            case = aws_api.support.describe_case(case_id=case_id)
            if case.status == "resolved":
                return

            logging.info(
                f"Enterprise support case {case_id} is still open. Current status: {case.status}"
            )
            raise AbortStateTransaction("Enterprise support case still open")

    def _set_security_contact(
        self,
        aws_api: AWSApi,
        account: str,
        name: str,
        title: str | None,
        email: str,
        phone_number: str,
    ) -> None:
        """Set the security contact for the account."""
        title = title or name
        security_contact = f"{name} {title} {email} {phone_number}"
        with self.state.transaction(
            state_key(account, TASK_SET_SECURITY_CONTACT)
        ) as _state:
            if _state.exists and _state.value == security_contact:
                return

            logging.info(f"Setting security contact for {account}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            aws_api.account.set_security_contact(
                name=name, title=title, email=email, phone_number=phone_number
            )
            _state.value = security_contact

    #
    # Public methods
    #
    def create_organization_account(
        self, aws_api: AWSApi, name: str, email: str
    ) -> str | None:
        """Create an organization account and return the creation status ID."""
        if create_account_request_id := self._create_account(aws_api, name, email):
            if uid := self._org_account_exists(
                aws_api, name, create_account_request_id
            ):
                return uid
        return None

    def create_iam_user(
        self,
        aws_api: AWSApi,
        name: str,
        user_name: str,
        user_policy_arn: str,
    ) -> AWSAccessKey | None:
        """Create an IAM user and return its access key."""
        with self.state.transaction(
            state_key(name, TASK_CREATE_IAM_USER), user_name
        ) as _state:
            if _state.exists and _state.value == user_name:
                return None

            logging.info(f"Creating IAM user '{user_name}' for {name}")
            if self.dry_run:
                raise AbortStateTransaction("Dry run")

            aws_api.iam.create_user(user_name=user_name)
            aws_api.iam.attach_user_policy(
                user_name=user_name,
                policy_arn=user_policy_arn,
            )
            return aws_api.iam.create_access_key(user_name=user_name)

    def reconcile_organization_account(
        self,
        aws_api: AWSApi,
        name: str,
        uid: str,
        ou: str,
        tags: dict[str, str],
        enterprise_support: bool,
    ) -> None:
        """Reconcile the AWS account on the organization level."""
        self._tag_account(aws_api, name, uid, tags)
        self._move_account(aws_api, name, uid, ou)
        if enterprise_support and (
            case_id := self._enable_enterprise_support(aws_api, name, uid)
        ):
            self._check_enterprise_support_status(aws_api, case_id)

    def reconcile_account(
        self,
        aws_api: AWSApi,
        name: str,
        alias: str | None,
        quotas: Iterable[Quota],
        security_contact: Contact,
    ) -> None:
        """Reconcile/update the AWS account. Return the initial user access key if a new user was created."""
        self._set_account_alias(aws_api, name, alias)
        if request_ids := self._request_quotas(aws_api, name, quotas):
            self._check_quota_change_requests(aws_api, name, request_ids)
        self._set_security_contact(
            aws_api,
            account=name,
            name=security_contact.name,
            title=security_contact.title,
            email=security_contact.email,
            phone_number=security_contact.phone_number,
        )
