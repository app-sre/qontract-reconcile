from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.ocm_subscription_labels.clusters import ClusterV1
from reconcile.ocm_subscription_labels.integration import (
    ClusterStates,
    EnvWithClusters,
    OcmLabelsIntegration,
)
from reconcile.utils.ocm.base import ClusterDetails
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_ocm_subscription_labels_get_clusters(
    clusters: Iterable[ClusterV1], gql_class_factory: Callable
) -> None:
    assert clusters == [
        gql_class_factory(
            ClusterV1,
            {
                "name": "cluster-1",
                "ocm": {
                    "environment": {
                        "name": "ocm-prod",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-1",
                },
                "ocmSubscriptionLabels": '{"my-label-prefix":{"to-be-added":"enabled","to-be-changed":"enabled"}}',
            },
        ),
        gql_class_factory(
            ClusterV1,
            {
                "name": "cluster-2",
                "ocm": {
                    "environment": {
                        "name": "ocm-stage",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-2",
                },
            },
        ),
        gql_class_factory(
            ClusterV1,
            {
                "name": "cluster-3",
                "ocm": {
                    "environment": {
                        "name": "ocm-stage",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-2",
                },
                "ocmSubscriptionLabels": '{"my-label-prefix":{"to-be-added":"enabled"}}',
            },
        ),
    ]


def test_ocm_subscription_labels_get_ocm_environments(
    ocm_subscription_labels: OcmLabelsIntegration,
    clusters: Iterable[ClusterV1],
    envs: Iterable[EnvWithClusters],
    ocm_base_client: OCMBaseClient,
) -> None:
    assert ocm_subscription_labels.get_ocm_environments(clusters) == envs


def test_ocm_subscription_labels_init_ocm_apis(
    ocm_subscription_labels: OcmLabelsIntegration,
    envs: Iterable[EnvWithClusters],
    ocm_base_client: OCMBaseClient,
) -> None:
    def init_ocm_base_client_fake(*args, **kwargs) -> OCMBaseClient:
        return ocm_base_client

    ocm_subscription_labels.init_ocm_apis(
        envs, init_ocm_base_client=init_ocm_base_client_fake
    )
    assert len(ocm_subscription_labels.ocm_apis) == 2


def test_ocm_subscription_labels_cluster_details_cache(
    ocm_subscription_labels: OcmLabelsIntegration,
    build_cluster_details: Callable,
    gql_class_factory: Callable,
    ocm_base_client: OCMBaseClient,
) -> None:
    cluster: ClusterDetails = build_cluster_details(name="cluster-1", org_id="org-id-1")
    cluster_states = {
        "cluster-1": gql_class_factory(
            ClusterLabelState,
            {
                "env": {
                    "name": "ocm-stage",
                    "accessTokenClientSecret": {
                        "field": "client_secret",
                        "path": "path/to/client_secret",
                    },
                },
                "ocm_api": ocm_base_client,
                "cluster_details": cluster,
                "labels": {},
            },
        )
    }
    ocm_subscription_labels.populate_cluster_details_cache(cluster_states)
    assert (
        ocm_subscription_labels.get_cluster_details_from_cache(
            org_id="org-id-1", name="cluster-1"
        )
        == cluster
    )

    assert (
        ocm_subscription_labels.get_cluster_details_from_cache(
            org_id="does-not", name="exist"
        )
        is None
    )


def test_ocm_subscription_labels_fetch_current_state(
    ocm_subscription_labels: OcmLabelsIntegration,
    clusters: Iterable[ClusterV1],
    ocm_clusters: Sequence[ClusterDetails],
    mocker: MockerFixture,
    envs: Iterable[EnvWithClusters],
    current_state: ClusterStates,
) -> None:
    mocker.patch.object(
        ocm_subscription_labels, "get_ocm_environments", return_value=envs
    )
    init_ocm_apis_mock = mocker.patch.object(ocm_subscription_labels, "init_ocm_apis")
    mocker.patch(
        "reconcile.ocm_subscription_labels.integration.discover_clusters_for_organizations",
        autospec=True,
        side_effect=[
            # ocm-prod
            ocm_clusters[0:1],
            # ocm-stage
            ocm_clusters[1:],
        ],
    )

    assert (
        ocm_subscription_labels.fetch_current_state(
            clusters, managed_label_prefixes=["my-label-prefix"]
        )
        == current_state
    )
    assert (
        ocm_subscription_labels.get_cluster_details_from_cache(
            org_id="org-id-1", name="cluster-1"
        )
        == ocm_clusters[0]
    )
    init_ocm_apis_mock.assert_called_once_with(envs)


def test_ocm_subscription_labels_fetch_desired_state(
    ocm_subscription_labels: OcmLabelsIntegration,
    clusters: Iterable[ClusterV1],
    current_state: ClusterStates,
    desired_state: ClusterStates,
) -> None:
    ocm_subscription_labels.populate_cluster_details_cache(current_state)

    assert ocm_subscription_labels.fetch_desired_state(clusters) == desired_state


@pytest.mark.parametrize("dry_run", [True, False])
def test_ocm_subscription_labels_reconcile(
    ocm_subscription_labels: OcmLabelsIntegration,
    mocker: MockerFixture,
    current_state: ClusterStates,
    desired_state: ClusterStates,
    ocm_base_client: OCMBaseClient,
    dry_run: bool,
) -> None:
    add_subscription_label_mock = mocker.patch(
        "reconcile.ocm_subscription_labels.integration.add_subscription_label",
        autospec=True,
    )
    update_ocm_label_mock = mocker.patch(
        "reconcile.ocm_subscription_labels.integration.update_ocm_label",
        autospec=True,
    )
    delete_ocm_label_mock = mocker.patch(
        "reconcile.ocm_subscription_labels.integration.delete_ocm_label",
        autospec=True,
    )
    ocm_subscription_labels.reconcile(dry_run, current_state, desired_state)
    if dry_run:
        add_subscription_label_mock.assert_not_called()
        update_ocm_label_mock.assert_not_called()
        delete_ocm_label_mock.assert_not_called()
    else:
        add_calls = [
            call(
                ocm_api=ocm_base_client,
                ocm_cluster=desired_state["cluster-1"].cluster_details.ocm_cluster,  # type: ignore[union-attr]
                label="my-label-prefix.to-be-added",
                value="enabled",
            ),
            call(
                ocm_api=ocm_base_client,
                ocm_cluster=desired_state["cluster-3"].cluster_details.ocm_cluster,  # type: ignore[union-attr]
                label="my-label-prefix.to-be-added",
                value="enabled",
            ),
        ]
        add_subscription_label_mock.assert_has_calls(add_calls)
        assert add_subscription_label_mock.call_count == len(add_calls)

        update_calls = [
            call(
                ocm_api=ocm_base_client,
                ocm_label=desired_state["cluster-1"].cluster_details.labels[  # type: ignore[union-attr]
                    "my-label-prefix.to-be-changed"
                ],
                label="my-label-prefix.to-be-changed",
                value="enabled",
            )
        ]
        update_ocm_label_mock.assert_has_calls(update_calls)
        assert update_ocm_label_mock.call_count == len(update_calls)

        delete_calls = [
            call(
                ocm_api=ocm_base_client,
                ocm_label=desired_state["cluster-1"].cluster_details.labels[  # type: ignore[union-attr]
                    "my-label-prefix.to-be-removed"
                ],
            ),
            call(
                ocm_api=ocm_base_client,
                ocm_label=desired_state["cluster-3"].cluster_details.labels[  # type: ignore[union-attr]
                    "my-label-prefix.to-be-removed"
                ],
            ),
        ]
        delete_ocm_label_mock.assert_has_calls(delete_calls)
        assert delete_ocm_label_mock.call_count == len(delete_calls)
