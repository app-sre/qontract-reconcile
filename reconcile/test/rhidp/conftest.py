from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.ocm.types import OCMOidcIdp
from reconcile.rhidp import common
from reconcile.rhidp.ocm_oidc_idp import integration
from reconcile.test.fixtures import Fixtures
from reconcile.test.ocm.fixtures import build_label
from reconcile.utils.ocm import OCMMap
from reconcile.utils.ocm.labels import (
    LabelContainer,
    build_label_container,
)


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("rhidp")


@pytest.fixture
def cluster_query_func(fx: Fixtures) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fx.get_anymarkup("clusters.yml")

    return q


@pytest.fixture
def clusters(cluster_query_func: Callable) -> list[ClusterV1]:
    return common.get_clusters(
        integration.QONTRACT_INTEGRATION, cluster_query_func, "https://issuer.url"
    )


@pytest.fixture
def clusters_to_act_on(clusters: list[ClusterV1]) -> list[ClusterV1]:
    return [c for c in clusters if c.name in ["cluster-1", "cluster-2", "cluster-3"]]


@pytest.fixture
def ocm_map(mocker: MockerFixture, fx: Fixtures) -> Mock:
    ocm_map_mock = mocker.create_autospec(OCMMap)
    side_effects = []
    for result in fx.get_anymarkup("get_oidc_idps.yml"):
        side_effects.append([OCMOidcIdp(**i) for i in result])
    ocm_map_mock.get.return_value.get_oidc_idps.side_effect = side_effects
    return ocm_map_mock


@pytest.fixture
def build_cluster_rhidp_labels() -> LabelContainer:
    labels = [
        build_label(common.RHIDP_LABEL_KEY, "enabled"),
    ]
    return build_label_container(labels)


@pytest.fixture
def ocm_env() -> OCMEnvironment:
    return OCMEnvironment(
        name="env",
        url="https://ocm",
        accessTokenUrl="https://sso/token",
        accessTokenClientId="client-id",
        accessTokenClientSecret=VaultSecret(
            field="client-secret", path="path", format=None, version=None
        ),
    )
