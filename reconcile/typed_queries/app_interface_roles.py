from reconcile.gql_definitions.common.openshift_roles import (
    query,
    RoleV1,
)
from reconcile.utils import gql


def get_app_interface_roles() -> list[RoleV1]:
    data = query(gql.get_api().query)
    return list(data.roles or [])