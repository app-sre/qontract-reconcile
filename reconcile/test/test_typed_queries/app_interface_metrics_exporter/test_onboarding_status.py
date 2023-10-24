from collections import Counter
from collections.abc import Callable

import pytest

from reconcile.gql_definitions.app_interface_metrics_exporter.onboarding_status import (
    AppV1,
    OnboardingStatusQueryData,
)
from reconcile.typed_queries.app_interface_metrics_exporter.onboarding_status import (
    get_onboarding_status,
)
from reconcile.utils.gql import GqlApi


@pytest.fixture
def onboarded_app(
    gql_class_factory: Callable[..., AppV1],
) -> AppV1:
    return gql_class_factory(
        AppV1,
        {
            "onboardingStatus": "OnBoarded",
        },
    )


@pytest.fixture
def inprogress_app(
    gql_class_factory: Callable[..., AppV1],
) -> AppV1:
    return gql_class_factory(
        AppV1,
        {
            "onboardingStatus": "InProgress",
        },
    )


@pytest.fixture
def apps(
    gql_class_factory: Callable[..., OnboardingStatusQueryData],
    onboarded_app: AppV1,
    inprogress_app: AppV1,
) -> OnboardingStatusQueryData:
    return gql_class_factory(
        OnboardingStatusQueryData,
        {
            "apps": [
                onboarded_app.dict(by_alias=True),
                onboarded_app.dict(by_alias=True),
                inprogress_app.dict(by_alias=True),
            ],
        },
    )


def test_get_onboarding_status(
    gql_api_builder: Callable[..., GqlApi],
    apps: OnboardingStatusQueryData,
) -> None:
    gql_api = gql_api_builder(apps.dict(by_alias=True))

    result = get_onboarding_status(gql_api)

    assert result == Counter({"OnBoarded": 2, "InProgress": 1})


def test_get_onboarding_status_with_emtpy_data(
    gql_api_builder: Callable[..., GqlApi],
    apps: OnboardingStatusQueryData,
) -> None:
    gql_api = gql_api_builder({"apps": None})

    result = get_onboarding_status(gql_api)

    assert result == Counter()
