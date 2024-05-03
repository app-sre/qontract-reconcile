from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.cluster_auth_rhidp.integration import (
    ClusterAuthRhidpIntegration,
    ClusterAuthRhidpIntegrationParams,
    OcmApis,
)
from reconcile.gql_definitions.cluster_auth_rhidp.clusters import ClusterV1
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import build_ocm_cluster
from reconcile.test.ocm.test_utils_ocm_labels import build_subscription_label
from reconcile.utils.ocm.base import (
    ClusterDetails,
    OCMCapability,
    build_label_container,
)
from reconcile.utils.ocm.label_sources import ClusterRef, LabelState
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("cluster_auth_rhidp")


@pytest.fixture
def intg(
    secret_reader: SecretReader, mocker: MockerFixture
) -> ClusterAuthRhidpIntegration:
    mocker.patch.object(ClusterAuthRhidpIntegration, "secret_reader", secret_reader)
    return ClusterAuthRhidpIntegration(ClusterAuthRhidpIntegrationParams())


@pytest.fixture
def query_func(
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
    intg: ClusterAuthRhidpIntegration, query_func: Callable
) -> list[ClusterV1]:
    return intg.get_clusters(query_func)


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
def ocm_apis(
    intg: ClusterAuthRhidpIntegration,
    envs: Iterable[OCMEnvironment],
    ocm_base_client: OCMBaseClient,
) -> OcmApis:
    def init_ocm_base_client_fake(*args, **kwargs) -> OCMBaseClient:  # type: ignore
        return ocm_base_client

    return intg.init_ocm_apis(envs, init_ocm_base_client=init_ocm_base_client_fake)


@pytest.fixture
def build_cluster_details() -> Callable:
    def _(
        name: str = "cluster_name",
        org_id: str = "org_id",
        subs_labels: list[tuple[str, str]] | None = None,
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
                ("do-not-touch", "enabled"),
            ],
        ),
        build_cluster_details(
            name="cluster-2",
            org_id="org-id-2",
            subs_labels=[
                ("sre-capabilities.rhidp.issuer", "https://example.com"),
                ("sre-capabilities.rhidp.name", "whatever"),
                ("sre-capabilities.rhidp.status", "enabled"),
            ],
        ),
        build_cluster_details(
            name="cluster-3",
            org_id="org-id-3",
            subs_labels=[
                ("sre-capabilities.rhidp.name", "whatever"),
                ("sre-capabilities.rhidp.status", "enabled"),
            ],
        ),
        # other cluster in org which must be ignored
        build_cluster_details(
            name="cluster-4",
            org_id="org-id-4",
            subs_labels=[
                ("sre-capabilities.rhidp.name", "whatever"),
                ("sre-capabilities.rhidp.status", "enabled"),
            ],
        ),
    ]


@pytest.fixture
def current_state(
    ocm_clusters: Sequence[ClusterDetails],
) -> LabelState:
    return {
        ClusterRef(
            ocm_env="ocm-prod",
            label_container_href=f"{ocm_clusters[0].ocm_cluster.subscription.href}/labels",
            cluster_id=ocm_clusters[0].ocm_cluster.id,
            org_id=ocm_clusters[0].organization_id,
            name=ocm_clusters[0].ocm_cluster.name,
        ): {},
        ClusterRef(
            ocm_env="ocm-stage",
            label_container_href=f"{ocm_clusters[1].ocm_cluster.subscription.href}/labels",
            cluster_id=ocm_clusters[1].ocm_cluster.id,
            org_id=ocm_clusters[1].organization_id,
            name=ocm_clusters[1].ocm_cluster.name,
        ): {
            "sre-capabilities.rhidp.issuer": "https://example.com",
            "sre-capabilities.rhidp.name": "whatever",
            "sre-capabilities.rhidp.status": "enabled",
        },
        ClusterRef(
            ocm_env="ocm-stage",
            label_container_href=f"{ocm_clusters[2].ocm_cluster.subscription.href}/labels",
            cluster_id=ocm_clusters[2].ocm_cluster.id,
            org_id=ocm_clusters[2].organization_id,
            name=ocm_clusters[2].ocm_cluster.name,
        ): {
            "sre-capabilities.rhidp.name": "whatever",
            "sre-capabilities.rhidp.status": "enabled",
        },
    }


@pytest.fixture
def desired_state() -> LabelState:
    return {
        ClusterRef(
            ocm_env="ocm-stage",
            label_container_href=None,
            cluster_id="cluster-2_id",
            org_id="org-id-2",
            name="cluster-2",
        ): {
            "sre-capabilities.rhidp.issuer": "https://example.com",
            "sre-capabilities.rhidp.name": "whatever",
            "sre-capabilities.rhidp.status": "disabled",
        },
        ClusterRef(
            ocm_env="ocm-prod",
            label_container_href=None,
            cluster_id="cluster-1_id",
            org_id="org-id-1",
            name="cluster-1",
        ): {
            "sre-capabilities.rhidp.name": "whatever",
            "sre-capabilities.rhidp.status": "enabled",
        },
        ClusterRef(
            ocm_env="ocm-stage",
            label_container_href=None,
            cluster_id="cluster-no-rhidp-auth_id",
            org_id="org-id-1",
            name="cluster-no-rhidp-auth",
        ): {},
        ClusterRef(
            ocm_env="ocm-stage",
            label_container_href=None,
            cluster_id="cluster-3_id",
            org_id="org-id-3",
            name="cluster-3",
        ): {},
    }
