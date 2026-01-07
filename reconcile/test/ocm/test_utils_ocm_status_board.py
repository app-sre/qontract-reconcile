from collections.abc import Callable
from typing import Any

import pytest
from pytest_mock import MockFixture

from reconcile.utils.ocm.status_board import (
    METADATA_MANAGED_BY_KEY,
    METADATA_MANAGED_BY_VALUE,
    create_application,
    create_product,
    create_service,
    delete_application,
    delete_product,
    delete_service,
    get_application_services,
    get_managed_products,
    get_product_applications,
    update_application,
    update_service,
)


@pytest.fixture
def ocm_api_return_data() -> list[dict[str, Any]]:
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


@pytest.mark.parametrize(
    "get_function,params",
    [
        (get_managed_products, None),
        (get_product_applications, "foo"),
        (get_application_services, "foo"),
    ],
)
def test_get_data_from_ocm(
    mocker: MockFixture,
    ocm_api_return_data: list[dict[str, Any]],
    get_function: Callable,
    params: str | None,
) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.get_paginated.return_value = iter(ocm_api_return_data)

    api_data = get_function(ocm, params) if params else get_function(ocm)

    assert len(api_data) == 2
    assert api_data[0] == ocm_api_return_data[0]
    # key foo not in APPLICATION_DESIRED_KEYS
    assert api_data[1] == {
        "id": "bar",
        "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
    }


@pytest.mark.parametrize(
    ("create_function", "end_point"),
    [
        (create_product, "/api/status-board/v1/products/"),
        (create_application, "/api/status-board/v1/applications/"),
        (create_service, "/api/status-board/v1/services/"),
    ],
)
def test_create_status_board_object_via_ocm_api(
    mocker: MockFixture,
    create_function: Callable,
    end_point: str,
) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.post.return_value = {"id": "foo"}

    id = create_function(ocm, {"name": "foo", "fullname": "foo", "metadata": {}})

    ocm.post.assert_called_once_with(
        end_point,
        data={
            "metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE},
            "name": "foo",
            "fullname": "foo",
        },
    )
    assert id == "foo"


@pytest.mark.parametrize(
    "delete_function,end_point",
    [
        (delete_product, "/api/status-board/v1/products/"),
        (delete_application, "/api/status-board/v1/applications/"),
        (delete_service, "/api/status-board/v1/services/"),
    ],
)
def test_delete_status_board_object_via_ocm_api(
    mocker: MockFixture, delete_function: Callable, end_point: str
) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    object_id = "foo"

    delete_function(ocm, object_id)

    ocm.delete.assert_called_once_with(f"{end_point}{object_id}")


def test_update_service(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.patch.return_value = {"id": "foo"}
    object_id = "foo"

    update_service(
        ocm,
        object_id,
        {
            "name": "foo",
            "fullname": "foo",
            "application": {"id": "1"},
            "status_type": "traffic_light",
            "service_endpoint": "none",
            "metadata": {
                "sli_specification": "specification",
                "target_unit": "unit",
                "slo_details": "details",
                "sli_type": "new type",
                "window": "window",
                "target": 0.99,
            },
        },
    )

    ocm.patch.assert_called_once_with(
        f"/api/status-board/v1/services/{object_id}",
        data={
            "name": "foo",
            "fullname": "foo",
            "application": {"id": "1"},
            "service_endpoint": "none",
            "status_type": "traffic_light",
            "metadata": {
                METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE,
                "sli_specification": "specification",
                "target_unit": "unit",
                "slo_details": "details",
                "sli_type": "new type",
                "window": "window",
                "target": 0.99,
            },
        },
    )


def test_update_application(mocker: MockFixture) -> None:
    ocm = mocker.patch("reconcile.utils.ocm_base_client.OCMBaseClient", autospec=True)
    ocm.patch.return_value = {"id": "foo"}
    object_id = "foo"

    update_application(
        ocm,
        object_id,
        {
            "name": "foo",
            "product": {"id": "1"},
            "fullname": "foo",
            "metadata": {"deployment_saas_files": {"foo"}},
        },
    )

    ocm.patch.assert_called_once_with(
        f"/api/status-board/v1/applications/{object_id}",
        data={
            "name": "foo",
            "product": {"id": "1"},
            "fullname": "foo",
            "metadata": {
                METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE,
                "deployment_saas_files": {"foo"},
            },
        },
    )
