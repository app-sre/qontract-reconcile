from collections.abc import Callable
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.slo_documents.slo_documents import SLODocumentV1
from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
from reconcile.status_board import (
    AbstractStatusBoard,
    Action,
    Application,
    Product,
    Service,
    StatusBoardExporterIntegration,
    StatusBoardHandler,
)
from reconcile.utils.ocm.status_board import BaseOCMSpec, ServiceMetadataSpec
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.runtime.integration import PydanticRunParams


class StatusBoardStub(AbstractStatusBoard):
    created: bool | None = False
    deleted: bool | None = False
    updated: bool | None = False
    summarized: bool | None = False

    def create(self, ocm: OCMBaseClient) -> None:
        self.created = True

    def update(self, ocm: OCMBaseClient) -> None:
        self.updated = True

    def delete(self, ocm: OCMBaseClient) -> None:
        self.deleted = True

    def summarize(self) -> str:
        self.summarized = True
        return ""

    @staticmethod
    def get_priority() -> int:
        return 0

    def to_ocm_spec(self) -> BaseOCMSpec:
        return {"name": "", "fullname": ""}


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
                },
                {
                    "appSelectors": {
                        "exclude": ['apps[?@.onboardingStatus!="OnBoarded"]']
                    },
                    "productEnvironment": {
                        "name": "bar",
                        "labels": '{"bar": "bar"}',
                        "namespaces": [
                            {
                                "app": {
                                    "name": "bar",
                                    "onboardingStatus": "OnBoarded",
                                }
                            },
                        ],
                        "product": {
                            "name": "bar",
                        },
                    },
                },
            ],
        },
    )


@pytest.fixture
def slo_documents(gql_class_factory: Callable[..., SLODocumentV1]) -> SLODocumentV1:
    return gql_class_factory(
        SLODocumentV1,
        {
            "labels": '{"service":"bar","statusBoard":"enabled"}',
            "name": "foo",
            "app": {"name": "foo"},
            "slos": [
                {
                    "name": "Availability",
                    "dashboard": "https://url.com",
                    "SLIType": "availability",
                    "SLISpecification": "specification 1",
                    "SLOTarget": 0.95,
                    "SLOTargetUnit": "percent_0_1",
                    "SLOParameters": {"window": "28d"},
                    "SLODetails": "https://url.com",
                    "expr": "metric{}",
                },
                {
                    "name": "Latency",
                    "dashboard": "https://url.com",
                    "SLIType": "latency",
                    "SLISpecification": "specification 2",
                    "SLOTarget": 0.95,
                    "SLOTargetUnit": "percent_0_1",
                    "SLOParameters": {"window": "28d"},
                    "SLODetails": "https://url.com",
                    "expr": "metric{}",
                },
            ],
            "namespaces": [
                {
                    "namespace": {
                        "cluster": {"name": "cluster"},
                        "environment": {"product": {"name": "foo"}},
                    }
                }
            ],
        },
    )


@pytest.fixture
def basic_service_metadata_spec() -> ServiceMetadataSpec:
    return {
        "sli_specification": "specification",
        "target_unit": "unit",
        "slo_details": "details",
        "sli_type": "type",
        "window": "window",
        "target": 0.99,
    }


def test_status_board_handler(mocker: MockerFixture) -> None:
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient")
    h = StatusBoardHandler(
        action=Action.create,
        status_board_object=StatusBoardStub(id=None,name="foo", fullname="foo", metadata={}),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.created
    assert h.status_board_object.summarized

    h = StatusBoardHandler(
        action=Action.delete,
        status_board_object=StatusBoardStub(id=None, name="foo", fullname="foo", metadata={}),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.deleted
    assert h.status_board_object.summarized

    # Update is only supported for Services
    # Services need an Application with ID to be updated
    metadata: ServiceMetadataSpec = {
        "sli_specification": "specification",
        "target_unit": "unit",
        "slo_details": "details",
        "sli_type": "type",
        "window": "window",
        "target": 0.99,
    }
    s = Service(
        id="baz",
        name="foo",
        fullname="baz/foo/bar",
        application=Application(
            id="foz",
            name="bar",
            fullname="bar",
            services=[],
            product=Product(id=None, name="baz", fullname="baz", applications=[], metadata={}),
            metadata={}
        ),
        metadata=metadata,
    )
    spy = mocker.spy(Service, "update")
    h = StatusBoardHandler(action=Action.update, status_board_object=s)
    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, Service)
    assert h.status_board_object.summarize() == 'Service: "foo" "baz/foo/bar"'
    spy.assert_called_once_with(s, ocm)


def test_get_product_apps(status_board: StatusBoardV1) -> None:
    p = StatusBoardExporterIntegration.get_product_apps(status_board)
    assert p == {"foo": {"foo", "foo-bar"}, "bar": {"bar"}}


def test_get_current_products_applications_services(mocker: MockerFixture) -> None:
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
                "metadata": {
                    "sli_type": "type",
                    "sli_specification": "spec",
                    "slo_details": "details",
                    "target": 0.99,
                    "target_unit": "unit",
                    "window": "1h",
                },
            },
            {
                "name": "service_2",
                "fullname": "product_1/app_1/service_2",
                "id": "1_1_2",
                "metadata": {
                    "sli_type": "type",
                    "sli_specification": "spec",
                    "slo_details": "details",
                    "target": 0.99,
                    "target_unit": "unit",
                    "window": "1h",
                },
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

    metadata: ServiceMetadataSpec = {
        "sli_type": "type",
        "sli_specification": "spec",
        "slo_details": "details",
        "target": 0.99,
        "target_unit": "unit",
        "window": "1h",
    }
    product_1 = Product(
        name="product_1",
        fullname="product_1",
        id="1",
        applications=[],
        metadata={}
    )
    product_2 = Product(
        name="product_2",
        fullname="product_2",
        id="2",
        applications=[],
        metadata={}
    )
    app_1 = Application(
        name="app_1",
        fullname="product_1/app_1",
        id="1_1",
        services=[],
        metadata={},
        product=product_1
    )
    app_2 = Application(
        name="app_2",
        fullname="product_1/app_2",
        id="1_2",
        services=[],
        metadata={},
        product=product_1
    )
    app_3 = Application(
        name="app_3",
        fullname="product_2/app_3",
        id="2_3",
        services=[],
        metadata={},
        product=product_2,
    )
    service_1 = Service(
        name="service_1",
        fullname="product_1/app_1/service_1",
        id="1_1_1",
        metadata=metadata,
        application=app_1,
    )
    service_2 = Service(
        name="service_2",
        fullname="product_1/app_1/service_2",
        id="1_1_2",
        metadata=metadata,
        application=app_1,
    )
    app_1.services = [service_1, service_2]
    product_1.applications = [app_1, app_2]
    product_2.applications = [app_3]

    assert products == [product_1, product_2]


def test_current_abstract_status_board_map() -> None:
    metadata: ServiceMetadataSpec = {
        "sli_type": "type",
        "sli_specification": "spec",
        "slo_details": "details",
        "target": 0.99,
        "target_unit": "unit",
        "window": "1h",
    }

    product_1 = Product(
        name="product_1",
        fullname="product_1",
        id=None,
        applications=[],
        metadata={}
    )
    product_2 = Product(
        name="product_2",
        fullname="product_2",
        id="2",
        applications=[],
        metadata={}
    )
    app_1 = Application(
        name="app_1",
        fullname="product_1/app_1",
        id="1_1",
        services=[],
        product=product_1,
        metadata={}
    )
    app_2 = Application(
        name="app_2",
        fullname="product_1/app_2",
        id="1_2",
        services=[],
        product=product_1,
        metadata={}
    )
    app_3 = Application(
        name="app_3",
        fullname="product_2/app_3",
        id="2_3",
        services=[],
        product=product_2,
        metadata={}
    )
    service_1 = Service(
        name="service_1",
        fullname="product_1/app_1/service_1",
        id="1_1_1",
        metadata=metadata,
        application=app_1,
    )
    service_2 = Service(
        name="service_2",
        fullname="product_1/app_1/service_2",
        id="1_1_2",
        metadata=metadata,
        application=app_1,
    )
    app_1.services = [service_1, service_2]
    product_1.applications = [app_1, app_2]
    product_2.applications = [app_3]

    flat_map = StatusBoardExporterIntegration.current_abstract_status_board_map([
        product_1,
        product_2,
    ])

    assert flat_map == {
        "product_1": Product(
            name="product_1",
            fullname="product_1",
            id="1",
            applications=[],
            metadata={}
        ),
        "product_1/app_1": Application(
            name="app_1",
            fullname="product_1/app_1",
            id="1_1",
            services=[],
            metadata={},
            product=product_1,
        ),
        "product_1/app_1/service_1": Service(
            name="service_1",
            fullname="product_1/app_1/service_1",
            id="1_1_1",
            metadata=metadata,
            application=app_1,
        ),
        "product_1/app_1/service_2": Service(
            name="service_2",
            fullname="product_1/app_1/service_2",
            id="1_1_2",
            metadata=metadata,
            application=app_1,
        ),
        "product_1/app_2": Application(
            name="app_2",
            fullname="product_1/app_2",
            id="1_2",
            services=[],
            metadata={},
            product=product_1,
        ),
        "product_2": Product(
            name="product_2",
            fullname="product_2",
            id="2",
            applications=[],
            metadata={}
        ),
        "product_2/app_3": Application(
            name="app_3",
            fullname="product_2/app_3",
            id="2_3",
            services=[],
            metadata={},
            product=product_2,
        ),
    }


def test_get_diff_create_app() -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": Application(
                name="bar",
                fullname="foo/bar",
                services=[],
                product=foo_product,
                id=None,
                metadata={}
            ),
            "foo/foo": Application(
                name="foo",
                fullname="foo/foo",
                services=[],
                product=foo_product,
                id=None,
                metadata={}
            )
        },
        current_abstract_status_board_map={
            "foo": Product(name="foo", fullname="foo", applications=[], id=None, metadata={}),
        },
    )

    assert len(h) == 2
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.create
        for e in h
    )
    assert any(
        e.status_board_object.name == "bar"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.create
        for e in h
    )


def test_get_diff_create_one_app() -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    current_foo = Product(
        id="1",
        name="foo",
        fullname="foo",
        applications=[],
    )
    current_app = Application(
        id="2", name="bar", fullname="foo/bar", services=[], product=current_foo
    )
    current_foo.applications = [current_app]
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": Application(
                name="bar", fullname="foo/bar", services=[], product=foo_product, id=None, metadata={}
            ),
            "foo/foo": Application(
                name="foo", fullname="foo/foo", services=[], product=foo_product, id=None, metadata={}
            ),
        },
        current_abstract_status_board_map={
            "foo": current_foo,
            "foo/bar": current_app,
        },
    )
    assert len(h) == 1
    assert h[0].action == Action.create
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "foo"
    assert h[0].status_board_object.fullname == "foo/foo"


def test_get_diff_create_product_and_apps() -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": Application(
                name="bar", fullname="foo/bar", services=[], product=foo_product, id=None, metadata={}
            ),
            "foo/foo": Application(
                name="foo", fullname="foo/foo", services=[], product=foo_product, id=None, metadata={}
            ),
        },
        current_abstract_status_board_map={},
    )

    assert len(h) == 3
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Product)
        and e.action == Action.create
        for e in h
    )
    assert any(
        e.status_board_object.name == "bar"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.create
        for e in h
    )
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.create
        for e in h
    )


def test_get_diff_create_product_app_and_service(
    basic_service_metadata_spec: ServiceMetadataSpec,
) -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    bar_app = Application(
        name="bar", fullname="foo/bar", services=[], product=foo_product, id=None, metadata={}
    )
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": bar_app,
            "foo/foo": Application(
                name="foo", fullname="foo/foo", services=[], product=foo_product, id=None, metadata={}
            ),
            "foo/bar/baz": Service(
                name="baz",
                fullname="foo/bar/baz",
                metadata=basic_service_metadata_spec,
                application=bar_app,
                id=None,
            ),
        },
        current_abstract_status_board_map={},
    )

    assert len(h) == 4
    assert h[0].action == Action.create
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Product)
        for e in h
    )
    assert any(
        e.status_board_object.name == "bar"
        and isinstance(e.status_board_object, Application)
        for e in h
    )
    assert any(
        e.status_board_object.name == "baz"
        and isinstance(e.status_board_object, Service)
        for e in h
    )


def test_get_diff_update_service() -> None:
    old_metadata: ServiceMetadataSpec = {
        "sli_specification": "specification",
        "target_unit": "unit",
        "slo_details": "details",
        "sli_type": "old type",
        "window": "window",
        "target": 0.99,
    }
    new_metadata: ServiceMetadataSpec = {
        "sli_specification": "specification",
        "target_unit": "unit",
        "slo_details": "details",
        "sli_type": "new type",
        "window": "window",
        "target": 0.99,
    }
    foo_product = Product(name="foo", fullname="foo", applications=[], metadata={})
    foo_bar_app = Application(
        name="bar", fullname="foo/bar", services=[], product=foo_product, metadata={}
    )
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": foo_bar_app,
            "foo/foo": Application(
                name="foo", fullname="foo/foo", services=[], product=foo_product, metadata={}
            ),
            "foo/bar/baz": Service(
                name="baz",
                fullname="foo/bar/baz",
                metadata=new_metadata,
                application=foo_bar_app,
            ),
        },
        current_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": foo_bar_app,
            "foo/foo": Application(
                name="foo", fullname="foo/foo", services=[], product=foo_product, metadata={}
            ),
            "foo/bar/baz": Service(
                name="baz",
                fullname="foo/bar/baz",
                metadata=old_metadata,
                application=foo_bar_app,
            ),
        },
    )

    assert len(h) == 1
    assert h[0].action == Action.update
    assert isinstance(h[0].status_board_object, Service)


def test_get_diff_noop() -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    current_foo = Product(
        id="1",
        name="foo",
        fullname="foo",
        applications=[],
        metadata={}
    )
    current_app = Application(
        id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
    )
    current_foo.applications = [current_app]
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
            "foo/bar": Application(
                name="bar", fullname="foo/bar", services=[], product=foo_product, id=None, metadata={}
            ),
        },
        current_abstract_status_board_map={
            "foo": current_foo,
            "foo/bar": current_app,
        },
    )
    assert len(h) == 0


def test_get_diff_delete_app() -> None:
    foo_product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    current_foo = Product(
        id="1",
        name="foo",
        fullname="foo",
        applications=[],
        metadata={}
    )
    current_app = Application(
        id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
    )
    current_foo.applications = [current_app]
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={
            "foo": foo_product,
        },
        current_abstract_status_board_map={
            "foo": current_foo,
            "foo/bar": Application(
                id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
            ),
        },
    )

    assert len(h) == 1
    assert h[0].action == Action.delete
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "bar"


def test_get_diff_delete_apps_and_product() -> None:
    current_foo = Product(
        id="1",
        name="foo",
        fullname="foo",
        applications=[],
        metadata={}
    )
    current_app = Application(
        id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
    )
    current_foo.applications = [current_app]
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={},
        current_abstract_status_board_map={
            "foo": current_foo,
            "foo/bar": Application(
                id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
            ),
        },
    )
    assert len(h) == 2
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Product)
        and e.action == Action.delete
        for e in h
    )
    assert any(
        e.status_board_object.name == "bar"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.delete
        for e in h
    )


def test_get_diff_delete_product_app_and_service() -> None:
    metadata: ServiceMetadataSpec = {
        "sli_specification": "specification",
        "target_unit": "unit",
        "slo_details": "details",
        "sli_type": "type",
        "window": "window",
        "target": 0.99,
    }
    current_foo = Product(
        id="1",
        name="foo",
        fullname="foo",
        applications=[],
        metadata={}
    )
    current_bar = Application(
        id="2", name="bar", fullname="foo/bar", services=[], product=current_foo, metadata={}
    )
    current_service = Service(
        id="3",
        name="baz",
        fullname="foo/bar/baz",
        metadata=metadata,
        application=current_bar,
    )
    current_bar.services = [current_service]
    current_foo.applications = [current_bar]
    h = StatusBoardExporterIntegration.get_diff(
        desired_abstract_status_board_map={},
        current_abstract_status_board_map={
            "foo": current_foo,
            "foo/bar": current_bar,
            "foo/bar/baz": Service(
                id="3",
                name="baz",
                fullname="foo/bar/baz",
                metadata=metadata,
                application=current_bar,
            ),
        },
    )
    assert len(h) == 3
    assert any(
        e.status_board_object.name == "foo"
        and isinstance(e.status_board_object, Product)
        and e.action == Action.delete
        for e in h
    )
    assert any(
        e.status_board_object.name == "bar"
        and isinstance(e.status_board_object, Application)
        and e.action == Action.delete
        for e in h
    )
    assert any(
        e.status_board_object.name == "baz"
        and isinstance(e.status_board_object, Service)
        and e.action == Action.delete
        for e in h
    )


def test_apply_sorted(mocker: MockerFixture) -> None:
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient", autospec=True)
    logging = mocker.patch("reconcile.status_board.logging", autospec=True)

    product = Product(name="foo", fullname="foo", applications=[], id=None, metadata={})
    application = Application(
        name="bar",
        fullname="foo/bar",
        product=product,
        services=[],
        id=None,
        metadata={},
    )
    metadata: ServiceMetadataSpec = {
        "sli_type": "type",
        "sli_specification": "spec",
        "slo_details": "details",
        "target": 0.99,
        "target_unit": "unit",
        "window": "1h",
    }
    h = [
        StatusBoardHandler(
            action=Action.create,
            status_board_object=Service(
                name="baz",
                fullname="foo/bar/baz",
                metadata=metadata,
                application=application,
            ),
        ),
        StatusBoardHandler(
            action=Action.create,
            status_board_object=application,
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
            call('Action.create - Service: "baz" "foo/bar/baz"'),
        ],
        any_order=False,
    )


def test_run_integration(
    mocker: MockerFixture,
    status_board: list[StatusBoardV1],
    slo_documents: list[SLODocumentV1],
) -> None:
    mocked_get_status_board = mocker.patch(
        "reconcile.status_board.get_status_board", autospec=True
    )
    mocked_get_slo_documents = mocker.patch(
        "reconcile.status_board.get_slo_documents", autospec=True
    )
    mock_init_ocm_base_client = mocker.patch(
        "reconcile.status_board.init_ocm_base_client", autospec=True
    )
    mocker.patch(
        "reconcile.utils.runtime.integration.get_app_interface_vault_settings",
        autospec=True,
    )
    mocker.patch(
        "reconcile.utils.runtime.integration.create_secret_reader", autospec=True
    )
    mocked_get_status_board.return_value = [status_board]
    mocked_get_slo_documents.return_value = [slo_documents]
    ocm_api_mock = mocker.Mock(OCMBaseClient)
    mock_init_ocm_base_client.return_value = ocm_api_mock

    mock_get_products = mocker.patch(
        "reconcile.status_board.get_managed_products", autospec=True
    )
    mock_get_apps = mocker.patch(
        "reconcile.status_board.get_product_applications", autospec=True
    )
    mock_get_services = mocker.patch(
        "reconcile.status_board.get_application_services", autospec=True
    )

    mock_get_products.return_value = [
        {"name": "product_1", "fullname": "product_1", "id": "1"},
        {"name": "bar", "fullname": "bar", "id": "2"},
    ]

    apps_mapping = {
        "1": [
            {"name": "app_1", "fullname": "product_1/app_1", "id": "1_1"},
        ],
        "2": [{"name": "bar", "fullname": "bar/bar", "id": "2_1"}],
    }

    services_mapping = {
        "1_1": [
            {
                "name": "service_1",
                "fullname": "product_1/app_1/service_1",
                "id": "1_1_1",
                "metadata": {
                    "sli_type": "availability",
                    "sli_specification": "specification 1",
                    "slo_details": "https://url.com",
                    "target": 0.95,
                    "target_unit": "percent_0_1",
                    "window": "28d",
                },
            },
        ],
    }

    mock_get_apps.side_effect = lambda _, product_id: apps_mapping.get(product_id, [])
    mock_get_services.side_effect = lambda _, app_id: services_mapping.get(app_id, [])

    mock_create_product = mocker.patch(
        "reconcile.status_board.create_product", autospec=True
    )
    mock_create_product.return_value = "1"

    mock_create_application = mocker.patch(
        "reconcile.status_board.create_application", autospec=True
    )
    mock_create_application.return_value = "2"

    mock_create_service = mocker.patch(
        "reconcile.status_board.create_service", autospec=True
    )
    mock_create_service.return_value = "3"

    mock_delete_product = mocker.patch(
        "reconcile.status_board.delete_product", autospec=True
    )
    mock_delete_application = mocker.patch(
        "reconcile.status_board.delete_application", autospec=True
    )
    mock_delete_service = mocker.patch(
        "reconcile.status_board.delete_service", autospec=True
    )
    integration = StatusBoardExporterIntegration(PydanticRunParams())

    integration.run(dry_run=False)

    mock_create_product.assert_called_once_with(
        ocm_api_mock, {"fullname": "foo", "name": "foo"}
    )
    mock_create_application.assert_has_calls(
        [
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "fullname": "foo/foo-bar",
                    "name": "foo-bar",
                    "product_id": "1",
                },
            ),
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "fullname": "foo/foo",
                    "name": "foo",
                    "product_id": "1",
                },
            ),
        ],
        any_order=True,
    )
    mock_create_service.assert_has_calls(
        [
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "name": "Availability",
                    "fullname": "foo/foo/Availability",
                    "metadata": {
                        "sli_type": "availability",
                        "sli_specification": "specification 1",
                        "slo_details": "https://url.com",
                        "target": 0.95,
                        "target_unit": "percent_0_1",
                        "window": "28d",
                    },
                    "application_id": "2",
                    "status_type": "traffic_light",
                    "service_endpoint": "none",
                },
            ),
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "name": "Latency",
                    "fullname": "foo/foo/Latency",
                    "metadata": {
                        "sli_type": "latency",
                        "sli_specification": "specification 2",
                        "slo_details": "https://url.com",
                        "target": 0.95,
                        "target_unit": "percent_0_1",
                        "window": "28d",
                    },
                    "application_id": "2",
                    "status_type": "traffic_light",
                    "service_endpoint": "none",
                },
            ),
        ],
        any_order=True,
    )
    mock_delete_product.assert_called_once_with(ocm_api_mock, "1")
    mock_delete_application.assert_called_once_with(ocm_api_mock, "1_1")
    mock_delete_service.assert_called_once_with(ocm_api_mock, "1_1_1")


def test_run_integration_create_services(
    mocker: MockerFixture,
    status_board: list[StatusBoardV1],
    slo_documents: list[SLODocumentV1],
) -> None:
    mocked_get_status_board = mocker.patch(
        "reconcile.status_board.get_status_board", autospec=True
    )
    mocked_get_slo_documents = mocker.patch(
        "reconcile.status_board.get_slo_documents", autospec=True
    )
    mock_init_ocm_base_client = mocker.patch(
        "reconcile.status_board.init_ocm_base_client", autospec=True
    )
    mocker.patch(
        "reconcile.utils.runtime.integration.get_app_interface_vault_settings",
        autospec=True,
    )
    mocker.patch(
        "reconcile.utils.runtime.integration.create_secret_reader", autospec=True
    )
    mocked_get_status_board.return_value = [status_board]
    mocked_get_slo_documents.return_value = [slo_documents]
    ocm_api_mock = mocker.Mock(OCMBaseClient)
    mock_init_ocm_base_client.return_value = ocm_api_mock

    mock_get_products = mocker.patch(
        "reconcile.status_board.get_managed_products", autospec=True
    )
    mock_get_apps = mocker.patch(
        "reconcile.status_board.get_product_applications", autospec=True
    )
    mock_get_services = mocker.patch(
        "reconcile.status_board.get_application_services", autospec=True
    )

    mock_get_products.return_value = [
        {"name": "foo", "fullname": "foo", "id": "1"},
        {"name": "bar", "fullname": "bar", "id": "2"},
    ]

    apps_mapping = {
        "1": [
            {"name": "foo", "fullname": "foo/foo", "id": "1_1"},
        ],
        "2": [{"name": "bar", "fullname": "bar/bar", "id": "2_1"}],
    }

    mock_get_apps.side_effect = lambda _, product_id: apps_mapping.get(product_id, [])
    mock_get_services.side_effect = lambda _, app_id: []

    mock_create_application = mocker.patch(
        "reconcile.status_board.create_application", autospec=True
    )
    mock_create_application.return_value = "2"

    mock_create_service = mocker.patch(
        "reconcile.status_board.create_service", autospec=True
    )
    mock_create_service.return_value = "3"

    integration = StatusBoardExporterIntegration(PydanticRunParams())

    integration.run(dry_run=False)

    mock_create_service.assert_has_calls(
        [
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "name": "Availability",
                    "fullname": "foo/foo/Availability",
                    "metadata": {
                        "sli_type": "availability",
                        "sli_specification": "specification 1",
                        "slo_details": "https://url.com",
                        "target": 0.95,
                        "target_unit": "percent_0_1",
                        "window": "28d",
                    },
                    "application_id": "1_1",
                    "status_type": "traffic_light",
                    "service_endpoint": "none",
                },
            ),
            call(
                ocm_api=ocm_api_mock,
                spec={
                    "name": "Latency",
                    "fullname": "foo/foo/Latency",
                    "metadata": {
                        "sli_type": "latency",
                        "sli_specification": "specification 2",
                        "slo_details": "https://url.com",
                        "target": 0.95,
                        "target_unit": "percent_0_1",
                        "window": "28d",
                    },
                    "application_id": "1_1",
                    "status_type": "traffic_light",
                    "service_endpoint": "none",
                },
            ),
        ],
        any_order=True,
    )
