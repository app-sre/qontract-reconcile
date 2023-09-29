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

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.ocm_labels.clusters import ClusterV1
from reconcile.ocm_labels.integration import (
    ClusterSubscriptionLabelSource,
    OcmLabelsIntegration,
    OcmLabelsIntegrationParams,
    init_cluster_subscription_label_source,
)
from reconcile.ocm_labels.label_sources import (
    ClusterRef,
    LabelOwnerRef,
)
from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.helpers import flatten
from reconcile.utils.ocm.base import (
    ClusterDetails,
    OCMCapability,
    build_label_container,
)
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("ocm_labels")


@pytest.fixture
def ocm_labels(
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
    ocm_labels: OcmLabelsIntegration, cluster_query_func: Callable
) -> list[ClusterV1]:
    return ocm_labels.get_clusters(cluster_query_func)


@pytest.fixture
def ocm_base_client(mocker: MockerFixture) -> OCMBaseClient:
    return mocker.create_autospec(spec=OCMBaseClient)


@pytest.fixture
def envs(gql_class_factory: Callable) -> list[OCMEnvironment]:
    return [
        gql_class_factory(
            OCMEnvironment,
            {
                "name": "ocm-prod",
                "accessTokenClientSecret": {
                    "field": "client_secret",
                    "path": "path/to/client_secret",
                },
            },
        ),
        gql_class_factory(
            OCMEnvironment,
            {
                "name": "ocm-stage",
                "accessTokenClientSecret": {
                    "field": "client_secret",
                    "path": "path/to/client_secret",
                },
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
        ocm_cluster = build_ocm_cluster(name, subs_id=f"{name}-sub-id")
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
def subscription_label_current_state(
    ocm_clusters: Sequence[ClusterDetails],
) -> dict[LabelOwnerRef, dict[str, str]]:
    return {
        ClusterRef(
            cluster_id=ocm_clusters[0].ocm_cluster.id,
            org_id=ocm_clusters[0].organization_id,
            ocm_env="ocm-prod",
            name=ocm_clusters[0].ocm_cluster.name,
            label_container_href=f"{ocm_clusters[0].ocm_cluster.subscription.href}/labels",
        ): {
            "my-label-prefix.to-be-changed": "disabled",
            "my-label-prefix.to-be-removed": "enabled",
        },
        ClusterRef(
            cluster_id=ocm_clusters[1].ocm_cluster.id,
            org_id=ocm_clusters[1].organization_id,
            ocm_env="ocm-stage",
            name=ocm_clusters[1].ocm_cluster.name,
            label_container_href=f"{ocm_clusters[1].ocm_cluster.subscription.href}/labels",
        ): {},
        ClusterRef(
            cluster_id=ocm_clusters[2].ocm_cluster.id,
            org_id=ocm_clusters[2].organization_id,
            ocm_env="ocm-stage",
            name=ocm_clusters[2].ocm_cluster.name,
            label_container_href=f"{ocm_clusters[2].ocm_cluster.subscription.href}/labels",
        ): {
            "my-label-prefix.to-be-removed": "enabled",
        },
    }


@pytest.fixture
def cluster_file_subscription_label_source(
    clusters: list[ClusterV1],
    ocm_labels: OcmLabelsIntegration,
) -> ClusterSubscriptionLabelSource:
    return init_cluster_subscription_label_source(clusters)


@pytest.fixture
def subscription_label_desired_state(
    clusters: Sequence[ClusterV1],
) -> dict[LabelOwnerRef, dict[str, str]]:
    desired: dict[LabelOwnerRef, dict[str, str]] = {
        ClusterRef(
            cluster_id=cluster.spec.q_id,
            org_id=cluster.ocm.org_id,
            ocm_env=cluster.ocm.environment.name,
            name=cluster.name,
            label_container_href=None,
        ): flatten(cluster.ocm_subscription_labels or {})
        for cluster in clusters
        if cluster.spec and cluster.spec.q_id and cluster.ocm  # mypy again :(
    }
    if len(clusters) != len(desired):
        raise RuntimeError("not all clusers had spec and ocm. should not happen")
    return desired
