from decimal import Decimal

from pydantic import BaseModel


class ReportItem(BaseModel):
    name: str
    delta_value: Decimal
    delta_percent: float | None
    total: Decimal


class ChildAppReport(BaseModel):
    name: str
    total: Decimal


class Report(BaseModel):
    app_name: str
    child_apps: list[ChildAppReport]
    child_apps_total: Decimal
    date: str
    parent_app_name: str | None
    items: list[ReportItem]
    items_delta_percent: float | None
    items_delta_value: Decimal
    items_total: Decimal
    total: Decimal


class OptimizationReportItem(BaseModel):
    cluster: str
    project: str
    workload: str
    workload_type: str
    container: str
    current_cpu_limit: str | None
    current_cpu_request: str | None
    current_memory_limit: str | None
    current_memory_request: str | None
    recommend_cpu_limit: str | None
    recommend_cpu_request: str | None
    recommend_memory_limit: str | None
    recommend_memory_request: str | None


class OptimizationReport(BaseModel):
    app_name: str
    items: list[OptimizationReportItem]
