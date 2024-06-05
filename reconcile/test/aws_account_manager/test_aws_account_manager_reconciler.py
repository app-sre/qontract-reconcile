from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_s3

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = object
from pytest_mock import MockerFixture

from reconcile.aws_account_manager.reconciler import (
    TASK_ACCOUNT_ALIAS,
    TASK_CHECK_ENTERPRISE_SUPPORT_STATUS,
    TASK_CHECK_SERVICE_QUOTA_STATUS,
    TASK_CREATE_ACCOUNT,
    TASK_CREATE_IAM_USER,
    TASK_DESCRIBE_ACCOUNT,
    TASK_ENABLE_ENTERPRISE_SUPPORT,
    TASK_MOVE_ACCOUNT,
    TASK_REQUEST_SERVICE_QUOTA,
    TASK_SET_SECURITY_CONTACT,
    TASK_TAG_ACCOUNT,
    AWSReconciler,
)
from reconcile.aws_account_manager.utils import state_key
from reconcile.gql_definitions.fragments.aws_account_managed import (
    AwsContactV1,
    AWSQuotaV1,
)
from reconcile.utils.aws_api_typed.iam import (
    AWSAccessKey,
    AWSEntityAlreadyExistsException,
)
from reconcile.utils.aws_api_typed.organization import (
    AWSAccountStatus,
    AwsOrganizationOU,
)
from reconcile.utils.aws_api_typed.service_quotas import (
    AWSQuota,
    AWSRequestedServiceQuotaChange,
)
from reconcile.utils.aws_api_typed.support import SUPPORT_PLAN, AWSCase
from reconcile.utils.state import State


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Generator[S3Client, None, None]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", "BUCKET")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", "ACCOUNT")

    with mock_s3():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="BUCKET")
        yield s3_client


@pytest.fixture
def state(s3_client: S3Client) -> State:
    return State(integration="integration", bucket="BUCKET", client=s3_client)


@pytest.fixture
def state_exists(state: State) -> Callable:
    def _set(key: str, value: Any) -> None:
        state[key] = value

    return _set


@pytest.fixture
def reconciler(mocker: MockerFixture, state: State) -> AWSReconciler:
    return AWSReconciler(state=state, dry_run=False)


@pytest.fixture
def reconciler_dry_run(mocker: MockerFixture, state: State) -> AWSReconciler:
    return AWSReconciler(state=state, dry_run=True)


def test_aws_account_manager_reconcile_create_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.organizations.create_account.return_value = AWSAccountStatus(
        Id="id", AccountName="account", State="PENDING"
    )
    assert reconciler._create_account(aws_api, "account", "email@email.com") == "id"
    aws_api.organizations.create_account.assert_called_once()


def test_aws_account_manager_reconcile_create_account_state_exists(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_CREATE_ACCOUNT), "id")
    assert reconciler._create_account(aws_api, "account", "email@email.com") == "id"
    aws_api.organizations.create_account.assert_not_called()


def test_aws_account_manager_reconcile_create_account_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    assert (
        reconciler_dry_run._create_account(aws_api, "account", "email@email.com")
        is None
    )
    aws_api.organizations.create_account.assert_not_called()


def test_aws_account_manager_reconcile_org_account_exists_succeeded(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.organizations.describe_create_account_status.return_value = (
        AWSAccountStatus(
            Id="ID123456",
            AccountName="account",
            AccountId="123456789012",
            State="SUCCEEDED",
        )
    )
    assert (
        reconciler._org_account_exists(aws_api, "account", "ID123456") == "123456789012"
    )
    aws_api.organizations.describe_create_account_status.assert_called_once()


def test_aws_account_manager_reconcile_org_account_exists_in_progress(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.organizations.describe_create_account_status.return_value = (
        AWSAccountStatus(
            Id="ID123456",
            AccountName="account",
            State="IN_PROGRESS",
        )
    )
    assert reconciler._org_account_exists(aws_api, "account", "ID123456") is None
    aws_api.organizations.describe_create_account_status.assert_called_once()


def test_aws_account_manager_reconcile_org_account_exists_errors(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.organizations.describe_create_account_status.return_value = (
        AWSAccountStatus(
            Id="ID123456",
            AccountName="account",
            State="FAILED",
        )
    )
    with pytest.raises(RuntimeError):
        reconciler._org_account_exists(aws_api, "account", "ID123456")

    aws_api.organizations.describe_create_account_status.return_value = (
        AWSAccountStatus(
            Id="ID123456",
            AccountName="account",
            State="UNKNOWN",
        )
    )
    with pytest.raises(RuntimeError):
        reconciler._org_account_exists(aws_api, "account", "ID123456")


def test_aws_account_manager_reconcile_org_account_exists_state_exists(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_DESCRIBE_ACCOUNT), "id")
    assert reconciler._org_account_exists(aws_api, "account", "ID123456") == "id"
    aws_api.organizations.describe_create_account_status.assert_not_called()


def test_aws_account_manager_reconcile_tag_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._tag_account(aws_api, "account", "123456789012", {"new": "tag"})

    aws_api.organizations.tag_resource.assert_called_once_with(
        resource_id="123456789012",
        tags={"new": "tag"},
    )
    aws_api.organizations.untag_resource.assert_not_called()


def test_aws_account_manager_reconcile_tag_account_state_exists_and_is_tagged(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_TAG_ACCOUNT), {"new": "tag"})
    reconciler._tag_account(aws_api, "account", "123456789012", {"new": "tag"})

    aws_api.organizations.tag_resource.assert_not_called()
    aws_api.organizations.untag_resource.assert_not_called()


def test_aws_account_manager_reconcile_tag_account_state_exists_and_needs_update(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_TAG_ACCOUNT), {"foo": "bar"})
    reconciler._tag_account(aws_api, "account", "123456789012", {"new": "tag"})

    aws_api.organizations.untag_resource(aws_api, ["default", "new"])
    aws_api.organizations.tag_resource.assert_called_once_with(
        resource_id="123456789012",
        tags={"new": "tag"},
    )


def test_aws_account_manager_reconcile_tag_account_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run._tag_account(aws_api, "account", "123456789012", {"new": "tag"})
    aws_api.organizations.tag_resource.assert_not_called()
    aws_api.organizations.untag_resource.assert_not_called()


def test_aws_account_manager_reconcile_get_destination_ou(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.organizations.get_organizational_units_tree.return_value = (
        AwsOrganizationOU(
            Id="ou-123456",
            Arn="arn",
            Name="Root",
            children=[AwsOrganizationOU(Id="ou-123457", Arn="arn", Name="ou")],
        )
    )
    ou = reconciler._get_destination_ou(aws_api, "/Root/ou")
    assert ou.name == "ou"

    with pytest.raises(KeyError):
        reconciler._get_destination_ou(aws_api, "/not/found")


def test_aws_account_manager_reconcile_move_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._get_destination_ou = MagicMock(  # type: ignore
        return_value=AwsOrganizationOU(Id="ou-123457", Arn="arn", Name="ou")
    )

    reconciler._move_account(aws_api, "account", "123456789012", "ou")
    aws_api.organizations.move_account.assert_called_once_with(
        uid="123456789012", destination_parent_id="ou-123457"
    )


def test_aws_account_manager_reconcile_move_account_state_exists_and_in_right_ou(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_MOVE_ACCOUNT), "ou")
    reconciler._move_account(aws_api, "account", "123456789012", "ou")
    aws_api.organizations.move_account.assert_not_called()


def test_aws_account_manager_reconcile_move_account_state_exists_and_needs_move(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    reconciler._get_destination_ou = MagicMock(  # type: ignore
        return_value=AwsOrganizationOU(Id="ou-123457", Arn="arn", Name="ou")
    )
    state_exists(state_key("account", TASK_MOVE_ACCOUNT), "somewhere-else")
    reconciler._move_account(aws_api, "account", "123456789012", "ou")
    aws_api.organizations.move_account.assert_called_once_with(
        uid="123456789012", destination_parent_id="ou-123457"
    )


def test_aws_account_manager_reconcile_move_account_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run._move_account(aws_api, "account", "123456789012", "ou")
    aws_api.organizations.move_account.assert_not_called()


def test_aws_account_manager_reconcile_set_account_alias(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._set_account_alias(aws_api, "account", "alias")
    aws_api.iam.set_account_alias.assert_called_once_with(account_alias="alias")


def test_aws_account_manager_reconcile_set_account_alias_name(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._set_account_alias(aws_api, "account", None)
    aws_api.iam.set_account_alias.assert_called_once_with(account_alias="account")


def test_aws_account_manager_reconcile_set_account_alias_state_exists_and_already_set(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_ACCOUNT_ALIAS), "alias")
    reconciler._set_account_alias(aws_api, "account", "alias")
    aws_api.iam.set_account_alias.assert_not_called()


def test_aws_account_manager_reconcile_set_account_alias_state_exists_and_needs_update(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_ACCOUNT_ALIAS), "whatever")
    reconciler._set_account_alias(aws_api, "account", "alias")
    aws_api.iam.set_account_alias.assert_called_once()


def test_aws_account_manager_reconcile_set_account_alias_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run._set_account_alias(aws_api, "account", "alias")
    aws_api.iam.set_account_alias.assert_not_called()


def test_aws_account_manager_reconcile_request_quotas(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.service_quotas.get_service_quota.side_effect = [
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeA",
            QuotaName="Quota A",
            Value=1.0,
        ),
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeB",
            QuotaName="Quota B",
            Value=1.0,
        ),
    ]
    aws_api.service_quotas.request_service_quota_change.side_effect = [
        AWSRequestedServiceQuotaChange(
            Id="id1",
            Status="PENDING",
            ServiceCode="serviceA",
            QuotaCode="codeA",
            DesiredValue=2.0,
        ),
        AWSRequestedServiceQuotaChange(
            Id="id2",
            Status="PENDING",
            ServiceCode="serviceA",
            QuotaCode="codeB",
            DesiredValue=2.0,
        ),
    ]
    assert reconciler._request_quotas(
        aws_api,
        "account",
        quotas=[
            AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=2.0),
            AWSQuotaV1(serviceCode="serviceA", quotaCode="codeB", value=2.0),
        ],
    ) == ["id1", "id2"]


def test_aws_account_manager_reconcile_request_quotas_nothing_to_change(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.service_quotas.get_service_quota.side_effect = [
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeA",
            QuotaName="Quota A",
            Value=1.0,
        ),
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeB",
            QuotaName="Quota B",
            Value=1.0,
        ),
    ]
    assert (
        reconciler._request_quotas(
            aws_api,
            "account",
            quotas=[
                # already at the desired default value
                AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=1.0),
                AWSQuotaV1(serviceCode="serviceA", quotaCode="codeB", value=1.0),
            ],
        )
        == []
    )
    aws_api.service_quotas.request_service_quota_change.assert_not_called()


def test_aws_account_manager_reconcile_request_quotas_state_exists_all_done(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    q = AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=2.0)
    state_exists(
        state_key("account", TASK_REQUEST_SERVICE_QUOTA),
        {"last_applied_quotas": [q.dict()], "ids": ["id1"]},
    )

    assert reconciler._request_quotas(aws_api, "account", quotas=[q]) == ["id1"]
    aws_api.service_quotas.request_service_quota_change.assert_not_called()


def test_aws_account_manager_reconcile_request_quotas_state_exists_but_outdated(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    q = AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=2.0)
    q2 = AWSQuotaV1(serviceCode="serviceA", quotaCode="codeB", value=2.0)
    state_exists(
        state_key("account", TASK_REQUEST_SERVICE_QUOTA),
        {"last_applied_quotas": [q.dict()], "ids": ["id1"]},
    )
    aws_api.service_quotas.get_service_quota.side_effect = [
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeA",
            QuotaName="Quota A",
            Value=2.0,
        ),
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeB",
            QuotaName="Quota B",
            Value=1.0,
        ),
    ]
    aws_api.service_quotas.request_service_quota_change.return_value = (
        AWSRequestedServiceQuotaChange(
            Id="id2",
            Status="PENDING",
            ServiceCode="serviceA",
            QuotaCode="codeB",
            DesiredValue=2.0,
        )
    )

    assert reconciler._request_quotas(aws_api, "account", quotas=[q, q2]) == ["id2"]
    aws_api.service_quotas.request_service_quota_change.assert_called_once_with(
        service_code="serviceA", quota_code="codeB", desired_value=2.0
    )


def test_aws_account_manager_reconcile_request_quotas_state_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    q = AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=2.0)

    aws_api.service_quotas.get_service_quota.side_effect = [
        AWSQuota(
            ServiceCode="serviceA",
            ServiceName="Service A",
            QuotaCode="codeA",
            QuotaName="Quota A",
            Value=1.0,
        )
    ]

    assert reconciler_dry_run._request_quotas(aws_api, "account", quotas=[q]) is None
    aws_api.service_quotas.request_service_quota_change.assert_not_called()


def test_aws_account_manager_reconcile_check_quota_change_requests_pending(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.service_quotas.get_requested_service_quota_change.return_value = (
        AWSRequestedServiceQuotaChange(
            Id="id1",
            Status="PENDING",
            ServiceCode="serviceA",
            QuotaCode="codeA",
            DesiredValue=2.0,
        )
    )

    reconciler._check_quota_change_requests(aws_api, "account", ["id1"])
    aws_api.service_quotas.get_requested_service_quota_change.assert_called_once()


def test_aws_account_manager_reconcile_check_quota_change_requests_closed(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.service_quotas.get_requested_service_quota_change.return_value = (
        AWSRequestedServiceQuotaChange(
            Id="id1",
            Status="CASE_CLOSED",
            ServiceCode="serviceA",
            QuotaCode="codeA",
            DesiredValue=2.0,
        )
    )

    reconciler._check_quota_change_requests(aws_api, "account", ["id1"])
    aws_api.service_quotas.get_requested_service_quota_change.assert_called_once()


def test_aws_account_manager_reconcile_check_quota_change_requests_error(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.service_quotas.get_requested_service_quota_change.return_value = (
        AWSRequestedServiceQuotaChange(
            Id="id1",
            Status="DENIED",
            ServiceCode="serviceA",
            QuotaCode="codeA",
            DesiredValue=2.0,
        )
    )
    with pytest.raises(RuntimeError):
        reconciler._check_quota_change_requests(aws_api, "account", ["id1"])


def test_aws_account_manager_reconcile_check_quota_change_requests_state_exists_all_done(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_CHECK_SERVICE_QUOTA_STATUS), ["id1"])
    reconciler._check_quota_change_requests(aws_api, "account", ["id1"])
    aws_api.service_quotas.get_requested_service_quota_change.assert_not_called()


def test_aws_account_manager_reconcile_check_quota_change_requests_state_exists_but_different(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_CHECK_SERVICE_QUOTA_STATUS), ["id1"])
    aws_api.service_quotas.get_requested_service_quota_change.return_value = (
        AWSRequestedServiceQuotaChange(
            Id="id2",
            Status="APPROVED",
            ServiceCode="serviceA",
            QuotaCode="codeA",
            DesiredValue=2.0,
        )
    )
    reconciler._check_quota_change_requests(aws_api, "account", ["id2"])
    aws_api.service_quotas.get_requested_service_quota_change.assert_called_once()


def test_aws_account_manager_reconcile_enable_enterprise_support(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.support.get_support_level.return_value = SUPPORT_PLAN.BASIC
    aws_api.support.create_case.return_value = "case-id"
    assert (
        reconciler._enable_enterprise_support(aws_api, "account", "123456789012")
        == "case-id"
    )
    aws_api.support.create_case.assert_called_once()


def test_aws_account_manager_reconcile_enable_enterprise_support_already_enabled(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.support.get_support_level.return_value = SUPPORT_PLAN.ENTERPRISE
    assert (
        reconciler._enable_enterprise_support(aws_api, "account", "123456789012")
        is None
    )
    aws_api.support.create_case.assert_not_called()


def test_aws_account_manager_reconcile_enable_enterprise_support_state_exists(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_ENABLE_ENTERPRISE_SUPPORT), "case-id")
    assert (
        reconciler._enable_enterprise_support(aws_api, "account", "123456789012")
        == "case-id"
    )
    aws_api.support.create_case.assert_not_called()


def test_aws_account_manager_reconcile_enable_enterprise_support_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    assert (
        reconciler_dry_run._enable_enterprise_support(
            aws_api, "account", "123456789012"
        )
        is None
    )
    aws_api.support.create_case.assert_not_called()


def test_aws_account_manager_reconcile_check_enterprise_support_status(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.support.describe_case.return_value = AWSCase(
        caseId="case-id", subject="foobar", status="resolved"
    )
    reconciler._check_enterprise_support_status(aws_api, "case-id")
    aws_api.support.describe_case.assert_called_once()


def test_aws_account_manager_reconcile_check_enterprise_support_status_state_exists(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("case-id", TASK_CHECK_ENTERPRISE_SUPPORT_STATUS), True)
    reconciler._check_enterprise_support_status(aws_api, "case-id")
    aws_api.support.describe_case.assert_not_called()


def test_aws_account_manager_reconcile_check_enterprise_support_status_state_exists_but_different(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("another-id", TASK_CHECK_ENTERPRISE_SUPPORT_STATUS), True)
    reconciler._check_enterprise_support_status(aws_api, "case-id")
    aws_api.support.describe_case.assert_called_once()


def test_aws_account_manager_reconcile_check_enterprise_support_status_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run._check_enterprise_support_status(aws_api, "case-id")
    aws_api.support.describe_case.assert_not_called()


def test_aws_account_manager_reconcile_set_security_contact(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._set_security_contact(
        aws_api, "account", "name", "title", "email", "phone"
    )

    aws_api.account.set_security_contact.assert_called_once_with(
        name="name", title="title", email="email", phone_number="phone"
    )


def test_aws_account_manager_reconcile_set_security_contact_state_exists_and_up2date(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(
        state_key("account", TASK_SET_SECURITY_CONTACT),
        "name title email phone",
    )
    reconciler._set_security_contact(
        aws_api, "account", "name", "title", "email", "phone"
    )

    aws_api.account.set_security_contact.assert_not_called()


def test_aws_account_manager_reconcile_set_security_contact_state_exists_and_needs_update(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_SET_SECURITY_CONTACT), "whatever")
    reconciler._set_security_contact(
        aws_api, "account", "name", "title", "email", "phone"
    )

    aws_api.account.set_security_contact.assert_called_once_with(
        name="name", title="title", email="email", phone_number="phone"
    )


def test_aws_account_manager_reconcile_set_security_contact_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run._set_security_contact(
        aws_api, "account", "name", "title", "email", "phone"
    )
    aws_api.account.set_security_contact.assert_not_called()


#
# Public methods
#


def test_aws_account_manager_reconcile_create_organization_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._create_account = MagicMock(return_value="id")  # type: ignore
    reconciler._org_account_exists = MagicMock(return_value="uid")  # type: ignore
    reconciler.create_organization_account(aws_api, "account", "email") == "uid"


def test_aws_account_manager_reconcile_create_organization_account_no_request(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._create_account = MagicMock(return_value=None)  # type: ignore
    reconciler._org_account_exists = MagicMock(return_value="uid")  # type: ignore
    reconciler.create_organization_account(aws_api, "account", "email") is None
    reconciler._org_account_exists.assert_not_called()


def test_aws_account_manager_reconcile_create_organization_account_not_created_yet(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._create_account = MagicMock(return_value="id")  # type: ignore
    reconciler._org_account_exists = MagicMock(return_value=None)  # type: ignore
    reconciler.create_organization_account(aws_api, "account", "email") is None


def test_aws_account_manager_reconcile_create_iam_user(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.iam.create_access_key.return_value = AWSAccessKey(
        AccessKeyId="key-id", SecretAccessKey="secret-key"
    )
    access_key = reconciler.create_iam_user(
        aws_api, "account", "user-name", "policy-arn"
    )
    assert access_key
    assert access_key.access_key_id == "key-id"
    assert access_key.secret_access_key == "secret-key"
    aws_api.iam.create_user.assert_called_once_with(user_name="user-name")
    aws_api.iam.attach_user_policy.assert_called_once_with(
        user_name="user-name", policy_arn="policy-arn"
    )
    aws_api.iam.create_access_key.assert_called_once_with(user_name="user-name")


def test_aws_account_manager_reconcile_create_iam_user_state_exists_and_done(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_CREATE_IAM_USER), "user-name")
    assert (
        reconciler.create_iam_user(aws_api, "account", "user-name", "policy-arn")
        is None
    )
    aws_api.iam.create_user.assert_not_called()
    aws_api.iam.attach_user_policy.assert_not_called()
    aws_api.iam.create_access_key.assert_not_called()


def test_aws_account_manager_reconcile_create_iam_user_state_exists_and_other_user(
    aws_api: MagicMock, reconciler: AWSReconciler, state_exists: Callable
) -> None:
    state_exists(state_key("account", TASK_CREATE_IAM_USER), "some-other-user")
    aws_api.iam.create_access_key.return_value = AWSAccessKey(
        AccessKeyId="key-id", SecretAccessKey="secret-key"
    )
    assert reconciler.create_iam_user(aws_api, "account", "user-name", "policy-arn")
    aws_api.iam.create_user.assert_called_once()
    aws_api.iam.attach_user_policy.assert_called_once()
    aws_api.iam.create_access_key.assert_called_once()


def test_aws_account_manager_reconcile_create_iam_user_dry_run(
    aws_api: MagicMock, reconciler_dry_run: AWSReconciler
) -> None:
    reconciler_dry_run.create_iam_user(aws_api, "account", "user-name", "policy-arn")
    aws_api.iam.create_user.assert_not_called()
    aws_api.iam.attach_user_policy.assert_not_called()
    aws_api.iam.create_access_key.assert_not_called()


def test_aws_account_manager_reconcile_create_iam_user_alredy_exists(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    aws_api.iam.create_user.side_effect = AWSEntityAlreadyExistsException(
        "User already exists"
    )
    with pytest.raises(AWSEntityAlreadyExistsException):
        reconciler.create_iam_user(aws_api, "account", "user-name", "policy-arn")


def test_aws_account_manager_reconcile_reconcile_organization_account_no_enterprise_support(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._tag_account = MagicMock()  # type: ignore
    reconciler._move_account = MagicMock()  # type: ignore
    reconciler._enable_enterprise_support = MagicMock()  # type: ignore
    reconciler._check_enterprise_support_status = MagicMock()  # type: ignore
    reconciler.reconcile_organization_account(
        aws_api,
        "account",
        "uid",
        "ou",
        {"new": "tag"},
        enterprise_support=False,
    )
    reconciler._tag_account.assert_called_once()
    reconciler._move_account.assert_called_once()
    reconciler._enable_enterprise_support.assert_not_called()
    reconciler._check_enterprise_support_status.assert_not_called()


def test_aws_account_manager_reconcile_reconcile_organization_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._tag_account = MagicMock()  # type: ignore
    reconciler._move_account = MagicMock()  # type: ignore
    reconciler._enable_enterprise_support = MagicMock(return_value="case-id")  # type: ignore
    reconciler._check_enterprise_support_status = MagicMock()  # type: ignore
    reconciler.reconcile_organization_account(
        aws_api,
        "account",
        "uid",
        "ou",
        {"new": "tag"},
        enterprise_support=True,
    )
    reconciler._tag_account.assert_called_once()
    reconciler._move_account.assert_called_once()
    reconciler._enable_enterprise_support.assert_called_once()
    reconciler._check_enterprise_support_status.assert_called_once()


def test_aws_account_manager_reconcile_reconcile_organization_account_no_case_id(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._tag_account = MagicMock()  # type: ignore
    reconciler._move_account = MagicMock()  # type: ignore
    reconciler._enable_enterprise_support = MagicMock(return_value=None)  # type: ignore
    reconciler._check_enterprise_support_status = MagicMock()  # type: ignore
    reconciler.reconcile_organization_account(
        aws_api,
        "account",
        "uid",
        "ou",
        {"new": "tag"},
        enterprise_support=True,
    )
    reconciler._tag_account.assert_called_once()
    reconciler._move_account.assert_called_once()
    reconciler._enable_enterprise_support.assert_called_once()
    reconciler._check_enterprise_support_status.assert_not_called()


def test_aws_account_manager_reconcile_reconcile_account(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._set_account_alias = MagicMock()  # type: ignore
    reconciler._request_quotas = MagicMock(return_value=["id1"])  # type: ignore
    reconciler._check_quota_change_requests = MagicMock()  # type: ignore
    reconciler._set_security_contact = MagicMock()  # type: ignore

    reconciler.reconcile_account(
        aws_api,
        "account",
        "alias",
        quotas=[AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=1.0)],
        security_contact=AwsContactV1(
            name="name", title="title", email="email", phoneNumber="phone"
        ),
    )
    reconciler._set_account_alias.assert_called_once()
    reconciler._request_quotas.assert_called_once()
    reconciler._check_quota_change_requests.assert_called_once()
    reconciler._set_security_contact.assert_called_once()


def test_aws_account_manager_reconcile_reconcile_account_no_initial_user(
    aws_api: MagicMock, reconciler: AWSReconciler
) -> None:
    reconciler._set_account_alias = MagicMock()  # type: ignore
    reconciler._request_quotas = MagicMock(return_value=["id1"])  # type: ignore
    reconciler._check_quota_change_requests = MagicMock()  # type: ignore
    reconciler._set_security_contact = MagicMock()  # type: ignore

    reconciler.reconcile_account(
        aws_api,
        "account",
        "alias",
        quotas=[AWSQuotaV1(serviceCode="serviceA", quotaCode="codeA", value=1.0)],
        security_contact=AwsContactV1(
            name="name", title="title", email="email", phoneNumber="phone"
        ),
    )
    reconciler._set_account_alias.assert_called_once()
    reconciler._request_quotas.assert_called_once()
    reconciler._check_quota_change_requests.assert_called_once()
    reconciler._set_security_contact.assert_called_once()
