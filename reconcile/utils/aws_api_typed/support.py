from enum import Enum
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_support import SupportClient
else:
    SupportClient = object


class AWSCase(BaseModel):
    case_id: str = Field(..., alias="caseId")
    subject: str
    status: str


class SUPPORT_PLAN(Enum):
    BASIC = "basic"
    DEVELOPER = "developer"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class AWSApiSupport:
    def __init__(self, client: SupportClient) -> None:
        self.client = client

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

    def describe_case(self, case_id: str) -> AWSCase:
        """Return the status of a support case."""
        case = self.client.describe_cases(caseIdList=[case_id])["cases"][0]
        return AWSCase(**case)

    def get_support_level(self) -> SUPPORT_PLAN:
        """Return the support level of the account."""

        try:
            response = self.client.describe_severity_levels(language="en")
        except self.client.exceptions.ClientError as err:
            if err.response["Error"]["Code"] == "SubscriptionRequiredException":
                return SUPPORT_PLAN.BASIC
            raise err

        severity_levels = {
            level["code"].lower() for level in response["severityLevels"]
        }
        if "critical" in severity_levels:
            return SUPPORT_PLAN.ENTERPRISE
        if "urgent" in severity_levels:
            return SUPPORT_PLAN.BUSINESS
        if "high" in severity_levels:
            return SUPPORT_PLAN.BUSINESS
        if "normal" in severity_levels:
            return SUPPORT_PLAN.DEVELOPER
        if "low" in severity_levels:
            return SUPPORT_PLAN.DEVELOPER
        return SUPPORT_PLAN.BASIC
