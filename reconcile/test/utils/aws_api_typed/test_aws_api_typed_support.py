from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.support import SUPPORT_PLAN, AWSApiSupport

if TYPE_CHECKING:
    from mypy_boto3_support import SupportClient
else:
    SupportClient = object


@pytest.fixture
def support_client(mocker: MockerFixture) -> SupportClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_support(support_client: SupportClient) -> AWSApiSupport:
    return AWSApiSupport(client=support_client)


def test_aws_api_typed_support_describe_case(
    aws_api_support: AWSApiSupport, support_client: MagicMock
) -> None:
    case_id = "case_id"
    expected_case = {
        "caseId": case_id,
        "subject": "subject",
        "status": "status",
    }
    support_client.describe_cases.return_value = {"cases": [expected_case]}

    case = aws_api_support.describe_case(case_id=case_id)

    assert case.case_id == expected_case["caseId"]
    assert case.subject == expected_case["subject"]
    assert case.status == expected_case["status"]
    support_client.describe_cases.assert_called_once_with(caseIdList=[case_id])


def test_aws_api_typed_support_create_case(
    aws_api_support: AWSApiSupport, support_client: MagicMock
) -> None:
    subject = "subject"
    message = "message"
    category = "other-account-issues"
    service = "customer-account"
    issue_type = "customer-service"
    language = "en"
    severity = "high"
    expected_case_id = "case_id"
    support_client.create_case.return_value = {"caseId": expected_case_id}

    case_id = aws_api_support.create_case(
        subject=subject,
        message=message,
    )

    assert case_id == expected_case_id
    support_client.create_case.assert_called_once_with(
        subject=subject,
        communicationBody=message,
        categoryCode=category,
        serviceCode=service,
        issueType=issue_type,
        language=language,
        severityCode=severity,
    )


@pytest.mark.parametrize(
    "security_levels, expected_support_level",
    [
        ([{"code": "Low"}], SUPPORT_PLAN.DEVELOPER),
        ([{"code": "Low"}, {"code": "Normal"}], SUPPORT_PLAN.DEVELOPER),
        (
            [{"code": "Low"}, {"code": "Normal"}, {"code": "High"}],
            SUPPORT_PLAN.BUSINESS,
        ),
        (
            [{"code": "Low"}, {"code": "Normal"}, {"code": "High"}, {"code": "Urgent"}],
            SUPPORT_PLAN.BUSINESS,
        ),
        (
            [
                {"code": "Low"},
                {"code": "Normal"},
                {"code": "High"},
                {"code": "Urgent"},
                {"code": "Critical"},
            ],
            SUPPORT_PLAN.ENTERPRISE,
        ),
    ],
)
def test_aws_api_typed_support_get_support_level(
    aws_api_support: AWSApiSupport,
    support_client: MagicMock,
    security_levels: list[dict],
    expected_support_level: SUPPORT_PLAN,
) -> None:
    support_client.describe_severity_levels.return_value = {
        "severityLevels": security_levels
    }

    assert aws_api_support.get_support_level() == expected_support_level
