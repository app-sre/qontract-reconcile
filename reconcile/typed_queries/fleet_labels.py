from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_fleet_label_specs(
    api: GqlApi | None = None,
) -> list[FleetLabelsSpecV1]:
    api = api or gql.get_api()
    data = query(api.query)
    return data.fleet_labels_specs or []
