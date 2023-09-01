from typing import (
    Any,
    Callable,
    Iterable,
    Optional,
)

from jsonpath_ng.ext import parser

from reconcile.gql_definitions.status_board.status_board import (
    StatusBoardProductV1,
    StatusBoardV1,
    query,
)
from reconcile.utils import gql


def get_status_board(
    query_func: Optional[Callable] = None,
) -> list[StatusBoardV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).status_board_v1 or []


def get_selected_app_names(
    global_selectors: Iterable[str],
    product: StatusBoardProductV1,
) -> set[str]:
    selected_app_names: set[str] = {
        namespace.app.name for namespace in product.product_environment.namespaces or []
    }

    apps: dict[str, Any] = {"apps": []}
    for namespace in product.product_environment.namespaces or []:
        apps["apps"].append(namespace.app.dict(by_alias=True))

        for child in namespace.app.children_apps or []:
            if child.name not in selected_app_names:
                selected_app_names.add(f"{namespace.app.name}-{child.name}")
                child_dict = child.dict(by_alias=True)
                child_dict["name"] = f"{namespace.app.name}-{child.name}"
                apps["apps"].append(child_dict)

    selectors = set(global_selectors)
    if product.app_selectors:
        selectors.update(product.app_selectors.exclude or [])

    for selector in selectors:
        apps_to_remove: set[str] = set()
        results = parser.parse(selector).find(apps)
        for match in results:
            apps_to_remove.add(match.value["name"])
        selected_app_names -= apps_to_remove

    return selected_app_names
