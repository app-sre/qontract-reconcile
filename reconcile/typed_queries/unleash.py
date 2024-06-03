from reconcile.gql_definitions.unleash_feature_toggles.feature_toggles import (
    UnleashInstanceV1,
    query,
)
from reconcile.utils import gql


def get_unleash_instances() -> list[UnleashInstanceV1]:
    data = query(gql.get_api().query)
    return list(data.instances or [])
