from collections.abc import Callable
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
from reconcile.status_board import (
    AbstractStatusBoard,
    Action,
    Application,
    Product,
    StatusBoardExporterIntegration,
    StatusBoardHandler,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


class StatusBoardStub(AbstractStatusBoard):
    created: bool | None = False
    deleted: bool | None = False
    updated: bool | None = False
    summarized: bool | None = False

    def create(self, ocm: OCMBaseClient) -> None:
        self.created = True

    def delete(self, ocm: OCMBaseClient) -> None:
        self.deleted = True

    def update(self, ocm: OCMBaseClient) -> None:
        self.updated = True

    def summarize(self) -> str:
        self.summarized = True
        return ""

    @staticmethod
    def get_priority() -> int:
        return 0


@pytest.fixture
def status_board(gql_class_factory: Callable[..., StatusBoardV1]) -> StatusBoardV1:
    return gql_class_factory(
        StatusBoardV1,
        {
            "name": "foo",
            "ocm": {
                "url": "https://foo.com",
                "accessTokenUrl": "foo",
                "accessTokenClientId": "foo",
                "accessTokenClientSecret": {
                    "path": "foo",
                    "field": "foo",
                    "version": "1",
                    "format": "foo",
                },
            },
            "globalAppSelectors": {"exclude": ['apps[?@.name=="excluded"]']},
            "products": [
                {
                    "appSelectors": {
                        "exclude": ['apps[?@.onboardingStatus!="OnBoarded"]']
                    },
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
                                    "name": "foo",
                                    "onboardingStatus": "OnBoarded",
                                    "childrenApps": [
                                        {
                                            "name": "bar",
                                            "onboardingStatus": "OnBoarded",
                                        },
                                    ],
                                }
                            },
                            {"app": {"name": "oof", "onboardingStatus": "BestEffort"}},
                        ],
                        "product": {
                            "name": "foo",
                        },
                    },
                }
            ],
        },
    )


def test_status_board_handler(mocker: MockerFixture) -> None:
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient")
    h = StatusBoardHandler(
        action=Action.create,
        status_board_object=StatusBoardStub(name="foo", fullname="foo"),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.created
    assert h.status_board_object.summarized

    h = StatusBoardHandler(
        action=Action.delete,
        status_board_object=StatusBoardStub(name="foo", fullname="foo"),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.deleted
    assert h.status_board_object.summarized

    h = StatusBoardHandler(
        action=Action.update,
        status_board_object=StatusBoardStub(name="foo", fullname="foo"),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.updated
    assert h.status_board_object.summarized


def test_get_product_apps(status_board: StatusBoardV1) -> None:
    p = StatusBoardExporterIntegration.get_product_apps(status_board)
    assert p == {"foo": {"foo", "foo-bar"}}


def test_get_diff_create_app() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/foo": {"product": "foo", "type": "app", "app": "foo"},
        },
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""}
        },
        current_products={"foo": Product(name="foo", fullname="foo", applications=[])},
    )

    assert len(h) == 2
    assert h[0].action == h[1].action == Action.create
    assert isinstance(h[0].status_board_object, Application)
    assert isinstance(h[1].status_board_object, Application)
    assert sorted([x.status_board_object.name for x in h]) == ["bar", "foo"]
    assert sorted([x.status_board_object.fullname for x in h]) == ["foo/bar", "foo/foo"]


def test_get_diff_create_one_app() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/foo": {"product": "foo", "type": "app", "app": "foo"},
        },
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[Application(name="bar", fullname="foo/bar", services=[])],
            )
        },
    )
    assert len(h) == 1
    assert h[0].action == Action.create
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "foo"
    assert h[0].status_board_object.fullname == "foo/foo"


def test_get_diff_create_product_and_apps() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/foo": {"product": "foo", "type": "app", "app": "foo"},
        },
        current_abstract_status_board_map={},
        current_products={},
    )

    assert len(h) == 3
    assert h[0].action == Action.create
    assert isinstance(h[0].status_board_object, Product)
    assert isinstance(h[1].status_board_object, Application)
    assert isinstance(h[2].status_board_object, Application)


def test_get_diff_noop() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
        },
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[Application(name="bar", fullname="foo/bar", services=[])],
            )
        },
    )
    assert len(h) == 0


def test_get_diff_delete_app() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
        },
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[Application(name="bar", fullname="foo/bar", services=[])],
            )
        },
    )

    assert len(h) == 1
    assert h[0].action == Action.delete
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "bar"


def test_get_diff_delete_apps_and_product() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={},
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[Application(name="bar", fullname="foo/bar", services=[])],
            )
        },
    )
    assert len(h) == 2
    assert h[0].action == h[1].action == Action.delete
    assert isinstance(h[0].status_board_object, Application)
    assert isinstance(h[1].status_board_object, Product)


def test_apply_sorted(mocker: MockerFixture) -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient", autospec=True)
    logging = mocker.patch("reconcile.status_board.logging", autospec=True)

    product = Product(name="foo", fullname="foo", applications=[])
    h = [
        StatusBoardHandler(
            action=Action.create,
            status_board_object=Application(
                name="bar", fullname="foo/bar", product=product
            ),
        ),
        StatusBoardHandler(
            action=Action.create,
            status_board_object=product,
        ),
    ]

    StatusBoardExporterIntegration.apply_diff(True, ocm, h)
    logging.info.assert_has_calls(
        calls=[
            call('Action.create - Product: "foo"'),
            call('Action.create - Application: "bar" "foo/bar"'),
        ],
        any_order=False,
    )
