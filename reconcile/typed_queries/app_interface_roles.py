from reconcile.gql_definitions.common.app_interface_roles import (
    RoleV1,
    query,
)
from reconcile.utils import gql


def get_app_interface_roles() -> list[RoleV1]:
    data = query(gql.get_api().query)
    return list(data.roles or [])
