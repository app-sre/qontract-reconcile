from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    GlitchtipInstanceV1,
    query,
)
from reconcile.utils import gql


def get_glitchtip_instances() -> list[GlitchtipInstanceV1]:
    data = query(gql.get_api().query)
    return list(data.instances or [])
