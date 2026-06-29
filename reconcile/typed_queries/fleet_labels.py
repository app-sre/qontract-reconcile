from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.fleet_labeler.fleet_labels import (
    FleetLabelsSpecV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_fleet_label_specs(
    api: GqlApi | None = None,
) -> list[FleetLabelsSpecV1]:
    api = api or gql.get_api()
    data = query(api.query)
    return data.fleet_labels_specs or []
