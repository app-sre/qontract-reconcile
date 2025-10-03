from reconcile.gql_definitions.common.schemas import _Schema, query
from reconcile.utils import gql


def get_schemas() -> list[_Schema]:
    data = query(gql.get_api().query)
    return list(data.schemas or [])
