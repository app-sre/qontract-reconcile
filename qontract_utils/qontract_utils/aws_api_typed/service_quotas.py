from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_service_quotas import ServiceQuotasClient
    from mypy_boto3_service_quotas.literals import RequestStatusType
else:
    # pydantic needs these types to be defined during runtime
    RequestStatusType = str


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


class AWSNoSuchResourceError(Exception):
    """Raised when a resource is not found in a service quotas API call."""


class AWSResourceAlreadyExistsError(Exception):
    """Raised when quota increase request already exists."""


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiServiceQuotas:
    _hooks: Hooks

    def __init__(self, client: ServiceQuotasClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="get_requested_service_quota_change", service="service-quotas"
        )
    )
    def get_requested_service_quota_change(
        self, request_id: str
    ) -> AWSRequestedServiceQuotaChange:
        """Return the requested service quota change."""
        req = self.client.get_requested_service_quota_change(RequestId=request_id)
        return AWSRequestedServiceQuotaChange(**req["RequestedQuota"])

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="request_service_quota_change", service="service-quotas"
        )
    )
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
            raise AWSResourceAlreadyExistsError(
                f"Service quota increase request {service_code=}, {quota_code=} already exists."
            ) from None

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_service_quota", service="service-quotas")
    )
    def get_service_quota(self, service_code: str, quota_code: str) -> AWSQuota:
        """Return the current value of the service quota."""
        try:
            quota = self.client.get_service_quota(
                ServiceCode=service_code, QuotaCode=quota_code
            )
            return AWSQuota(**quota["Quota"])
        except self.client.exceptions.NoSuchResourceException:
            raise AWSNoSuchResourceError(
                f"Service quota {service_code=}, {quota_code=} not found."
            ) from None
