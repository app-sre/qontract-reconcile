from reconcile.gql_definitions.ocp_release_mirror.ocp_release_mirror import (
    OcpReleaseMirrorV1,
    query,
)
from reconcile.utils import gql


def get_ocp_release_mirrors() -> list[OcpReleaseMirrorV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.ocp_release_mirror or [])
