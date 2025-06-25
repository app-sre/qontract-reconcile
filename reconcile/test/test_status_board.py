from collections.abc import Callable
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.status_board.status_board import StatusBoardV1
from reconcile.status_board import (
    AbstractStatusBoard,
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
                                    "saasFiles": [
                                        {
                                            "name": "foo-deployment",
                                            "managedResourceTypes": [
                                                "Deployment",
                                                "Service",
                                            ],
                                        },
                                        {
                                            "name": "foo-config",
                                            "managedResourceTypes": ["ConfigMap"],
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
        action="create",
        status_board_object=StatusBoardStub(id=None, name="foo", fullname="foo", metadata=None),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.created
    assert h.status_board_object.summarized

    h = StatusBoardHandler(
        action="delete",
        status_board_object=StatusBoardStub(id=None, name="foo", fullname="foo", metadata=None),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.deleted
    assert h.status_board_object.summarized


def test_get_product_apps(status_board: StatusBoardV1) -> None:
    p = StatusBoardExporterIntegration.get_product_apps(status_board)
    assert "foo" in p
    assert "foo" in p["foo"]
    assert "foo-bar" in p["foo"]

    assert p["foo"]["foo"]["metadata"]["deploymentSaasFiles"] == ["foo-deployment"]
    assert p["foo"]["foo-bar"]["metadata"]["deploymentSaasFiles"] == ["foo-deployment"]


def test_get_diff_create_app() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {
            "foo": {
                "foo": {"name": "foo", "metadata": {}},
                "bar": {"name": "bar", "metadata": {}},
            }
        },
        [Product(id=None, name="foo", fullname="foo", metadata=None, applications=[])],
    )

    assert len(h) == 2
    assert h[0].action == h[1].action == "create"
    assert isinstance(h[0].status_board_object, Application)
    assert isinstance(h[1].status_board_object, Application)
    assert sorted([x.status_board_object.name for x in h]) == ["bar", "foo"]
    assert sorted([x.status_board_object.fullname for x in h]) == ["foo/bar", "foo/foo"]


def test_get_diff_create_one_app() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {"foo": {"foo": {"name": "foo", "metadata": {}}, "bar": {"name": "bar", "metadata": {}}}},
        [
            Product(
                id=None,
                name="foo",
                fullname="foo",
                metadata=None,
                applications=[Application(id=None, name="bar", fullname="foo/bar", metadata=None, old_metadata=None, product=None)],
            )
        ],
    )

    assert len(h) == 1
    assert h[0].action == "create"
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "foo"
    assert h[0].status_board_object.fullname == "foo/foo"


def test_get_diff_create_product_and_apps() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {
            "foo": {
                "foo": {"name": "foo", "metadata": {}},
                "bar": {"name": "bar", "metadata": {}},
            }
        },
        [],
    )

    assert len(h) == 3
    assert h[0].action == "create"
    assert isinstance(h[0].status_board_object, Product)
    assert isinstance(h[1].status_board_object, Application)
    assert isinstance(h[2].status_board_object, Application)


def test_get_diff_noop() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {"foo": {"bar": {"name": "bar", "metadata": {}}}},
        [
            Product(
                id=None,
                name="foo",
                fullname="foo",
                metadata=None,
                applications=[Application(id=None, name="bar", fullname="foo/bar", metadata=None, old_metadata=None, product=None)],
            )
        ],
    )

    assert len(h) == 0


def test_get_diff_delete_app() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {"foo": {}},
        [
            Product(
                id=None,
                name="foo",
                fullname="foo",
                metadata=None,
                applications=[Application(id=None, name="bar", fullname="foo/bar", metadata=None, old_metadata=None, product=None)],
            )
        ],
    )

    assert len(h) == 1
    assert h[0].action == "delete"
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "bar"


def test_get_diff_delete_apps_and_product() -> None:
    Product.update_forward_refs()

    h = StatusBoardExporterIntegration.get_diff(
        {},
        [
            Product(
                id=None,
                name="foo",
                fullname="foo",
                metadata=None,
                applications=[Application(id=None, name="bar", fullname="foo/bar", metadata=None, old_metadata=None, product=None)],
            )
        ],
    )

    assert len(h) == 2
    assert h[0].action == h[1].action == "delete"
    assert isinstance(h[0].status_board_object, Application)
    assert isinstance(h[1].status_board_object, Product)


def test_get_diff_update_app_metadata() -> None:
    Product.update_forward_refs()

    # Existing application with old metadata (no deploymentSaasFiles)
    existing_app = Application(
        id="app-123",
        name="foo",
        fullname="product/foo",
        metadata={"someOtherField": "value"},  # No deploymentSaasFiles
        old_metadata=None,
        product=None
    )
    existing_product = Product(
        id="prod-123",
        name="product",
        fullname="product",
        metadata=None,
        applications=[existing_app]
    )

    # Desired state with deploymentSaasFiles
    desired_apps = {
        "product": {
            "foo": {
                "name": "foo",
                "metadata": {
                    "deploymentSaasFiles": ["foo-deployment"]
                }
            }
        }
    }

    h = StatusBoardExporterIntegration.get_diff(
        desired_apps,
        [existing_product],
    )

    # Should generate an update action
    assert len(h) == 1
    assert h[0].action == "update"
    assert isinstance(h[0].status_board_object, Application)
    assert h[0].status_board_object.name == "foo"
    assert h[0].status_board_object.id == "app-123"  # Should preserve the ID
    if h[0].status_board_object.metadata:
        assert h[0].status_board_object.metadata["deploymentSaasFiles"] == ["foo-deployment"]


def test_get_diff_update_app_metadata_preserves_managed_by() -> None:
    Product.update_forward_refs()

    # Existing application with old metadata that should be replaced
    existing_app = Application(
        id="app-123",
        name="foo",
        fullname="product/foo",
        metadata={
            "managedBy": "qontract-reconcile",
            "someOtherField": "value"  # This should be discarded in fresh metadata
        },
        old_metadata=None,
        product=None
    )
    existing_product = Product(
        id="prod-123",
        name="product",
        fullname="product",
        metadata=None,
        applications=[existing_app]
    )

    # Desired state with deploymentSaasFiles
    desired_apps = {
        "product": {
            "foo": {
                "name": "foo",
                "metadata": {
                    "deploymentSaasFiles": ["foo-deployment"]
                }
            }
        }
    }

    h = StatusBoardExporterIntegration.get_diff(
        desired_apps,
        [existing_product],
    )

    # Should generate an update action with fresh metadata
    assert len(h) == 1
    assert h[0].action == "update"
    assert isinstance(h[0].status_board_object, Application)
    
    updated_metadata = h[0].status_board_object.metadata
    if updated_metadata:
        assert updated_metadata["managedBy"] == "qontract-reconcile"  # Always present
        assert updated_metadata["deploymentSaasFiles"] == ["foo-deployment"]  # From desired state
        assert "someOtherField" not in updated_metadata  # Old metadata discarded
        assert len(updated_metadata) == 2  # Only managedBy and deploymentSaasFiles


def test_apply_sorted(mocker: MockerFixture) -> None:
    Product.update_forward_refs()
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient", autospec=True)
    logging = mocker.patch("reconcile.status_board.logging", autospec=True)

    product = Product(id=None, name="foo", fullname="foo", metadata=None, applications=[])
    h = [
        StatusBoardHandler(
            action="create",
            status_board_object=Application(
                id=None, name="bar", fullname="foo/bar", metadata=None, old_metadata=None, product=product
            ),
        ),
        StatusBoardHandler(
            action="create",
            status_board_object=product,
        ),
    ]

    StatusBoardExporterIntegration.apply_diff(True, ocm, h)
    logging.info.assert_has_calls(
        calls=[
            call('create - Product: "foo"'),
            call('create - Application: "bar" "foo/bar"'),
        ],
        any_order=False,
    )


def test_status_board_handler_update(mocker: MockerFixture) -> None:
    ocm = mocker.patch("reconcile.status_board.OCMBaseClient")
    h = StatusBoardHandler(
        action="update",
        status_board_object=StatusBoardStub(id="123", name="foo", fullname="foo", metadata=None),
    )

    h.act(dry_run=False, ocm=ocm)
    assert isinstance(h.status_board_object, StatusBoardStub)
    assert h.status_board_object.updated
    assert h.status_board_object.summarized
