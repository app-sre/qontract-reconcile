from collections import Counter

from reconcile.gql_definitions.app_interface_metrics_exporter.onboarding_status import (
    query,
)
from reconcile.utils.gql import GqlApi


def get_onboarding_status(
    gql: GqlApi,
) -> Counter:
    data = query(gql.query)
    return Counter(a.onboarding_status for a in data.apps)
