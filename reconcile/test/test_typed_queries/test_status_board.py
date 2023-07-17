import pytest

from reconcile.gql_definitions.status_board.status_board import (
    AppV1,
    EnvironmentV1,
    NamespaceV1,
    ProductV1,
    StatusBoardProductV1,
    StatusBoardProductV1_StatusBoardAppSelectorV1,
)
from reconcile.typed_queries.status_board import get_selected_app_names


@pytest.fixture
def status_board_product():
    return StatusBoardProductV1(
        appSelectors=StatusBoardProductV1_StatusBoardAppSelectorV1(
            exclude=['apps[?@.onboardingStatus!="OnBoarded"]'],
        ),
        productEnvironment=EnvironmentV1(
            name="foo",
            labels='{"foo": "foo"}',
            namespaces=[
                NamespaceV1(app=AppV1(name="excluded", onboardingStatus="OnBoarded")),
                NamespaceV1(app=AppV1(name="foo", onboardingStatus="OnBoarded")),
                NamespaceV1(app=AppV1(name="oof", onboardingStatus="BestEffort")),
            ],
            product=ProductV1(name="foo"),
        ),
    )


def test_get_selected_app_names(status_board_product):
    app_names = get_selected_app_names(
        ['apps[?@.name=="excluded"]'], status_board_product
    )
    assert app_names == {"foo"}

    app_names = get_selected_app_names([], status_board_product)
    assert app_names == {"excluded", "foo"}
