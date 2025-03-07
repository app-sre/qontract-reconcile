import json
from collections.abc import Iterable
from typing import Any
from unittest.mock import (
    Mock,
    create_autospec,
)

from reconcile.fleet_labeler.metrics import FleetLabelerMetrics
from reconcile.fleet_labeler.ocm import Cluster, OCMClient
from reconcile.fleet_labeler.vcs import VCS
from reconcile.test.fixtures import Fixtures


def build_ocm_client(
    discover_clusters_by_labels: Iterable[Cluster],
    cluster_labels: dict[str, dict[str, str]] | None = None,
) -> Mock:
    def cluster_labels_by_cluster_id(cluster_id: str) -> dict[str, str]:
        if not cluster_labels:
            return {}
        return cluster_labels[cluster_id]

    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_labels.return_value = discover_clusters_by_labels
    if cluster_labels:
        ocm_client.get_cluster_labels.side_effect = cluster_labels_by_cluster_id
    return ocm_client


def build_cluster(
    subscription_labels: dict[str, str],
    uid: str,
    name: str,
    server_url: str = "https://api.test.com",
) -> Cluster:
    return Cluster(
        cluster_id=uid,
        subscription_id=uid,
        name=name,
        server_url=server_url,
        subscription_labels=subscription_labels,
    )


def build_vcs(content: str = "", error: Exception | None = None) -> Mock:
    vcs = create_autospec(spec=VCS)
    if error:
        vcs.get_file_content_from_main.side_effect = error
    else:
        vcs.get_file_content_from_main.return_value = content
    return vcs


def build_metrics() -> Mock:
    return create_autospec(spec=FleetLabelerMetrics)


def get_fixture_content(file_name: str) -> str:
    fxt = Fixtures("fleet_labeler")
    return fxt.get(file_name)


def label_spec_data_from_fixture(file_name: str) -> dict[str, Any]:
    """
    Yaml spec files have refs and Json. This function properly fills refs and converts Json to strings.
    This is required to fullfill gql data class requirements.
    """
    fxt = Fixtures("fleet_labeler")
    data = fxt.get_anymarkup(file_name)
    del data["$schema"]
    data["path"] = "/test.yaml"
    data["ocmEnv"] = {
        "name": "ocm_test",
        "url": "https://api.test.com",
        "accessTokenClientId": "client_id",
        "accessTokenUrl": "https://test.com",
        "accessTokenClientSecret": {},
    }
    for label_default in data.get("labelDefaults") or []:
        label_default["subscriptionLabelTemplate"] = {
            "type": "jinja2",
            "path": {
                "content": fxt.get("label_template.yaml.j2"),
            },
            "variables": json.dumps(
                label_default["subscriptionLabelTemplate"]["variables"]
            ),
        }
        label_default["matchSubscriptionLabels"] = json.dumps(
            label_default["matchSubscriptionLabels"]
        )
    for cluster in data["clusters"]:
        cluster["subscriptionLabels"] = json.dumps(cluster["subscriptionLabels"])
    return data
