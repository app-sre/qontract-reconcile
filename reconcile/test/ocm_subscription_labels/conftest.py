from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from typing import (
    Any,
    Optional,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.ocm_subscription_labels.clusters import ClusterV1
from reconcile.ocm_subscription_labels.integration import (
    ClusterLabelState,
    ClusterStates,
    EnvWithClusters,
    OcmLabelsIntegration,
    OcmLabelsIntegrationParams,
)
from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.ocm.base import (
    ClusterDetails,
    OCMCapability,
    build_label_container,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ocm_subscription_labels")


@pytest.fixture
def ocm_subscription_labels(
    secret_reader: SecretReader,
    mocker: MockerFixture,
    ocm_base_client: OCMBaseClient,
) -> OcmLabelsIntegration:
    mocker.patch.object(OcmLabelsIntegration, "secret_reader", secret_reader)
    intg = OcmLabelsIntegration(
        OcmLabelsIntegrationParams(managed_label_prefixes=["my-label-prefix"])
    )
    intg.ocm_apis = {
        "ocm-prod": ocm_base_client,
        "ocm-stage": ocm_base_client,
    }
    return intg


@pytest.fixture
def cluster_query_func(
    fx: Fixtures,
    data_factory: Callable[[type[ClusterV1], Mapping[str, Any]], Mapping[str, Any]],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return {
            "clusters": [
                data_factory(ClusterV1, c)
                for c in fx.get_anymarkup("clusters.yml")["clusters"]
            ]
        }

    return q


@pytest.fixture
def clusters(
    ocm_subscription_labels: OcmLabelsIntegration, cluster_query_func: Callable
) -> list[ClusterV1]:
    return ocm_subscription_labels.get_clusters(cluster_query_func)


@pytest.fixture
def ocm_base_client(mocker: MockerFixture) -> OCMBaseClient:
    return mocker.create_autospec(spec=OCMBaseClient)


@pytest.fixture
def envs(
    clusters: Sequence[ClusterV1],
    gql_class_factory: Callable,
    ocm_base_client: OCMBaseClient,
) -> list[ClusterV1]:
    return [
        gql_class_factory(
            EnvWithClusters,
            {
                "env": {
                    "name": "ocm-prod",
                    "accessTokenClientSecret": {
                        "field": "client_secret",
                        "path": "path/to/client_secret",
                    },
                },
                "ocm_api": ocm_base_client,
                "clusters": clusters[0:1],
            },
        ),
        gql_class_factory(
            EnvWithClusters,
            {
                "env": {
                    "name": "ocm-stage",
                    "accessTokenClientSecret": {
                        "field": "client_secret",
                        "path": "path/to/client_secret",
                    },
                },
                "ocm_api": ocm_base_client,
                "clusters": clusters[1:],
            },
        ),
    ]


@pytest.fixture
def build_cluster_details() -> Callable:
    def _(
        name: str = "cluster_name",
        org_id: str = "org_id",
        subs_labels: Optional[list[tuple[str, str]]] = None,
    ) -> ClusterDetails:
        ocm_cluster = build_ocm_cluster(name)
        return ClusterDetails(
            ocm_cluster=ocm_cluster,
            organization_id=org_id,
            organization_labels=build_label_container([]),
            subscription_labels=build_label_container(
                [
                    build_subscription_label(k, v, ocm_cluster.subscription.id)
                    for k, v in subs_labels or []
                ],
            ),
            capabilities={
                "foo": OCMCapability(name="foo", value="bar"),
            },
        )

    return _


@pytest.fixture
def ocm_clusters(build_cluster_details: Callable) -> list[ClusterDetails]:
    return [
        build_cluster_details(
            name="cluster-1",
            org_id="org-id-1",
            subs_labels=[
                ("my-label-prefix.to-be-removed", "enabled"),
                ("my-label-prefix.to-be-changed", "disabled"),
                ("do-not-touch", "enabled"),
            ],
        ),
        build_cluster_details(
            name="cluster-2",
            org_id="org-id-2",
            subs_labels=[
                ("another-do-not-touch-attribute", "something-else"),
            ],
        ),
        build_cluster_details(
            name="cluster-3",
            org_id="org-id-2",
            subs_labels=[
                ("my-label-prefix.to-be-removed", "enabled"),
            ],
        ),
    ]


@pytest.fixture
def current_state(
    gql_class_factory: Callable,
    ocm_clusters: Sequence[ClusterDetails],
    ocm_base_client: OCMBaseClient,
) -> ClusterStates:
    return {
        "cluster-1": gql_class_factory(
            ClusterLabelState,
            {
                "env": {
                    "name": "ocm-prod",
                    "accessTokenClientSecret": {
                        "field": "client_secret",
                        "path": "path/to/client_secret",
                    },
                },
                "ocm_api": ocm_base_client,
                "cluster_details": ocm_clusters[0],
                "labels": {
                    "my-label-prefix.to-be-changed": "disabled",
                    "my-label-prefix.to-be-removed": "enabled",
                },
            },
        ),
        "cluster-2": gql_class_factory(
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
                "cluster_details": ocm_clusters[1],
                "labels": {},
            },
        ),
        "cluster-3": gql_class_factory(
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
                "cluster_details": ocm_clusters[2],
                "labels": {
                    "my-label-prefix.to-be-removed": "enabled",
                },
            },
        ),
    }


@pytest.fixture
def desired_state(
    gql_class_factory: Callable,
    ocm_clusters: Sequence[ClusterDetails],
    ocm_base_client: OCMBaseClient,
) -> ClusterStates:
    return {
        "cluster-1": gql_class_factory(
            ClusterLabelState,
            {
                "env": {
                    "name": "ocm-prod",
                    "accessTokenClientSecret": {
                        "field": "client_secret",
                        "path": "path/to/client_secret",
                    },
                },
                "ocm_api": ocm_base_client,
                "cluster_details": ocm_clusters[0],
                "labels": {
                    "my-label-prefix.to-be-changed": "enabled",
                    "my-label-prefix.to-be-added": "enabled",
                },
            },
        ),
        "cluster-2": gql_class_factory(
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
                "cluster_details": ocm_clusters[1],
                "labels": {},
            },
        ),
        "cluster-3": gql_class_factory(
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
                "cluster_details": ocm_clusters[2],
                "labels": {
                    "my-label-prefix.to-be-added": "enabled",
                },
            },
        ),
    }
