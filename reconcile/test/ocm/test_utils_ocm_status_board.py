from typing import Any

import pytest
from pytest_mock import MockFixture

from reconcile.utils.ocm.status_board import (
    METADATA_MANAGED_BY_KEY,
    METADATA_MANAGED_BY_VALUE,
    create_application,
    create_product,
    delete_application,
    delete_product,
    get_managed_products,
    get_product_applications,
)


@pytest.fixture
def application_status_board() -> list[dict[str, Any]]:
    return [
        {
            "id": "foo",
            "name": "foo",
            "fullname": "foo",
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
        },
        {
            "id": "bar",
            "foo": "bar",
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
        },
        {
            "id": "oof",
        },
    ]


@pytest.fixture
def products_status_board() -> list[dict[str, Any]]:
    return [
        {
            "id": "foo",
            "name": "foo",
            "fullname": "foo",
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
        },
        {
            "id": "bar",
            "foo": "bar",
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
        },
        {
            "id": "oof",
        },
    ]


def test_get_product_applications_fields(
    mocker: MockFixture, application_status_board: list[dict[str, Any]]
) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.get_paginated.return_value = iter(application_status_board)

    apps = get_product_applications(ocm, "foo")
    assert len(apps) == 2
    assert apps[0] == application_status_board[0]
    # key foo not in APPLICATION_DESIRED_KEYS
    assert apps[1] == {
        "id": "bar",
        "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
    }


def test_get_managed_products(
    mocker: MockFixture, products_status_board: list[dict[str, Any]]
) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.get_paginated.return_value = iter(products_status_board)

    products = get_managed_products(ocm)
    assert len(products) == 2
    assert products[0] == products_status_board[0]
    # key foo not in APPLICATION_DESIRED_KEYS
    assert products[1] == {
        "id": "bar",
        "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
    }


def test_create_product(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.post.return_value = {"id": "foo"}

    id = create_product(ocm, {"name": "foo"})

    ocm.post.assert_called_once_with(
        "/api/status-board/v1/products/",
        data={
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
            "name": "foo",
        },
    )
    assert id == "foo"


def test_create_application(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.post.return_value = {"id": "foo"}

    id = create_application(ocm, {"name": "foo"})

    ocm.post.assert_called_once_with(
        "/api/status-board/v1/applications/",
        data={
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
            "name": "foo",
        },
    )
    assert id == "foo"


def test_delete_product(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    product_id = "foo"

    delete_product(ocm, product_id)

    ocm.delete.assert_called_once_with(f"/api/status-board/v1/products/{product_id}")


def test_delete_application(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    application_id = "foo"

    delete_application(ocm, application_id)

    ocm.delete.assert_called_once_with(
        f"/api/status-board/v1/applications/{application_id}"
    )
