from typing import (
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
        a.app.name for a in product.product_environment.namespaces or []
    }

    selectors = set(global_selectors)
    if product.app_selectors:
        selectors.update(product.app_selectors.exclude or [])

    apps = {
        "apps": [
            a.app.dict(by_alias=True)
            for a in product.product_environment.namespaces or []
        ],
    }

    for selector in selectors:
        apps_to_remove: set[str] = set()
        results = parser.parse(selector).find(apps)
        for match in results:
            apps_to_remove.add(match.value["name"])
        selected_app_names -= apps_to_remove

    return selected_app_names
