import pytest

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
def application_status_board():
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
def products_status_board():
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


def test_get_product_applications_fields(mocker, application_status_board):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    mocker.patch(
        "reconcile.utils.ocm_base_client.OCMBaseClient.get_paginated",
        return_value=iter(application_status_board),
    )
    apps = get_product_applications(ocm, "foo")
    assert len(apps) == 2
    assert apps[0] == application_status_board[0]
    # key foo not in APPLICATION_DESIRED_KEYS
    assert apps[1] == {
        "id": "bar",
        "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
    }


def test_get_managed_products(mocker, products_status_board):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    mocker.patch(
        "reconcile.utils.ocm_base_client.OCMBaseClient.get_paginated",
        return_value=iter(products_status_board),
    )

    products = get_managed_products(ocm)
    assert len(products) == 2
    assert products[0] == products_status_board[0]
    # key foo not in APPLICATION_DESIRED_KEYS
    assert products[1] == {
        "id": "bar",
        "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
    }


def test_create_product(mocker):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    p = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient.post")

    create_product(ocm, {"name": "foo"})

    p.assert_called_once_with(
        "/api/status-board/v1/products/",
        data={
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
            "name": "foo",
        },
    )


def test_create_application(mocker):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    p = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient.post")

    create_application(ocm, {"name": "foo"})

    p.assert_called_once_with(
        "/api/status-board/v1/applications/",
        data={
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
            "name": "foo",
        },
    )


def test_delete_product(mocker):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    d = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient.delete")

    product_id = "foo"
    delete_product(ocm, product_id)

    d.assert_called_once_with(f"/api/status-board/v1/products/{product_id}")


def test_delete_application(mocker):
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient")
    d = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient.delete")

    application_id = "foo"
    delete_application(ocm, application_id)

    d.assert_called_once_with(f"/api/status-board/v1/applications/{application_id}")
