from collections.abc import Callable, Iterable
from typing import Any

from jsonpath_ng.ext import parser

from reconcile.gql_definitions.status_board.status_board import (
    StatusBoardProductV1,
    StatusBoardV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.ocm.status_board import (
    METADATA_MANAGED_BY_KEY,
    METADATA_MANAGED_BY_VALUE,
)


def get_status_board(
    query_func: Callable | None = None,
) -> list[StatusBoardV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).status_board_v1 or []


def get_selected_app_data(
    global_selectors: Iterable[str],
    product: StatusBoardProductV1,
) -> dict[str, dict[str, dict[str, set[str]]]]:
    selected_app_data: dict[str, dict[str, dict[str, Any]]] = {}

    apps: dict[str, Any] = {"apps": []}
    for namespace in product.product_environment.namespaces or []:
        prefix = ""
        if namespace.app.parent_app:
            prefix = f"{namespace.app.parent_app.name}-"
        name = f"{prefix}{namespace.app.name}"

        deployment_saas_files = set()
        if namespace.app.saas_files:
            deployment_saas_files = {
                saas_file.name
                for saas_file in namespace.app.saas_files
                if "Deployment" in saas_file.managed_resource_types
                or "ClowdApp" in saas_file.managed_resource_types
            }

        selected_app_data[name] = {
            "metadata": {
                METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE,
                "deploymentSaasFiles": set(deployment_saas_files),
            },
        }

        app = namespace.app.dict(by_alias=True)
        app["name"] = name
        apps["apps"].append(app)

        for child in namespace.app.children_apps or []:
            name = f"{namespace.app.name}-{child.name}"
            if name not in selected_app_data:
                deployment_saas_files = set()
                if child.saas_files:
                    deployment_saas_files = {
                        saas_file.name
                        for saas_file in child.saas_files
                        if "Deployment" in saas_file.managed_resource_types
                    }

                selected_app_data[name] = {
                    "metadata": {
                        METADATA_MANAGED_BY_KEY: METADATA_MANAGED_BY_VALUE,
                        "deploymentSaasFiles": set(deployment_saas_files),
                    },
                }

                child_dict = child.dict(by_alias=True)
                child_dict["name"] = name
                apps["apps"].append(child_dict)

    selectors = set(global_selectors)
    if product.app_selectors:
        selectors.update(product.app_selectors.exclude or [])

    for selector in selectors:
        apps_to_remove: set[str] = set()
        results = parser.parse(selector).find(apps)
        apps_to_remove.update(match.value["name"] for match in results)
        for app_name in apps_to_remove:
            selected_app_data.pop(app_name, None)

    return selected_app_data
