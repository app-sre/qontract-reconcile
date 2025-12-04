from reconcile.gql_definitions.common.app_interface_clusterrole import (
    RoleV1,
    query,
)
from reconcile.utils import gql


def get_app_interface_clusterroles() -> list[RoleV1]:
    data = query(gql.get_api().query)
    return list(data.cluster_roles or [])
