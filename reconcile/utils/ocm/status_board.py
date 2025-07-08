from typing import Any, TypedDict

from reconcile.utils.ocm_base_client import OCMBaseClient

SERVICE_DESIRED_KEYS = {"id", "name", "fullname", "metadata"}
APPLICATION_DESIRED_KEYS = {"id", "name", "fullname", "metadata"}
PRODUCTS_DESIRED_KEYS = {"id", "name", "fullname", "metadata"}


METADATA_MANAGED_BY_KEY = "managedBy"
METADATA_MANAGED_BY_VALUE = "qontract-reconcile"


class BaseOCMSpec(TypedDict):
    name: str
    fullname: str


class IDSpec(TypedDict):
    id: str


class ApplicationOCMSpec(BaseOCMSpec):
    product: IDSpec


class ServiceMetadataSpec(TypedDict):
    sli_type: str
    sli_specification: str
    slo_details: str
    target: float
    target_unit: str
    window: str


class ServiceOCMSpec(BaseOCMSpec):
    # The next two fields come from the orignal script at
    # https://gitlab.cee.redhat.com/service/status-board/-/blob/main/scripts/create-services-from-app-intf.sh?ref_type=heads#L116
    status_type: str
    service_endpoint: str
    application: IDSpec
    metadata: ServiceMetadataSpec


def get_product_applications(
    ocm_api: OCMBaseClient, product_id: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for application in ocm_api.get_paginated(
        f"/api/status-board/v1/products/{product_id}/applications"
    ):
        if (
            application.get("metadata", {}).get(METADATA_MANAGED_BY_KEY, "")
            == METADATA_MANAGED_BY_VALUE
        ):
            results.append({  # noqa: PERF401
                k: v for k, v in application.items() if k in APPLICATION_DESIRED_KEYS
            })

    return results


def get_application_services(
    ocm_api: OCMBaseClient, app_id: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for service in ocm_api.get_paginated(
        f"/api/status-board/v1/applications/{app_id}/services"
    ):
        if (
            service.get("metadata", {}).get(METADATA_MANAGED_BY_KEY, "")
            == METADATA_MANAGED_BY_VALUE
        ):
            results.append({  # noqa: PERF401
                k: v for k, v in service.items() if k in SERVICE_DESIRED_KEYS
            })

    return results


def get_managed_products(ocm_api: OCMBaseClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for product in ocm_api.get_paginated("/api/status-board/v1/products/"):
        if (
            product.get("metadata", {}).get(METADATA_MANAGED_BY_KEY, "")
            == METADATA_MANAGED_BY_VALUE
        ):
            results.append({  # noqa: PERF401
                k: v for k, v in product.items() if k in PRODUCTS_DESIRED_KEYS
            })
    return results


def create_product(ocm_api: OCMBaseClient, spec: BaseOCMSpec) -> str:
    data = spec | {"metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE}}

    resp = ocm_api.post("/api/status-board/v1/products/", data=data)
    return resp["id"]


def create_application(ocm_api: OCMBaseClient, spec: ApplicationOCMSpec) -> str:
    data = spec | {"metadata": {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE}}

    resp = ocm_api.post("/api/status-board/v1/applications/", data=data)
    return resp["id"]


def create_service(ocm_api: OCMBaseClient, spec: ServiceOCMSpec) -> str:
    data = spec | {
        "metadata": spec["metadata"]
        | {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE}
    }

    resp = ocm_api.post("/api/status-board/v1/services/", data=data)
    return resp["id"]


def update_service(
    ocm_api: OCMBaseClient,
    service_id: str,
    spec: ServiceOCMSpec,
) -> None:
    data = spec | {
        "metadata": spec["metadata"]
        | {METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE}
    }

    ocm_api.patch(f"/api/status-board/v1/services/{service_id}", data=data)


def delete_product(ocm_api: OCMBaseClient, product_id: str) -> None:
    ocm_api.delete(f"/api/status-board/v1/products/{product_id}")


def delete_application(ocm_api: OCMBaseClient, application_id: str) -> None:
    ocm_api.delete(f"/api/status-board/v1/applications/{application_id}")


def delete_service(ocm_api: OCMBaseClient, service_id: str) -> None:
    ocm_api.delete(f"/api/status-board/v1/services/{service_id}")
