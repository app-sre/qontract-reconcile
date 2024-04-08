from decimal import Decimal
from typing import List

from pydantic import BaseModel


class ServiceReport(BaseModel):
    service: str
    delta_value: Decimal
    delta_percent: float | None
    total: Decimal


class ChildAppReport(BaseModel):
    name: str
    total: Decimal


class Report(BaseModel):
    app_name: str
    child_apps: List[ChildAppReport]
    child_apps_total: Decimal
    date: str
    parent_app_name: str | None
    services: List[ServiceReport]
    services_delta_percent: float | None
    services_delta_value: Decimal
    services_total: Decimal
    total: Decimal
