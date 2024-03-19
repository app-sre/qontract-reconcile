from pydantic import BaseModel


class Delta(BaseModel):
    value: float
    percentage: float


class Money(BaseModel):
    value: float
    units: str


class CostTotal(BaseModel):
    total: Money


class TotalMeta(BaseModel):
    cost: CostTotal


class ReportMeta(BaseModel):
    delta: Delta
    total: TotalMeta


class ServiceCostValue(BaseModel):
    delta_value: float
    delta_percentage: float
    cost: CostTotal


class ServiceCost(BaseModel):
    service: str
    values: list[ServiceCostValue]


class Cost(BaseModel):
    date: str
    services: ServiceCost


class ReportCost(BaseModel):
    meta: ReportMeta
    data: list[Cost]
