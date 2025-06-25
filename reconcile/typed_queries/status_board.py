from collections.abc import Callable, Iterable
from typing import Any

from jsonpath_ng.ext import parser

from reconcile.gql_definitions.status_board.status_board import (
    StatusBoardProductV1,
    StatusBoardV1,
    query,
)
from reconcile.utils import gql


def get_status_board(
    query_func: Callable | None = None,
) -> list[StatusBoardV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).status_board_v1 or []


def get_selected_app_data(
    global_selectors: Iterable[str],
    product: StatusBoardProductV1,
) -> dict[str, dict[str, Any]]:
    """
    Get selected app data including saasFiles metadata.
    Returns a mapping of app_name -> app_data_with_metadata
    """
    selected_app_data: dict[str, dict[str, Any]] = {}

    apps: dict[str, Any] = {"apps": []}
    for namespace in product.product_environment.namespaces or []:
        prefix = ""
        if namespace.app.parent_app:
            prefix = f"{namespace.app.parent_app.name}-"
        name = f"{prefix}{namespace.app.name}"

        # Get deployment saasFiles for this app
        deployment_saas_files = []
        if namespace.app.saas_files:
            deployment_saas_files = [
                saas_file.name
                for saas_file in namespace.app.saas_files
                if "Deployment" in saas_file.managed_resource_types
            ]

        app_data = {
            "name": name,
            "metadata": {"deploymentSaasFiles": deployment_saas_files},
        }
        selected_app_data[name] = app_data

        app = namespace.app.dict(by_alias=True)
        app["name"] = name
        apps["apps"].append(app)

        for child in namespace.app.children_apps or []:
            child_name = f"{namespace.app.name}-{child.name}"
            if child_name not in selected_app_data:
                # Children don't have their own saasFiles, they inherit from parent
                child_data = {
                    "name": child_name,
                    "metadata": {"deploymentSaasFiles": deployment_saas_files},
                }
                selected_app_data[child_name] = child_data

                child_dict = child.dict(by_alias=True)
                child_dict["name"] = child_name
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


def get_selected_app_names(
    global_selectors: Iterable[str],
    product: StatusBoardProductV1,
) -> set[str]:
    app_data = get_selected_app_data(global_selectors, product)
    return set(app_data.keys())
