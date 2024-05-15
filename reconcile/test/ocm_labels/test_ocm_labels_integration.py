from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.ocm_labels.clusters import ClusterV1
from reconcile.ocm_labels.integration import (
    ClusterSubscriptionLabelSource,
    OcmLabelsIntegration,
    init_cluster_subscription_label_source,
)
from reconcile.utils.ocm.base import ClusterDetails
from reconcile.utils.ocm.label_sources import (
    LabelSource,
    LabelState,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


class StaticLabelSource(LabelSource):
    def __init__(self, prefixes: set[str], labels: LabelState):
        self.prefixes = prefixes
        self.labels = labels

    def managed_label_prefixes(self) -> set[str]:
        return self.prefixes

    def get_labels(self) -> LabelState:
        return self.labels


def test_ocm_labels_get_clusters(
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
                        "labels": "{}",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-1",
                },
                "spec": {"id": "cluster-1_id"},
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
                        "labels": "{}",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-2",
                },
                "spec": {"id": "cluster-2_id"},
            },
        ),
        gql_class_factory(
            ClusterV1,
            {
                "name": "cluster-3",
                "ocm": {
                    "environment": {
                        "name": "ocm-stage",
                        "labels": "{}",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-2",
                },
                "spec": {"id": "cluster-3_id"},
                "ocmSubscriptionLabels": '{"my-label-prefix":{"to-be-added":"enabled"}}',
            },
        ),
    ]


def test_ocm_labels_init_ocm_apis(
    ocm_labels: OcmLabelsIntegration,
    envs: Iterable[OCMEnvironment],
    ocm_base_client: OCMBaseClient,
) -> None:
    def init_ocm_base_client_fake(*args, **kwargs) -> OCMBaseClient:
        return ocm_base_client

    ocm_apis = ocm_labels.init_ocm_apis(
        envs, init_ocm_base_client=init_ocm_base_client_fake
    )
    assert len(ocm_apis) == 2


def test_ocm_labels_fetch_current_state(
    ocm_labels: OcmLabelsIntegration,
    clusters: Iterable[ClusterV1],
    ocm_clusters: Sequence[ClusterDetails],
    mocker: MockerFixture,
    subscription_label_current_state: LabelState,
) -> None:
    mocker.patch(
        "reconcile.ocm_labels.integration.discover_clusters_for_organizations",
        autospec=True,
        side_effect=[
            # ocm-prod
            ocm_clusters[0:1],
            # ocm-stage
            ocm_clusters[1:],
        ],
    )

    assert (
        ocm_labels.fetch_subscription_label_current_state(
            clusters,
            managed_label_prefixes=["my-label-prefix"],
            ignored_label_prefixes=["my-label-prefix.must-be-ignored"],
        )
        == subscription_label_current_state
    )


def test_ocm_labels_fetch_desired_state(
    ocm_labels: OcmLabelsIntegration,
    clusters: list[ClusterV1],
    subscription_label_desired_state: LabelState,
) -> None:
    desired_state = ocm_labels.fetch_desired_state([
        init_cluster_subscription_label_source(clusters)
    ])
    assert desired_state == subscription_label_desired_state


@pytest.mark.parametrize("dry_run", [True, False])
def test_ocm_labels_reconcile(
    ocm_labels: OcmLabelsIntegration,
    mocker: MockerFixture,
    subscription_label_current_state: LabelState,
    subscription_label_desired_state: LabelState,
    ocm_base_client: OCMBaseClient,
    dry_run: bool,
) -> None:
    add_label_mock = mocker.patch(
        "reconcile.ocm_labels.integration.add_label",
        autospec=True,
    )
    update_label_mock = mocker.patch(
        "reconcile.ocm_labels.integration.update_label",
        autospec=True,
    )
    delete_label_mock = mocker.patch(
        "reconcile.ocm_labels.integration.delete_label",
        autospec=True,
    )
    ocm_labels.reconcile(
        dry_run,
        "scope",
        subscription_label_current_state,
        subscription_label_desired_state,
    )
    if dry_run:
        add_label_mock.assert_not_called()
        update_label_mock.assert_not_called()
        delete_label_mock.assert_not_called()
    else:
        add_calls = [
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-1-sub-id/labels",
                label="my-label-prefix.to-be-added",
                value="enabled",
            ),
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-3-sub-id/labels",
                label="my-label-prefix.to-be-added",
                value="enabled",
            ),
        ]
        add_label_mock.assert_has_calls(add_calls)
        assert add_label_mock.call_count == len(add_calls)

        update_calls = [
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-1-sub-id/labels",
                label="my-label-prefix.to-be-changed",
                value="enabled",
            )
        ]
        update_label_mock.assert_has_calls(update_calls)
        assert update_label_mock.call_count == len(update_calls)

        delete_calls = [
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-1-sub-id/labels",
                label="my-label-prefix.to-be-removed",
            ),
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-3-sub-id/labels",
                label="my-label-prefix.to-be-removed",
            ),
        ]
        delete_label_mock.assert_has_calls(delete_calls)
        assert delete_label_mock.call_count == len(delete_calls)


def test_cluster_label_source_get_labels(
    cluster_file_subscription_label_source: ClusterSubscriptionLabelSource,
    subscription_label_desired_state: LabelState,
) -> None:
    assert (
        cluster_file_subscription_label_source.get_labels()
        == subscription_label_desired_state
    )
