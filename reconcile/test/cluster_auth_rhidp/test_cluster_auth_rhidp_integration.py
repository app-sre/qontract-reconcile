from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from reconcile.cluster_auth_rhidp.integration import (
    ClusterAuthRhidpIntegration,
    OcmApis,
)
from reconcile.gql_definitions.cluster_auth_rhidp.clusters import ClusterV1
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils.ocm.base import ClusterDetails
from reconcile.utils.ocm.label_sources import LabelState
from reconcile.utils.ocm_base_client import OCMBaseClient


def test_cluster_auth_rhidp_early_exit(
    query_func: Callable, intg: ClusterAuthRhidpIntegration
) -> None:
    early_exit_state = intg.get_early_exit_desired_state(query_func)
    assert early_exit_state == {
        "hash": "e73e956c58e69a5f545f4f624c731a2532c6724e473ec4e6f3227a9ae8d6c5ba"
    }


def test_cluster_auth_rhidp_get_clusters(
    clusters: Iterable[ClusterV1], gql_class_factory: Callable
) -> None:
    assert clusters == [
        gql_class_factory(
            ClusterV1,
            {
                "name": "cluster-no-rhidp-auth",
                "ocm": {
                    "environment": {
                        "name": "ocm-stage",
                        "labels": "{}",
                        "accessTokenClientSecret": {
                            "field": "client_secret",
                            "path": "path/to/client_secret",
                        },
                    },
                    "orgId": "org-id-1",
                },
                "spec": {"id": "cluster-no-rhidp-auth_id"},
                "auth": [
                    {
                        "service": "oidc",
                        "name": "whatever",
                    }
                ],
            },
        ),
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
                "auth": [
                    {
                        "service": "rhidp",
                        "name": "whatever",
                    }
                ],
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
                "auth": [
                    {
                        "service": "rhidp",
                        "name": "whatever",
                        "status": "disabled",
                        "issuer": "https://example.com",
                    }
                ],
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
                    "orgId": "org-id-3",
                },
                "spec": {"id": "cluster-3_id"},
                "auth": [],
            },
        ),
    ]


def test_cluster_auth_rhidp_init_ocm_apis(
    intg: ClusterAuthRhidpIntegration,
    envs: Iterable[OCMEnvironment],
    ocm_base_client: OCMBaseClient,
) -> None:
    def init_ocm_base_client_fake(*args, **kwargs) -> OCMBaseClient:  # type: ignore
        return ocm_base_client

    ocm_apis = intg.init_ocm_apis(envs, init_ocm_base_client=init_ocm_base_client_fake)
    assert len(ocm_apis) == 2


def test_cluster_auth_rhidp_fetch_desired_state(
    intg: ClusterAuthRhidpIntegration,
    clusters: list[ClusterV1],
    desired_state: LabelState,
) -> None:
    assert intg.fetch_desired_state(clusters) == desired_state


def test_cluster_auth_rhidp_fetch_current_state(
    mocker: MockerFixture,
    ocm_apis: OcmApis,
    intg: ClusterAuthRhidpIntegration,
    clusters: Iterable[ClusterV1],
    ocm_clusters: Sequence[ClusterDetails],
    current_state: LabelState,
) -> None:
    mocker.patch(
        "reconcile.cluster_auth_rhidp.integration.discover_clusters_for_organizations",
        autospec=True,
        side_effect=[
            # ocm-prod
            ocm_clusters[0:1],
            # ocm-stage
            ocm_clusters[1:],
        ],
    )

    assert (
        intg.fetch_current_state(
            ocm_apis, clusters, managed_label_prefixes=["sre-capabilities.rhidp"]
        )
        == current_state
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_cluster_auth_rhidp_reconcile(
    mocker: MockerFixture,
    intg: ClusterAuthRhidpIntegration,
    current_state: LabelState,
    desired_state: LabelState,
    ocm_base_client: OCMBaseClient,
    ocm_apis: OcmApis,
    dry_run: bool,
) -> None:
    add_label_mock = mocker.patch(
        "reconcile.cluster_auth_rhidp.integration.add_label",
        autospec=True,
    )
    update_label_mock = mocker.patch(
        "reconcile.cluster_auth_rhidp.integration.update_label",
        autospec=True,
    )
    delete_label_mock = mocker.patch(
        "reconcile.cluster_auth_rhidp.integration.delete_label",
        autospec=True,
    )
    intg.reconcile(
        dry_run,
        ocm_apis,
        current_state,
        desired_state,
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
                label="sre-capabilities.rhidp.status",
                value="enabled",
            ),
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-1-sub-id/labels",
                label="sre-capabilities.rhidp.name",
                value="whatever",
            ),
        ]
        assert add_label_mock.call_count == len(add_calls)
        add_label_mock.assert_has_calls(add_calls, any_order=True)

        update_calls = [
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-2-sub-id/labels",
                label="sre-capabilities.rhidp.status",
                value="disabled",
            )
        ]
        assert update_label_mock.call_count == len(update_calls)
        update_label_mock.assert_has_calls(update_calls, any_order=True)

        delete_calls = [
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-3-sub-id/labels",
                label="sre-capabilities.rhidp.status",
            ),
            call(
                ocm_api=ocm_base_client,
                label_container_href="/api/accounts_mgmt/v1/subscriptions/cluster-3-sub-id/labels",
                label="sre-capabilities.rhidp.name",
            ),
        ]
        assert delete_label_mock.call_count == len(delete_calls)
        delete_label_mock.assert_has_calls(delete_calls, any_order=True)
