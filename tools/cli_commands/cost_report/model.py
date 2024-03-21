from decimal import Decimal
from typing import List

from pydantic import BaseModel


class ServiceReport(BaseModel):
    service: str
    delta_value: Decimal
    delta_percentage: float
    total: Decimal


class Report(BaseModel):
    app_name: str
    child_apps: List[str]
    child_apps_total: Decimal
    parent_app_name: str | None
    services: List[ServiceReport]
    services_delta_percentage: float
    services_delta_value: Decimal
    services_total: Decimal
    total: Decimal
