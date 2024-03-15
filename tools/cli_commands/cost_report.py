from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel

from reconcile.typed_queries.cost_report.app_names import App


class Report(BaseModel):
    pass


class CostReportCommand:
    def execute(self) -> str:
        apps = self.get_apps()
        report = self.get_report(apps)
        return self.render(report)

    def get_apps(self) -> list[App]:
        return []

    def get_report(self, apps: Iterable[App]) -> Report:
        return Report()

    def render(self, report: Report) -> str:
        return ""

    @classmethod
    def create(
        cls,
    ) -> Self:
        return cls()
