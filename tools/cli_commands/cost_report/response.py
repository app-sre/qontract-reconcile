from decimal import Decimal

from pydantic import BaseModel


class DeltaResponse(BaseModel):
    value: Decimal
    percent: float | None


class MoneyResponse(BaseModel):
    value: Decimal
    units: str


class CostTotalResponse(BaseModel):
    total: MoneyResponse


class TotalMetaResponse(BaseModel):
    cost: CostTotalResponse


class ReportMetaResponse(BaseModel):
    delta: DeltaResponse
    total: TotalMetaResponse


class ServiceCostValueResponse(BaseModel):
    delta_value: Decimal
    delta_percent: float | None
    cost: CostTotalResponse


class ServiceCostResponse(BaseModel):
    service: str
    values: list[ServiceCostValueResponse]


class CostResponse(BaseModel):
    date: str
    services: list[ServiceCostResponse]


class ReportCostResponse(BaseModel):
    meta: ReportMetaResponse
    data: list[CostResponse]


class ProjectCostValueResponse(BaseModel):
    delta_value: Decimal
    delta_percent: float | None
    cost: CostTotalResponse
    clusters: list[str]


class ProjectCostResponse(BaseModel):
    project: str
    values: list[ProjectCostValueResponse]


class OpenShiftCostResponse(BaseModel):
    date: str
    projects: list[ProjectCostResponse]


class OpenShiftReportCostResponse(BaseModel):
    meta: ReportMetaResponse
    data: list[OpenShiftCostResponse]
