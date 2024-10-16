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


class AwsReportCostResponse(BaseModel):
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


class ResourceConfigResponse(BaseModel):
    amount: float | None = None
    format: str | None = None


class ResourceResponse(BaseModel):
    cpu: ResourceConfigResponse
    memory: ResourceConfigResponse


class RecommendationResourcesResponse(BaseModel):
    limits: ResourceResponse
    requests: ResourceResponse


class RecommendationEngineResponse(BaseModel):
    config: RecommendationResourcesResponse
    variation: RecommendationResourcesResponse


class RecommendationEnginesResponse(BaseModel):
    cost: RecommendationEngineResponse
    performance: RecommendationEngineResponse


class RecommendationTermResponse(BaseModel):
    recommendation_engines: RecommendationEnginesResponse | None = None


class RecommendationTermsResponse(BaseModel):
    long_term: RecommendationTermResponse
    medium_term: RecommendationTermResponse
    short_term: RecommendationTermResponse


class RecommendationsResponse(BaseModel):
    current: RecommendationResourcesResponse
    recommendation_terms: RecommendationTermsResponse


class OpenShiftCostOptimizationResponse(BaseModel):
    cluster_alias: str
    cluster_uuid: str
    container: str
    id: str
    project: str
    recommendations: RecommendationsResponse
    workload: str
    workload_type: str


class OpenShiftCostOptimizationReportResponse(BaseModel):
    data: list[OpenShiftCostOptimizationResponse]
