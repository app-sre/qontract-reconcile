import json
from collections.abc import Iterable
from typing import Any
from unittest.mock import (
    create_autospec,
)

from reconcile.fleet_labeler.ocm import Cluster, OCMClient
from reconcile.fleet_labeler.vcs import VCS
from reconcile.test.fixtures import Fixtures


def build_ocm_client(
    discover_clusters_by_labels: Iterable[Cluster],
) -> OCMClient:
    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_label_keys.return_value = (
        discover_clusters_by_labels
    )
    return ocm_client


def build_cluster(
    subscription_labels: dict[str, str],
    cluster_id: str,
    name: str,
    server_url: str = "https://api.test.com",
) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        server_url=server_url,
        subscription_labels=subscription_labels,
    )


def build_vcs(content: str = "") -> VCS:
    vcs = create_autospec(spec=VCS)
    vcs.get_file_content_from_main.return_value = content
    return vcs


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
    data["path"] = "test.yaml"
    data["ocm"] = {
        "environment": {
            "url": "https://api.test.com",
        },
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
