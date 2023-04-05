from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.saas_auto_promotions_manager.saas_files_for_auto_promotion import (
    SaasFileV2,
)
from reconcile.gql_definitions.saas_auto_promotions_manager.saas_files_for_auto_promotion import (
    query as query_saas_files_for_auto_promotions,
)
from reconcile.utils import gql


def get_saas_files_for_auto_promotions(
    query_func: Optional[Callable] = None,
) -> list[SaasFileV2]:
    if not query_func:
        query_func = gql.get_api().query
    data = query_saas_files_for_auto_promotions(query_func=query_func)
    return list(data.saas_files or [])
