from collections.abc import Iterable
from unittest.mock import (
    create_autospec,
)

from reconcile.dynatrace_token_provider.ocm import Cluster, OCMClient
from reconcile.utils.dynatrace.client import DynatraceClient


def build_ocm_client(cluster_details: Iterable[Cluster]) -> OCMClient:
    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_labels.return_value = cluster_details
    return ocm_client


def build_dynatrace_client() -> DynatraceClient:
    dynatrace_client = create_autospec(spec=DynatraceClient)
    return dynatrace_client
