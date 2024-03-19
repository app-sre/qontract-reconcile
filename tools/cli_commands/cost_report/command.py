from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel

from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.utils import gql


class Report(BaseModel):
    pass


class CostReportCommand:
    def __init__(self, gql_api: gql.GqlApi) -> None:
        self.gql_api = gql_api

    def execute(self) -> str:
        apps = self.get_apps()
        report = self.get_report(apps)
        return self.render(report)

    def get_apps(self) -> list[App]:
        return get_app_names(self.gql_api)

    def get_report(self, apps: Iterable[App]) -> Report:
        return Report()

    def render(self, report: Report) -> str:
        return ""

    @classmethod
    def create(
        cls,
    ) -> Self:
        return cls(gql.get_api())
