from reconcile.gql_definitions.common.quay_instances import QuayInstanceV1, query
from reconcile.utils import gql


def get_quay_instances() -> list[QuayInstanceV1]:
    data = query(gql.get_api().query)
    return list(data.instances or [])
