from collections.abc import Callable

import pytest

from reconcile.gql_definitions.status_board.status_board import StatusBoardProductV1
from reconcile.typed_queries.status_board import get_selected_app_data


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


def test_get_selected_app_data(status_board_product):
    app_names = get_selected_app_data(
        ['apps[?@.name=="excluded"]'], status_board_product
    )
    assert app_names == {
        "oof-bar": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
        "bar-oof-bar": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
        "foo": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
    }

    app_names = get_selected_app_data([], status_board_product)
    assert app_names == {
        "excluded": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
        "oof-bar": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
        "bar-oof-bar": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
        "foo": {
            "metadata": {
                "managedBy": "qontract-reconcile",
                "deployment_saas_files": set(),
            }
        },
    }
