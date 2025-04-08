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
    Service,
    StatusBoardExporterIntegration,
    StatusBoardHandler,
    UpdateNotSupported,
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
    Application.update_forward_refs()

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

    # Update is only supported for Services
    # Services need an Application with ID to be updated
    s = Service(
        id="baz",
        name="foo",
        fullname="foo/bar",
        application=Application(id="foz", name="bar", fullname="bar", services=None),
    )
    spy = mocker.spy(Service, "update")
    h = StatusBoardHandler(action=Action.update, status_board_object=s)
    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, Service)
    assert h.status_board_object.summarize() == 'Service: "foo" "foo/bar"'
    spy.assert_called_once_with(s, ocm)


def test_status_board_hander_update_not_supported(mocker: MockerFixture) -> None:
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient")

    h = StatusBoardHandler(
        action=Action.update,
        status_board_object=StatusBoardStub(name="foo", fullname="foo"),
    )

    with pytest.raises(UpdateNotSupported) as exp:
        h.act(dry_run=False, ocm=ocm)
    assert (
        str(exp.value)
        == "Called update on StatusBoardHandler that doesn't have update method"
    )


def test_get_product_apps(status_board: StatusBoardV1) -> None:
    p = StatusBoardExporterIntegration.get_product_apps(status_board)
    assert p == {"foo": {"foo", "foo-bar"}}


def test_get_current_products_applications_services(mocker: MockerFixture) -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient")
    mock_get_products = mocker.patch("reconcile.status_board.get_managed_products")
    mock_get_apps = mocker.patch("reconcile.status_board.get_product_applications")
    mock_get_services = mocker.patch("reconcile.status_board.get_application_services")

    mock_get_products.return_value = [
        {"name": "product_1", "fullname": "product_1", "id": "1"},
        {"name": "product_2", "fullname": "product_2", "id": "2"},
    ]

    apps_mapping = {
        "1": [
            {"name": "app_1", "fullname": "product_1/app_1", "id": "1_1"},
            {"name": "app_2", "fullname": "product_1/app_2", "id": "1_2"},
        ],
        "2": [
            {"name": "app_3", "fullname": "product_2/app_3", "id": "2_3"},
        ],
    }

    services_mapping = {
        "1_1": [
            {
                "name": "service_1",
                "fullname": "product_1/app_1/service_1",
                "id": "1_1_1",
            },
            {
                "name": "service_2",
                "fullname": "product_1/app_1/service_2",
                "id": "1_1_2",
            },
        ],
        "1_2": [],
        "2_3": [],
    }

    mock_get_apps.side_effect = lambda _, product_id: apps_mapping.get(product_id, [])
    mock_get_services.side_effect = lambda _, app_id: services_mapping.get(app_id, [])

    products = (
        StatusBoardExporterIntegration.get_current_products_applications_services(ocm)
    )

    assert products == [
        Product(
            name="product_1",
            fullname="product_1",
            id="1",
            applications=[
                Application(
                    name="app_1",
                    fullname="product_1/app_1",
                    id="1_1",
                    services=[
                        Service(
                            name="service_1",
                            fullname="product_1/app_1/service_1",
                            id="1_1_1",
                        ),
                        Service(
                            name="service_2",
                            fullname="product_1/app_1/service_2",
                            id="1_1_2",
                        ),
                    ],
                ),
                Application(
                    name="app_2", fullname="product_1/app_2", id="1_2", services=[]
                ),
            ],
        ),
        Product(
            name="product_2",
            fullname="product_2",
            id="2",
            applications=[
                Application(
                    name="app_3", fullname="product_2/app_3", id="2_3", services=[]
                )
            ],
        ),
    ]


def test_current_abstract_status_board_map() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    current_data = [
        Product(
            name="product_1",
            fullname="product_1",
            id="1",
            applications=[
                Application(
                    name="app_1",
                    fullname="product_1/app_1",
                    id="1_1",
                    services=[
                        Service(
                            name="service_1",
                            fullname="product_1/app_1/service_1",
                            id="1_1_1",
                        ),
                        Service(
                            name="service_2",
                            fullname="product_1/app_1/service_2",
                            id="1_1_2",
                        ),
                    ],
                ),
                Application(
                    name="app_2", fullname="product_1/app_2", id="1_2", services=[]
                ),
            ],
        ),
        Product(
            name="product_2",
            fullname="product_2",
            id="2",
            applications=[
                Application(
                    name="app_3", fullname="product_2/app_3", id="2_3", services=[]
                )
            ],
        ),
    ]

    flat_map = StatusBoardExporterIntegration.current_abstract_status_board_map(
        current_data
    )

    assert flat_map == {
        "product_1": {"type": "product", "product": "product_1", "app": ""},
        "product_1/app_1": {"type": "app", "product": "product_1", "app": "app_1"},
        "product_1/app_1/service_1": {
            "type": "service",
            "product": "product_1",
            "app": "app_1",
            "service": "service_1",
            "metadata": None,
        },
        "product_1/app_1/service_2": {
            "type": "service",
            "product": "product_1",
            "app": "app_1",
            "service": "service_2",
            "metadata": None,
        },
        "product_1/app_2": {"type": "app", "product": "product_1", "app": "app_2"},
        "product_2": {"type": "product", "product": "product_2", "app": ""},
        "product_2/app_3": {"type": "app", "product": "product_2", "app": "app_3"},
    }


def test_get_diff_create_app() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

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


def test_get_diff_create_product_app_and_service() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/foo": {"product": "foo", "type": "app", "app": "foo"},
            "foo/bar/baz": {
                "product": "foo",
                "type": "service",
                "app": "bar",
                "service": "baz",
                "metadata": {},
            },
        },
        current_abstract_status_board_map={},
        current_products={},
    )

    assert len(h) == 4
    assert h[0].action == Action.create
    assert h[0].status_board_object.name == "foo"
    assert isinstance(h[0].status_board_object, Product)
    assert h[1].status_board_object.name == "bar"
    assert isinstance(h[1].status_board_object, Application)
    assert h[2].status_board_object.name == "baz"
    assert isinstance(h[2].status_board_object, Service)
    assert h[3].status_board_object.name == "foo"
    assert isinstance(h[3].status_board_object, Application)


def test_get_diff_update_service() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/bar/baz": {
                "product": "foo",
                "type": "service",
                "app": "bar",
                "service": "baz",
                "metadata": {
                    "type": "new_type",
                },
            },
        },
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/bar/baz": {
                "product": "foo",
                "type": "service",
                "app": "bar",
                "service": "baz",
                "metadata": {"type": "old_type"},
            },
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[
                    Application(
                        name="bar",
                        fullname="foo/bar",
                        services=[
                            Service(
                                name="baz",
                                fullname="foo/bar/baz",
                                metadata={"type": "old_type"},
                            )
                        ],
                    )
                ],
            )
        },
    )

    assert len(h) == 1
    assert h[0].action == Action.update
    assert isinstance(h[0].status_board_object, Service)


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


def test_get_diff_delete_product_app_and_service() -> None:
    Product.update_forward_refs()
    Application.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={},
        current_abstract_status_board_map={
            "foo": {"product": "foo", "type": "product", "app": ""},
            "foo/bar": {"product": "foo", "type": "app", "app": "bar"},
            "foo/bar/baz": {
                "product": "foo",
                "type": "service",
                "app": "bar",
                "service": "baz",
                "metadata": {},
            },
        },
        current_products={
            "foo": Product(
                name="foo",
                fullname="foo",
                applications=[
                    Application(
                        name="bar",
                        fullname="foo/bar",
                        services=[
                            Service(name="baz", fullname="foo/bar/baz", metadata={})
                        ],
                    )
                ],
            )
        },
    )
    assert len(h) == 3
    assert h[0].action == h[1].action == h[2].action == Action.delete
    assert isinstance(h[0].status_board_object, Service)
    assert isinstance(h[1].status_board_object, Application)
    assert isinstance(h[2].status_board_object, Product)


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
                name="bar",
                fullname="foo/bar",
                product=product,
                services=[],
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
