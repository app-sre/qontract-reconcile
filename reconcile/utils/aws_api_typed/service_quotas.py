from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_service_quotas import ServiceQuotasClient
    from mypy_boto3_service_quotas.literals import RequestStatusType
else:
    ServiceQuotasClient = RequestStatusType = object


class AWSRequestedServiceQuotaChange(BaseModel):
    id: str = Field(..., alias="Id")
    status: RequestStatusType = Field(..., alias="Status")
    service_code: str = Field(..., alias="ServiceCode")
    quota_code: str = Field(..., alias="QuotaCode")
    desired_value: float = Field(..., alias="DesiredValue")


class AWSQuota(BaseModel):
    service_code: str = Field(..., alias="ServiceCode")
    service_name: str = Field(..., alias="ServiceName")
    quota_code: str = Field(..., alias="QuotaCode")
    quota_name: str = Field(..., alias="QuotaName")
    value: float = Field(..., alias="Value")

    def __str__(self) -> str:
        return f"{self.service_name=} {self.service_code=} {self.quota_name=} {self.quota_code=}: {self.value=}"

    def __repr__(self) -> str:
        return str(self)


class AWSNoSuchResourceException(Exception):
    """Raised when a resource is not found in a service quotas API call."""


class AWSResourceAlreadyExistsException(Exception):
    """Raised when quota increase request already exists."""


class AWSApiServiceQuotas:
    def __init__(self, client: ServiceQuotasClient) -> None:
        self.client = client

    def get_requested_service_quota_change(
        self, request_id: str
    ) -> AWSRequestedServiceQuotaChange:
        """Return the requested service quota change."""
        req = self.client.get_requested_service_quota_change(RequestId=request_id)
        return AWSRequestedServiceQuotaChange(**req["RequestedQuota"])

    def request_service_quota_change(
        self, service_code: str, quota_code: str, desired_value: float
    ) -> AWSRequestedServiceQuotaChange:
        """Request a service quota change."""
        try:
            req = self.client.request_service_quota_increase(
                ServiceCode=service_code,
                QuotaCode=quota_code,
                DesiredValue=desired_value,
            )
            return AWSRequestedServiceQuotaChange(**req["RequestedQuota"])
        except self.client.exceptions.ResourceAlreadyExistsException:
            raise AWSResourceAlreadyExistsException(
                f"Service quota increase request {service_code=}, {quota_code=} already exists."
            ) from None

    def get_service_quota(self, service_code: str, quota_code: str) -> AWSQuota:
        """Return the current value of the service quota."""
        try:
            quota = self.client.get_service_quota(
                ServiceCode=service_code, QuotaCode=quota_code
            )
            return AWSQuota(**quota["Quota"])
        except self.client.exceptions.NoSuchResourceException:
            raise AWSNoSuchResourceException(
                f"Service quota {service_code=}, {quota_code=} not found."
            ) from None
