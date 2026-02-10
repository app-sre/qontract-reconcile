from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qontract_utils.aws_api_typed.service_quotas import AWSApiServiceQuotas

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from mypy_boto3_service_quotas import ServiceQuotasClient
    from pytest_mock import MockerFixture


@pytest.fixture
def service_quotas_client(mocker: MockerFixture) -> ServiceQuotasClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_service_quotas(
    service_quotas_client: ServiceQuotasClient,
) -> AWSApiServiceQuotas:
    return AWSApiServiceQuotas(client=service_quotas_client)


def test_aws_api_typed_service_quotas_get_requested_service_quota_change(
    aws_api_service_quotas: AWSApiServiceQuotas, service_quotas_client: MagicMock
) -> None:
    service_quotas_client.get_requested_service_quota_change.return_value = {
        "RequestedQuota": {
            "Id": "id",
            "CaseId": "case_id",
            "Status": "PENDING",
            "ServiceCode": "service_code",
            "QuotaCode": "quota_code",
            "DesiredValue": 100.0,
        }
    }
    change = aws_api_service_quotas.get_requested_service_quota_change("id")
    assert change.id == "id"
    assert change.status == "PENDING"
    assert change.service_code == "service_code"
    assert change.quota_code == "quota_code"
    assert change.desired_value == 100.0


def test_aws_api_typed_service_quotas_request_service_quota_change(
    aws_api_service_quotas: AWSApiServiceQuotas, service_quotas_client: MagicMock
) -> None:
    service_quotas_client.request_service_quota_increase.return_value = {
        "RequestedQuota": {
            "Id": "id",
            "CaseId": "case_id",
            "Status": "PENDING",
            "ServiceCode": "service_code",
            "QuotaCode": "quota_code",
            "DesiredValue": 100.0,
        }
    }
    change = aws_api_service_quotas.request_service_quota_change(
        "service_code", "quota_code", 100.0
    )
    assert change.id == "id"
    assert change.status == "PENDING"
    assert change.service_code == "service_code"
    assert change.quota_code == "quota_code"
    assert change.desired_value == 100.0


def test_aws_api_typed_service_quotas_get_service_quota(
    aws_api_service_quotas: AWSApiServiceQuotas, service_quotas_client: MagicMock
) -> None:
    service_quotas_client.get_service_quota.return_value = {
        "Quota": {
            "ServiceCode": "service_code",
            "ServiceName": "service_name",
            "QuotaCode": "quota_code",
            "QuotaName": "quota_name",
            "Value": 100.0,
        }
    }
    quota = aws_api_service_quotas.get_service_quota("service_code", "quota_code")
    assert quota.service_code == "service_code"
    assert quota.service_name == "service_name"
    assert quota.quota_code == "quota_code"
    assert quota.quota_name == "quota_name"
    assert quota.value == 100.0
