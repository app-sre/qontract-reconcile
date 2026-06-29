from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from reconcile.gql_definitions.app_interface_metrics_exporter.onboarding_status import (
    query,
)

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_onboarding_status(
    gql: GqlApi,
) -> Counter:
    apps = query(gql.query).apps or []
    return Counter(a.onboarding_status for a in apps)
