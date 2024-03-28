from pydantic import BaseModel

from reconcile.gql_definitions.cost_report.app_names import query
from reconcile.utils.gql import GqlApi


class App(BaseModel):
    name: str
    parent_app_name: str | None


def get_app_names(
    gql_api: GqlApi,
) -> list[App]:
    apps = query(gql_api.query).apps or []
    return [
        App(
            name=app.name,
            parent_app_name=app.parent_app.name if app.parent_app else None,
        )
        for app in apps
    ]
