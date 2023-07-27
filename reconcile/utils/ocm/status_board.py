from typing import Any

from reconcile.utils.ocm_base_client import OCMBaseClient

APPLICATION_DESIRED_KEYS = {"id", "name", "fullname", "metadata"}
PRODUCTS_DESIRED_KEYS = {"id", "name", "fullname", "metadata"}


METADATA_MANAGED_BY_KEY = "managedBy"
METADATA_MANAGED_BY_VALUE = "qontract-reconcile"


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
            results.append(
                {k: v for k, v in application.items() if k in APPLICATION_DESIRED_KEYS}
            )

    return results


def get_managed_products(ocm_api: OCMBaseClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for product in ocm_api.get_paginated("/api/status-board/v1/products/"):
        if (
            product.get("metadata", {}).get(METADATA_MANAGED_BY_KEY, "")
            == METADATA_MANAGED_BY_VALUE
        ):
            results.append(
                {k: v for k, v in product.items() if k in PRODUCTS_DESIRED_KEYS}
            )
    return results


def create_product(ocm_api: OCMBaseClient, spec: dict[str, Any]) -> str:
    if "metadata" not in spec or spec["metadata"] is None:
        spec["metadata"] = {}
    spec["metadata"][METADATA_MANAGED_BY_KEY] = METADATA_MANAGED_BY_VALUE
    resp = ocm_api.post("/api/status-board/v1/products/", data=spec)
    return resp["id"]


def create_application(ocm_api: OCMBaseClient, spec: dict[str, Any]) -> str:
    if "metadata" not in spec or spec["metadata"] is None:
        spec["metadata"] = {}
    spec["metadata"][METADATA_MANAGED_BY_KEY] = METADATA_MANAGED_BY_VALUE
    resp = ocm_api.post("/api/status-board/v1/applications/", data=spec)
    return resp["id"]


def delete_product(ocm_api: OCMBaseClient, product_id: str) -> None:
    ocm_api.delete(f"/api/status-board/v1/products/{product_id}")


def delete_application(ocm_api: OCMBaseClient, application_id: str) -> None:
    ocm_api.delete(f"/api/status-board/v1/applications/{application_id}")
