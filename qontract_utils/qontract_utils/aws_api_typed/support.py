from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_support import SupportClient


class AWSCase(BaseModel):
    case_id: str = Field(..., alias="caseId")
    subject: str
    status: str


class SupportPlan(Enum):
    BASIC = "basic"
    DEVELOPER = "developer"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


SEVERITY_LEVEL_SUPPORT_PLANS = [
    ("critical", SupportPlan.ENTERPRISE),
    ("urgent", SupportPlan.BUSINESS),
    ("high", SupportPlan.BUSINESS),
    ("normal", SupportPlan.DEVELOPER),
    ("low", SupportPlan.DEVELOPER),
]


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiSupport:
    _hooks: Hooks

    def __init__(self, client: SupportClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="create_case", service="support")
    )
    def create_case(
        self,
        subject: str,
        message: str,
        category: str = "other-account-issues",
        service: str = "customer-account",
        issue_type: Literal["customer-service", "technical"] = "customer-service",
        language: Literal["en", "zh", "ja", "ko"] = "en",
        severity: str = "high",
    ) -> str:
        """Create a support case and return the case id."""
        case = self.client.create_case(
            subject=subject,
            communicationBody=message,
            categoryCode=category,
            serviceCode=service,
            issueType=issue_type,
            language=language,
            severityCode=severity,
        )
        return case["caseId"]

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="describe_case", service="support")
    )
    def describe_case(self, case_id: str) -> AWSCase:
        """Return the status of a support case."""
        case = self.client.describe_cases(caseIdList=[case_id])["cases"][0]
        return AWSCase(**case)

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_support_level", service="support")
    )
    def get_support_level(self) -> SupportPlan:
        """Return the support level of the account."""
        try:
            response = self.client.describe_severity_levels(language="en")
        except self.client.exceptions.ClientError as err:
            if err.response["Error"]["Code"] == "SubscriptionRequiredException":
                return SupportPlan.BASIC
            raise

        severity_levels = {
            level["code"].lower() for level in response["severityLevels"]
        }

        return next(
            (
                support_plan
                for (severity_level, support_plan) in SEVERITY_LEVEL_SUPPORT_PLANS
                if severity_level in severity_levels
            ),
            SupportPlan.BASIC,
        )
