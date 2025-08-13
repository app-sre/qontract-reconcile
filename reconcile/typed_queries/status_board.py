from collections.abc import Callable, Iterable, Sequence
from typing import Any

from jsonpath_ng.ext import parser

from reconcile.gql_definitions.status_board.status_board import (
    AppV1_SaasFileV2,
    SaasFileV2,
    StatusBoardProductV1,
    StatusBoardV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.ocm.status_board import (
    ApplicationMetadataSpec,
)


def get_status_board(
    query_func: Callable | None = None,
) -> list[StatusBoardV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).status_board_v1 or []


def _get_deployment_saas_files(
    saas_files: Sequence[SaasFileV2 | AppV1_SaasFileV2],
) -> list[str]:
    return sorted(
        saas_file.name
        for saas_file in saas_files
        if "Deployment" in saas_file.managed_resource_types
        or "ClowdApp" in saas_file.managed_resource_types
    )


def get_selected_app_metadata(
    global_selectors: Iterable[str],
    product: StatusBoardProductV1,
) -> dict[str, ApplicationMetadataSpec]:
    selected_app_metadata: dict[str, ApplicationMetadataSpec] = {}

    apps: dict[str, Any] = {"apps": []}
    for namespace in product.product_environment.namespaces or []:
        prefix = ""
        if namespace.app.parent_app:
            prefix = f"{namespace.app.parent_app.name}-"
        name = f"{prefix}{namespace.app.name}"
        selected_app_names.add(name)
        app = namespace.app.model_dump(by_alias=True)
        app["name"] = name

        deployment_saas_files = []
        if namespace.app.saas_files:
            deployment_saas_files = {
                saas_file.name
                for saas_file in namespace.app.saas_files
                if "Deployment" in saas_file.managed_resource_types
                or "ClowdApp" in saas_file.managed_resource_types
            }

        selected_app_metadata[name] = {
            "deployment_saas_files": deployment_saas_files,
        }

        app = namespace.app.dict(by_alias=True)
        app["name"] = name
        apps["apps"].append(app)

        for child in namespace.app.children_apps or []:
            name = f"{namespace.app.name}-{child.name}"
            if name not in selected_app_names:
                selected_app_names.add(f"{namespace.app.name}-{child.name}")
                child_dict = child.model_dump(by_alias=True)
                child_dict["name"] = name

                deployment_saas_files = []

                if child.saas_files:
                    deployment_saas_files = {
                        saas_file.name
                        for saas_file in child.saas_files
                        if "Deployment" in saas_file.managed_resource_types
                    }

                selected_app_metadata[name] = {
                    "deployment_saas_files": deployment_saas_files,
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
            selected_app_metadata.pop(app_name, None)

    return selected_app_metadata
