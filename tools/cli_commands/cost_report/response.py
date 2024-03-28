from decimal import Decimal
from typing import List

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
    values: List[ServiceCostValueResponse]


class CostResponse(BaseModel):
    date: str
    services: List[ServiceCostResponse]


class ReportCostResponse(BaseModel):
    meta: ReportMetaResponse
    data: List[CostResponse]
