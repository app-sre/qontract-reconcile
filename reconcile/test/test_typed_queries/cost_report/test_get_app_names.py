from collections.abc import Callable

import pytest

from reconcile.gql_definitions.cost_report.app_names import AppNamesQueryData, AppV1
from reconcile.typed_queries.cost_report.app_names import App, get_app_names
from reconcile.utils.gql import GqlApi


def test_get_app_names_when_no_data(
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    gql_api = gql_api_builder({"apps": None})

    apps = get_app_names(gql_api)

    assert apps == []


@pytest.fixture
def parent_app(
    gql_class_factory: Callable[..., AppV1],
) -> AppV1:
    return gql_class_factory(
        AppV1,
        {
            "name": "parent",
        },
    )


@pytest.fixture
def child_app(
    gql_class_factory: Callable[..., AppV1],
) -> AppV1:
    return gql_class_factory(
        AppV1,
        {
            "name": "child",
            "parentApp": {
                "name": "parent",
            },
        },
    )


@pytest.fixture
def apps_response(
    gql_class_factory: Callable[..., AppNamesQueryData],
    parent_app: AppV1,
    child_app: AppV1,
) -> AppNamesQueryData:
    return gql_class_factory(
        AppNamesQueryData,
        {
            "apps": [
                parent_app.model_dump(by_alias=True),
                child_app.model_dump(by_alias=True),
            ],
        },
    )


@pytest.fixture
def expected_apps(
    parent_app: AppV1,
    child_app: AppV1,
) -> list[App]:
    return [
        App(name=parent_app.name, parent_app_name=None),
        App(name=child_app.name, parent_app_name=parent_app.name),
    ]


def test_get_app_names(
    gql_api_builder: Callable[..., GqlApi],
    apps_response: AppNamesQueryData,
    expected_apps: list[App],
) -> None:
    gql_api = gql_api_builder(apps_response.model_dump(by_alias=True))

    apps = get_app_names(gql_api)

    assert apps == expected_apps
