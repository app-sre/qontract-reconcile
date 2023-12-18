from typing import Callable

import pytest

from reconcile.gql_definitions.status_board.status_board import StatusBoardProductV1
from reconcile.typed_queries.status_board import get_selected_app_names


@pytest.fixture
def status_board_product(
    gql_class_factory: Callable[..., StatusBoardProductV1],
) -> StatusBoardProductV1:
    return gql_class_factory(
        StatusBoardProductV1,
        {
            "appSelectors": {"exclude": ['apps[?@.onboardingStatus!="OnBoarded"]']},
            "productEnvironment": {
                "name": "foo",
                "labels": '{"foo": "foo"}',
                "namespaces": [
                    {
                        "app": {
                            "name": "excluded",
                            "onboardingStatus": "OnBoarded",
                        }
                    },
                    {
                        "app": {
                            "name": "bar",
                            "onboardingStatus": "OnBoarded",
                            "parentApp": {
                                "name": "oof",
                                "onboardingStatus": "OnBoarded",
                            },
                            "childrenApps": [
                                {
                                    "name": "oof-bar",
                                    "onboardingStatus": "OnBoarded",
                                }
                            ],
                        }
                    },
                    {
                        "app": {
                            "name": "baxr",
                            "onboardingStatus": "BestEffort",
                            "parentApp": {
                                "name": "oxof",
                                "onboardingStatus": "OnBoarded",
                            },
                        }
                    },
                    {"app": {"name": "foo", "onboardingStatus": "OnBoarded"}},
                    {"app": {"name": "oof", "onboardingStatus": "BestEffort"}},
                ],
                "product": {
                    "name": "foo",
                },
            },
        },
    )


def test_get_selected_app_names(status_board_product):
    app_names = get_selected_app_names(
        ['apps[?@.name=="excluded"]'], status_board_product
    )
    assert app_names == {"bar-oof-bar", "oof-bar", "foo"}

    app_names = get_selected_app_names([], status_board_product)
    assert app_names == {"excluded", "bar-oof-bar", "oof-bar", "foo"}
